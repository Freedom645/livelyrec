"""`app._load_seed_if_needed` の回帰テスト（2026-05-30 バグ修正）。

ユーザ報告: master.json を修正してもアプリ再起動で古いタイトルが残る。
原因は app.py が「DB が空のときだけ seed をロード」する仕様だったため。
修正後は seed の `version` フィールドと `app_kv.master_seed_version` を
比較し、異なれば強制再ロードする。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from livelyrec.app import _load_seed_if_needed
from livelyrec.application.master_service import MasterService
from livelyrec.infrastructure.repository import (
    AppKvRepository,
    ChartRepository,
    SongRepository,
    open_database,
)


@pytest.fixture
def db(tmp_path: Path):
    """テスト用の空 DB を生成して接続を返す。"""
    db_path = tmp_path / "livelyrec.sqlite3"
    conn = open_database(db_path)
    yield conn
    conn.close()


@pytest.fixture
def master(db) -> MasterService:
    return MasterService(SongRepository(db), ChartRepository(db), fetcher=None)


@pytest.fixture
def kv(db) -> AppKvRepository:
    return AppKvRepository(db)


def _write_seed(path: Path, songs: list[dict], version: str = "2026-05-30T00:00:00Z") -> None:
    doc = {
        "version": version,
        "schema_version": 1,
        "songs": songs,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _song(song_id: str, title: str) -> dict:
    return {
        "song_id": song_id,
        "title": title,
        "title_norm": title.lower(),
        "artist": "",
        "genre": None,
        "has_upper": False,
        "charts": [
            {"difficulty": "EASY", "level": None},
            {"difficulty": "NORMAL", "level": None},
            {"difficulty": "HYPER", "level": None},
            {"difficulty": "EX", "level": None},
        ],
    }


def test_seed_loaded_when_db_empty(
    tmp_path: Path, master: MasterService, kv: AppKvRepository
) -> None:
    seed = tmp_path / "master.json"
    _write_seed(seed, [_song("popn-1", "曲A")], version="v1")
    _load_seed_if_needed(master, seed, kv, logging.getLogger("test"))
    assert master.song_count() == 1
    assert kv.get("master_seed_version") == "v1"


def test_reload_when_seed_version_differs(
    tmp_path: Path, master: MasterService, kv: AppKvRepository
) -> None:
    """既存 DB + 新しい seed version で強制再ロードされる（バグ修正の核）。"""
    seed = tmp_path / "master.json"
    # 旧 seed をロード
    _write_seed(seed, [_song("popn-1", "Old Title*初移植曲")], version="v1")
    _load_seed_if_needed(master, seed, kv, logging.getLogger("test"))
    assert master.song_count() == 1
    fetched = master.get_song("popn-1")
    assert fetched is not None
    assert fetched.title == "Old Title*初移植曲"

    # 新 seed（タイトル修正＋version 変更）でロード
    _write_seed(seed, [_song("popn-1", "Old Title")], version="v2")
    _load_seed_if_needed(master, seed, kv, logging.getLogger("test"))
    fetched2 = master.get_song("popn-1")
    assert fetched2 is not None
    assert fetched2.title == "Old Title"
    assert kv.get("master_seed_version") == "v2"


def test_skip_when_version_unchanged(
    tmp_path: Path, master: MasterService, kv: AppKvRepository
) -> None:
    """同じ version の seed では再ロードしない（性能・安定性）。"""
    seed = tmp_path / "master.json"
    _write_seed(seed, [_song("popn-1", "曲A")], version="v1")
    _load_seed_if_needed(master, seed, kv, logging.getLogger("test"))
    initial_count = master.song_count()

    # seed の内容を改変するが version は据え置き → 反映されない想定
    _write_seed(seed, [_song("popn-1", "曲A 改変")], version="v1")
    _load_seed_if_needed(master, seed, kv, logging.getLogger("test"))
    fetched = master.get_song("popn-1")
    assert fetched is not None
    assert fetched.title == "曲A"  # 改変が反映されていない
    assert master.song_count() == initial_count


def test_missing_seed_warns_but_no_crash(
    tmp_path: Path, master: MasterService, kv: AppKvRepository, caplog
) -> None:
    """seed ファイル不在でも WARN ログのみで完走する。"""
    missing = tmp_path / "does_not_exist.json"
    with caplog.at_level(logging.WARNING):
        _load_seed_if_needed(master, missing, kv, logging.getLogger("test"))
    assert any("not found" in r.message for r in caplog.records)
    assert master.song_count() == 0


def test_malformed_seed_warns_but_no_crash(
    tmp_path: Path, master: MasterService, kv: AppKvRepository, caplog
) -> None:
    """壊れた JSON でも WARN ログのみで完走する。"""
    bad = tmp_path / "bad.json"
    bad.write_text("not a valid json {", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        _load_seed_if_needed(master, bad, kv, logging.getLogger("test"))
    assert any("read failed" in r.message for r in caplog.records)
    assert master.song_count() == 0
