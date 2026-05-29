"""ポータブル構成のパス解決（AppPaths）のテスト。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from livelyrec.shared.exceptions import DataFolderNotWritableError
from livelyrec.shared.paths import AppPaths, _find_repo_root, ensure_data_folder_writable


def _make_paths(
    base: Path, data_dir: Path | None = None, bundle: Path | None = None
) -> AppPaths:
    data = data_dir if data_dir is not None else base
    bundle_dir = bundle if bundle is not None else base
    return AppPaths(
        root=base,
        bundle_dir=bundle_dir,
        data_dir=data,
        settings_file=data / "settings.json",
        db_file=data / "db" / "livelyrec.sqlite3",
        logs_dir=data / "logs",
        export_dir=data / "export",
        crash_dir=data / "crash",
        debug_dir=data / "debug",
        result_dir=data / "result",
        banner_dir=data / "banner",
        banners_ref_dir=data / "banners_ref",
        templates_dir=bundle_dir / "templates",
        browser_source_dir=bundle_dir / "browser_source",
        master_seed_file=bundle_dir / "data" / "master.json",
        banner_features_seed_file=bundle_dir / "data" / "banner_features.json",
        banner_features_cache_file=data / "banner_features.json",
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
    # 開発時は bundle_dir == root（リポジトリルート）
    assert paths.bundle_dir == paths.root
    assert paths.templates_dir == paths.bundle_dir / "templates"
    assert paths.browser_source_dir == paths.bundle_dir / "browser_source"
    assert paths.master_seed_file == paths.bundle_dir / "data" / "master.json"


def test_detect_frozen_resolves_bundle_from_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PyInstaller frozen 時、bundle_dir は sys._MEIPASS（_internal）を指し、
    root（exe の隣）と分離されること。
    """
    exe_dir = tmp_path / "LivelyRec"
    exe_dir.mkdir()
    fake_exe = exe_dir / "LivelyRec.exe"
    fake_exe.write_bytes(b"")
    meipass = exe_dir / "_internal"
    meipass.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    paths = AppPaths.detect()

    assert paths.root == exe_dir
    assert paths.bundle_dir == meipass
    assert paths.templates_dir == meipass / "templates"
    assert paths.browser_source_dir == meipass / "browser_source"
    assert paths.master_seed_file == meipass / "data" / "master.json"
    # ユーザデータは exe の隣（書込み可能側）
    assert paths.data_dir == exe_dir / "livelyrec_data"


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
