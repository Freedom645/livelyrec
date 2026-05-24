"""MasterService と SongStabilizer のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from livelyrec.application.master_service import MasterService, SongStabilizer, _parse_master
from livelyrec.domain.master import Song
from livelyrec.domain.score import Difficulty
from livelyrec.infrastructure.repository import (
    ChartRepository,
    SongRepository,
    open_database,
)
from livelyrec.shared.exceptions import MasterFetchError, MasterParseError


@pytest.fixture
def repos(tmp_path: Path):
    conn = open_database(tmp_path / "t.sqlite3")
    yield SongRepository(conn), ChartRepository(conn)
    conn.close()


def _master_data() -> dict:
    return {
        "songs": [
            {
                "song_id": "popn-1",
                "title": "ぽぽぽかレトロード",
                # title_norm を省略すると _parse_master が自動正規化する
                "genre": "ぽかぽかレトロード",
                "has_upper": False,
                "charts": [
                    {"difficulty": "EASY", "level": 8},
                    {"difficulty": "NORMAL", "level": 24},
                    {"difficulty": "HYPER", "level": 36},
                    {"difficulty": "EX", "level": 42},
                ],
            },
            {
                "song_id": "popn-2",
                "title": "漆黒のスペシャルプリンセスサンデー",
                "genre": "VIP DANCE",
                "has_upper": False,
                "charts": [
                    {"difficulty": "HYPER", "level": 38},
                    {"difficulty": "EX", "level": 47},
                ],
            },
        ]
    }


def test_parse_master_creates_songs() -> None:
    songs = _parse_master(_master_data())
    assert len(songs) == 2
    assert songs[0].song_id == "popn-1"
    assert len(songs[0].charts) == 4


def test_identify_returns_chart(repos) -> None:
    song_repo, chart_repo = repos
    for s in _parse_master(_master_data()):
        song_repo.upsert(s)

    svc = MasterService(song_repo, chart_repo, fetcher=None, threshold=60.0)
    # OCR が誤読を含むケース
    result = svc.identify("ほかぼかレトロード", difficulty_hint=Difficulty.HYPER)
    assert result.accepted
    assert result.chart is not None
    assert result.chart.song_id == "popn-1"
    assert result.chart.difficulty == Difficulty.HYPER


def test_identify_with_no_hint_picks_priority(repos) -> None:
    song_repo, chart_repo = repos
    for s in _parse_master(_master_data()):
        song_repo.upsert(s)
    svc = MasterService(song_repo, chart_repo, fetcher=None, threshold=60.0)
    result = svc.identify("漆黒のスペシャル")
    assert result.accepted
    assert result.chart is not None
    # ヒント無し → HYPER 優先
    assert result.chart.difficulty == Difficulty.HYPER


def test_identify_below_threshold_rejected(repos) -> None:
    song_repo, chart_repo = repos
    for s in _parse_master(_master_data()):
        song_repo.upsert(s)
    svc = MasterService(song_repo, chart_repo, fetcher=None, threshold=99.0)
    result = svc.identify("全然違う楽曲名XYZ")
    assert not result.accepted
    assert result.chart is None


def test_song_stabilizer_majority_with_competing() -> None:
    s = SongStabilizer(window=5, min_majority=0.6)
    assert s.push("a") == "a"  # 1/1 ≥ 0.6 → 採用
    assert s.push("b") is None  # a:1, b:1 → 1/2 = 0.5 < 0.6
    assert s.push("a") == "a"  # a:2, b:1 → 2/3 ≈ 0.67 ≥ 0.6
    assert s.push("a") == "a"  # a:3, b:1 → 3/4 = 0.75
    assert s.push("b") == "a"  # a:3, b:2 → top=a, 3/5 = 0.6 ≥ 0.6 で採用
    # tie ケースの確認
    s2 = SongStabilizer(window=5, min_majority=0.6)
    s2.push("a")
    s2.push("a")
    s2.push("b")
    s2.push("b")
    # a:2, b:2 → tie. most_common は a を返すかは順序依存だが、いずれにせよ 2/4=0.5 < 0.6
    assert s2.push("c") is None  # a:2, b:2, c:1 → 2/5 < 0.6


def test_song_stabilizer_resets() -> None:
    s = SongStabilizer(window=3)
    s.push("a")
    s.push("a")
    s.reset()
    assert s.push("b") == "b"  # 1/1


def test_song_stabilizer_all_none_returns_none() -> None:
    s = SongStabilizer(window=3)
    assert s.push(None) is None
    assert s.push(None) is None


# ---- refresh ----

class _FakeFetcher:
    """fetch() が固定の dict／例外を返すフェイク。"""

    def __init__(self, data: dict | None = None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error

    def fetch(self) -> dict:
        if self._error is not None:
            raise self._error
        assert self._data is not None
        return self._data


def test_refresh_upserts_songs(repos) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=_FakeFetcher(data=_master_data()))
    assert svc.refresh() == 2
    assert song_repo.get("popn-1") is not None


def test_refresh_without_fetcher_returns_zero(repos) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=None)
    assert svc.refresh() == 0


def test_refresh_fetch_error_propagates(repos) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(
        song_repo, chart_repo, fetcher=_FakeFetcher(error=MasterFetchError("down"))
    )
    with pytest.raises(MasterFetchError):
        svc.refresh()


def test_refresh_parse_error_wrapped(repos) -> None:
    song_repo, chart_repo = repos
    # song_id 欠落 → _parse_master が KeyError → MasterParseError に変換される
    bad_data = {"songs": [{"title": "id 欠落の楽曲"}]}
    svc = MasterService(song_repo, chart_repo, fetcher=_FakeFetcher(data=bad_data))
    with pytest.raises(MasterParseError):
        svc.refresh()


# ---- identify の境界 ----

def test_identify_empty_text_rejected(repos) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=None)
    result = svc.identify("")
    assert not result.accepted
    assert result.chart is None


def test_identify_no_candidates_rejected(repos) -> None:
    # DB が空 → fuzzy_search が候補なし
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=None, threshold=60.0)
    result = svc.identify("どの楽曲にも無いタイトル")
    assert not result.accepted


def test_identify_margin_rejection(repos) -> None:
    # margin を極端に大きくすると、2位との差が常に不足 → 曖昧として棄却
    song_repo, chart_repo = repos
    for s in _parse_master(_master_data()):
        song_repo.upsert(s)
    svc = MasterService(song_repo, chart_repo, fetcher=None, threshold=10.0, margin=100.0)
    result = svc.identify("ぽぽぽかレトロード")
    assert not result.accepted


# ---- _select_chart / _parse_master ----

def test_select_chart_empty_charts_returns_none(repos) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=None)
    empty_song = Song(
        song_id="x", title="t", title_norm="t", genre=None, has_upper=False, charts=()
    )
    assert svc._select_chart(empty_song, None) is None


def test_parse_master_skips_invalid_difficulty() -> None:
    data = {
        "songs": [
            {
                "song_id": "x",
                "title": "テスト",
                "charts": [
                    {"difficulty": "HYPER", "level": 30},
                    {"difficulty": "INVALID_DIFF", "level": 10},  # 不正値 → スキップ
                    {"level": 5},  # difficulty キー欠落 → スキップ
                ],
            }
        ]
    }
    songs = _parse_master(data)
    assert len(songs) == 1
    assert len(songs[0].charts) == 1
    assert songs[0].charts[0].difficulty == Difficulty.HYPER


# ---- load_from_file / song_count（seed ロード, I-015） ----

def test_load_from_file_seeds_db(repos, tmp_path) -> None:
    import json

    song_repo, chart_repo = repos
    seed = tmp_path / "master.json"
    seed.write_text(json.dumps(_master_data(), ensure_ascii=False), encoding="utf-8")
    svc = MasterService(song_repo, chart_repo, fetcher=None)
    assert svc.song_count() == 0
    n = svc.load_from_file(seed)
    assert n == 2
    assert svc.song_count() == 2


def test_load_from_file_missing_raises(repos, tmp_path) -> None:
    song_repo, chart_repo = repos
    svc = MasterService(song_repo, chart_repo, fetcher=None)
    with pytest.raises(MasterParseError):
        svc.load_from_file(tmp_path / "does_not_exist.json")
