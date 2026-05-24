"""ポータブル構成のパス解決（AppPaths）のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livelyrec.shared.exceptions import DataFolderNotWritableError
from livelyrec.shared.paths import AppPaths, _find_repo_root, ensure_data_folder_writable


def _make_paths(base: Path, data_dir: Path | None = None) -> AppPaths:
    data = data_dir if data_dir is not None else base
    return AppPaths(
        root=base,
        data_dir=data,
        settings_file=data / "settings.json",
        db_file=data / "db" / "livelyrec.sqlite3",
        logs_dir=data / "logs",
        export_dir=data / "export",
        crash_dir=data / "crash",
        debug_dir=data / "debug",
        templates_dir=base / "templates",
        browser_source_dir=base / "browser_source",
        master_seed_file=base / "data" / "master.json",
    )


def test_detect_returns_structured_paths() -> None:
    paths = AppPaths.detect()
    # data_dir 配下の各サブディレクトリが生成される
    assert paths.data_dir.exists()
    assert paths.logs_dir.exists()
    assert paths.export_dir.exists()
    assert paths.crash_dir.exists()
    assert paths.db_file.parent.exists()
    # パス組み立ての整合
    assert paths.data_dir.parent == paths.root
    assert paths.settings_file == paths.data_dir / "settings.json"
    assert paths.templates_dir == paths.root / "templates"
    assert paths.browser_source_dir == paths.root / "browser_source"


def test_find_repo_root_locates_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _find_repo_root(nested) == tmp_path


def test_find_repo_root_fallback_when_not_found(tmp_path: Path) -> None:
    # pyproject.toml が見つからない深い階層 → start.parents[3] にフォールバック
    deep = tmp_path / "w" / "x" / "y" / "z"
    deep.mkdir(parents=True)
    assert _find_repo_root(deep) == tmp_path


def test_ensure_data_folder_writable_passes(tmp_path: Path) -> None:
    # 書き込めるディレクトリなら例外は発生しない
    ensure_data_folder_writable(_make_paths(tmp_path))


def test_ensure_data_folder_writable_raises_on_non_directory(tmp_path: Path) -> None:
    # data_dir が実際にはファイル → プローブ書き込みに失敗
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_text("x", encoding="utf-8")
    paths = _make_paths(tmp_path, data_dir=not_a_dir)
    with pytest.raises(DataFolderNotWritableError):
        ensure_data_folder_writable(paths)
