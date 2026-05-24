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
    """配布フォルダ直下に展開される全パスを集約。"""

    root: Path
    data_dir: Path
    settings_file: Path
    db_file: Path
    logs_dir: Path
    export_dir: Path
    crash_dir: Path
    debug_dir: Path
    templates_dir: Path
    browser_source_dir: Path
    master_seed_file: Path

    @classmethod
    def detect(cls) -> AppPaths:
        """PyInstaller 配下なら exe の隣、開発時はリポジトリルートを基準にする。"""
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            root = _find_repo_root(Path(__file__).resolve())

        data = root / DATA_DIR_NAME
        data.mkdir(exist_ok=True)
        for sub in ("db", "logs", "export", "crash", "debug"):
            (data / sub).mkdir(exist_ok=True)

        return cls(
            root=root,
            data_dir=data,
            settings_file=data / "settings.json",
            db_file=data / "db" / "livelyrec.sqlite3",
            logs_dir=data / "logs",
            export_dir=data / "export",
            crash_dir=data / "crash",
            debug_dir=data / "debug",
            templates_dir=root / "templates",
            browser_source_dir=root / "browser_source",
            master_seed_file=root / "data" / "master.json",
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
