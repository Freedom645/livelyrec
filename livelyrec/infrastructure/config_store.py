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
    endpoint_url: str = ""


@dataclass
class LoggingSettings:
    level: str = "INFO"


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
    """部分的に存在しないキーを既定値で補完して dict から復元する。"""
    base = AppSettings()
    merged = asdict(base)
    _deep_update(merged, d)
    return AppSettings(
        schema_version=merged.get("schema_version", SCHEMA_VERSION),
        obs=ObsSettings(**merged["obs"]),
        recording=RecordingSettings(**merged["recording"]),
        websocket_server=WebSocketServerSettings(**merged["websocket_server"]),
        update=UpdateSettings(**merged["update"]),
        browser_source=BrowserSourceSettings(**merged["browser_source"]),
        master=MasterSettings(**merged["master"]),
        logging=LoggingSettings(**merged["logging"]),
    )


def _deep_update(target: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_update(target[k], v)
        else:
            target[k] = v
