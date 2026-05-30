"""アプリ設定の永続化（平文 JSON）。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §7
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from livelyrec.shared.constants import (
    DEFAULT_BUSINESS_DAY_ROLLOVER_HOUR,
    DEFAULT_FPS,
    DEFAULT_OBS_HOST,
    DEFAULT_OBS_PORT,
    DEFAULT_WS_HOST,
    DEFAULT_WS_PORT,
    SCHEMA_VERSION,
)
from livelyrec.shared.exceptions import ConfigError

logger = logging.getLogger("livelyrec.config")


@dataclass
class ObsSettings:
    host: str = DEFAULT_OBS_HOST
    port: int = DEFAULT_OBS_PORT
    source_name: str = ""
    password: str = ""
    password_persist: bool = True


@dataclass
class RecordingSettings:
    fps: int = DEFAULT_FPS
    business_day_rollover_hour: int = DEFAULT_BUSINESS_DAY_ROLLOVER_HOUR
    debug_capture: bool = False


@dataclass
class WebSocketServerSettings:
    host: str = DEFAULT_WS_HOST
    port: int = DEFAULT_WS_PORT
    lan_publish: bool = False
    token: str = ""


@dataclass
class UpdateSettings:
    auto_update: bool = True
    check_on_startup: bool = True


@dataclass
class BrowserSourceSettings:
    theme_url: str | None = None


@dataclass
class MasterSettings:
    # 楽曲マスタ配信先 URL（GitHub Pages 既定）。空にすると同梱 seed のみで動作。
    endpoint_url: str = "https://Freedom645.github.io/livelyrec/master.json"


@dataclass
class LoggingSettings:
    level: str = "INFO"


@dataclass
class ResultCaptureSettings:
    """リザルト画面の自動スクリーンショット設定（FR-REC-046〜048）。

    - `enabled`: 有効/無効（既定 False）
    - `output_dir`: 保存先パス文字列。None または空文字なら AppPaths.result_dir
      をフォールバックとして使う。
    """

    enabled: bool = False
    output_dir: str | None = None


@dataclass
class DeveloperSettings:
    """開発者支援機能の設定（FR-DEV-001〜004）。

    - `banner_capture_enabled`: リザルト画面のバナー画像保存 ON/OFF（既定 False）
    - `banner_dir`: 保存先パス文字列。None または空文字なら AppPaths.banner_dir。
    """

    banner_capture_enabled: bool = False
    banner_dir: str | None = None


@dataclass
class BannerSettings:
    """バナー画像認識（2 次認識器）の設定（FR-BAN-003, FR-BAN-004、v2.0/v0.8）。

    - `match_enabled`: バナー特徴量マッチを使う ON/OFF（既定 True）
    - `endpoint_url`: `banner_features.json` の配信エンドポイント
      （GitHub Releases 等）。空文字なら同梱 seed のみで動作

    要件 v0.8 でバナー画像本体をアプリのランタイム動作からも完全に排除した
    ため、`auto_fetch_enabled` / `cache_dir` は廃止された。
    """

    match_enabled: bool = True
    # バナー特徴量マスタ配信先 URL（GitHub Pages 既定）。空にすると同梱 seed のみで動作。
    endpoint_url: str = "https://Freedom645.github.io/livelyrec/banner_features.json"


@dataclass
class AppSettings:
    schema_version: int = SCHEMA_VERSION
    obs: ObsSettings = field(default_factory=ObsSettings)
    recording: RecordingSettings = field(default_factory=RecordingSettings)
    websocket_server: WebSocketServerSettings = field(default_factory=WebSocketServerSettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    browser_source: BrowserSourceSettings = field(default_factory=BrowserSourceSettings)
    master: MasterSettings = field(default_factory=MasterSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    result_capture: ResultCaptureSettings = field(default_factory=ResultCaptureSettings)
    developer: DeveloperSettings = field(default_factory=DeveloperSettings)
    banner: BannerSettings = field(default_factory=BannerSettings)


class ConfigStore:
    """settings.json の読み書き。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppSettings:
        if not self._path.exists():
            settings = AppSettings()
            self.save(settings)
            return settings
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"failed to load settings: {e}") from e
        return _from_dict(data)

    def save(self, settings: AppSettings) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except OSError as e:
            raise ConfigError(f"failed to save settings: {e}") from e


def _from_dict(d: dict) -> AppSettings:
    """部分的に存在しないキーを既定値で補完して dict から復元する。

    v1 → v2 マイグレーション: `result_capture` / `developer` セクションが
    存在しない旧設定ファイルは、`AppSettings()` の既定値で自動補完される。
    """
    base = AppSettings()
    merged = asdict(base)
    _deep_update(merged, d)
    # v1 → v2 マイグレーションの観測ログ（schema_version を最新に巻き上げる）
    incoming_version = merged.get("schema_version")
    if incoming_version is not None and int(incoming_version) < SCHEMA_VERSION:
        logger.info(
            "settings migrated: v%s → v%s (added result_capture / developer)",
            incoming_version,
            SCHEMA_VERSION,
        )
    merged["schema_version"] = SCHEMA_VERSION
    return AppSettings(
        schema_version=merged["schema_version"],
        obs=ObsSettings(**merged["obs"]),
        recording=RecordingSettings(**merged["recording"]),
        websocket_server=WebSocketServerSettings(**merged["websocket_server"]),
        update=UpdateSettings(**merged["update"]),
        browser_source=BrowserSourceSettings(**merged["browser_source"]),
        master=MasterSettings(**merged["master"]),
        logging=LoggingSettings(**merged["logging"]),
        result_capture=ResultCaptureSettings(**merged["result_capture"]),
        developer=DeveloperSettings(**merged["developer"]),
        banner=BannerSettings(**_filter_banner_dict(merged["banner"])),
    )


def _filter_banner_dict(d: dict) -> dict:
    """旧 settings.json の `auto_fetch_enabled` / `cache_dir` キーを無視する。

    要件 v0.8（2026-05-29）でバナー画像本体をアプリのランタイム動作から
    排除した際に廃止したキー。旧設定ファイルにこれらが残っていてもエラーに
    せず読み飛ばす（後方互換）。
    """
    return {k: v for k, v in d.items() if k in {"match_enabled", "endpoint_url"}}


def _deep_update(target: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_update(target[k], v)
        else:
            target[k] = v
