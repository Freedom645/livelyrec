"""ポータブル構成のパス解決。

詳細: docs/design/05_基本設計書.md §9.1、docs/design/06_詳細設計_アーキテクチャ.md §8
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .constants import DATA_DIR_NAME
from .exceptions import DataFolderNotWritableError


@dataclass(frozen=True)
class AppPaths:
    """配布フォルダに展開される全パスを集約。

    - `root` は exe の隣（書き込み可能な配布ルート）。ユーザデータ（`livelyrec_data/`）の親。
    - `bundle_dir` は配布リソース（templates・browser_source・data/master.json）の親。
      PyInstaller の onedir モードでは `sys._MEIPASS`（`root/_internal/`）を指し、
      開発時は `root` と同一（リポジトリルート）。
    """

    root: Path
    bundle_dir: Path
    data_dir: Path
    settings_file: Path
    db_file: Path
    logs_dir: Path
    export_dir: Path
    crash_dir: Path
    debug_dir: Path
    result_dir: Path     # リザルト自動スクショ既定先（FR-REC-046）
    banner_dir: Path     # 開発者向けバナー画像既定先（FR-DEV-002）
    templates_dir: Path
    browser_source_dir: Path
    master_seed_file: Path
    banner_features_seed_file: Path  # 同梱バナー特徴量 seed（FR-BAN-003、v2.0）
    banner_features_cache_file: Path  # 取得後ローカルキャッシュ（FR-BAN-004、v2.0）

    @classmethod
    def detect(cls) -> AppPaths:
        """PyInstaller 配下なら exe の隣、開発時はリポジトリルートを基準にする。"""
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
            # PyInstaller 6 の onedir では sys._MEIPASS は `root/_internal/`。
            # 配布同梱の datas（templates/browser_source/data）はそこに展開される。
            bundle = Path(getattr(sys, "_MEIPASS", root))
        else:
            root = _find_repo_root(Path(__file__).resolve())
            bundle = root

        data = root / DATA_DIR_NAME
        data.mkdir(exist_ok=True)
        for sub in (
            "db", "logs", "export", "crash", "debug",
            "result", "banner",
        ):
            (data / sub).mkdir(exist_ok=True)

        return cls(
            root=root,
            bundle_dir=bundle,
            data_dir=data,
            settings_file=data / "settings.json",
            db_file=data / "db" / "livelyrec.sqlite3",
            logs_dir=data / "logs",
            export_dir=data / "export",
            crash_dir=data / "crash",
            debug_dir=data / "debug",
            result_dir=data / "result",
            banner_dir=data / "banner",
            templates_dir=bundle / "templates",
            browser_source_dir=bundle / "browser_source",
            master_seed_file=bundle / "data" / "master.json",
            banner_features_seed_file=bundle / "data" / "banner_features.json",
            banner_features_cache_file=data / "banner_features.json",
        )


def _find_repo_root(start: Path) -> Path:
    """開発時に pyproject.toml を含むディレクトリを探す。見つからなければ start.parents[3]。"""
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return start.parents[3]


def ensure_data_folder_writable(paths: AppPaths) -> None:
    """データフォルダに書き込めるかチェック。書き込めなければ例外。"""
    probe = paths.data_dir / ".write_test"
    try:
        probe.write_bytes(b"")
    except OSError as e:  # PermissionError 等
        raise DataFolderNotWritableError(
            f"データフォルダ {paths.data_dir} に書き込めません: {e}"
        ) from e
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
