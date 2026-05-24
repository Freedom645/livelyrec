"""リポジトリ層のテスト（in-memory SQLite）。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from livelyrec.domain.master import Song, normalize_song_title
from livelyrec.domain.score import (
    Chart,
    ClearType,
    Difficulty,
    Judgements,
    Medal,
    Rank,
    Result,
    SessionStatus,
)
from livelyrec.infrastructure.repository import (
    AppKvRepository,
    ChartRepository,
    DailyCounterRepository,
    PlaySessionRepository,
    ResultRepository,
    SongRepository,
    open_database,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = open_database(tmp_path / "test.sqlite3")
    yield conn
    conn.close()


def _make_song() -> Song:
    return Song(
        song_id="popn-1",
        title="ぽぽぽかレトロード",
        title_norm=normalize_song_title("ぽぽぽかレトロード"),
        genre="ぽかぽかレトロード",
        has_upper=False,
        charts=(
            Chart(song_id="popn-1", title="ぽぽぽかレトロード", difficulty=Difficulty.HYPER, level=36),
            Chart(song_id="popn-1", title="ぽぽぽかレトロード", difficulty=Difficulty.EX, level=42),
        ),
    )


def test_song_upsert_and_get(db: sqlite3.Connection) -> None:
    repo = SongRepository(db)
    repo.upsert(_make_song())
    fetched = repo.get("popn-1")
    assert fetched is not None
    assert fetched.title == "ぽぽぽかレトロード"
    assert len(fetched.charts) == 2


def test_song_fuzzy_search(db: sqlite3.Connection) -> None:
    repo = SongRepository(db)
    repo.upsert(_make_song())
    # マスタには「ぽぽぽかレトロード」、OCR が「ほかぼかレトロード」を出した想定
    matches = repo.fuzzy_search("ほかぼかレトロード", limit=3)
    assert matches
    top, score = matches[0]
    assert top.song_id == "popn-1"
    assert score >= 60.0


def test_chart_repo(db: sqlite3.Connection) -> None:
    SongRepository(db).upsert(_make_song())
    repo = ChartRepository(db)
    charts = repo.list_by_song("popn-1")
    assert len(charts) == 2
    hyp = repo.get("popn-1:HYPER:0")
    assert hyp is not None
    assert hyp.difficulty == Difficulty.HYPER


def test_session_and_result_flow(db: sqlite3.Connection) -> None:
    SongRepository(db).upsert(_make_song())
    chart_repo = ChartRepository(db)
    sess_repo = PlaySessionRepository(db)
    result_repo = ResultRepository(db)

    chart = chart_repo.get("popn-1:HYPER:0")
    assert chart is not None
    started_at = datetime(2026, 5, 18, 14, 0, tzinfo=UTC)
    session = sess_repo.create(
        chart=chart,
        started_at=started_at,
        business_date=date(2026, 5, 18),
        obs_scene="main",
        obs_source="popn-game",
        resolution="1366x768",
    )

    # リトライ追加
    sess_repo.increment_attempt(session.session_id)
    sess_repo.append_retry(session.session_id, started_at)

    fetched = sess_repo.get(session.session_id)
    assert fetched is not None
    assert fetched.attempt_count == 2
    assert len(fetched.retries) == 1

    # リザルト記録
    result = Result(
        score=87268,
        judgements=Judgements(312, 18, 5, 2),
        combo=329,
        clear_type=ClearType.CLEAR,
        medal=Medal.CIRCLE,
        rank=Rank.AAA,
        best_score_diff=1234,
    )
    result_repo.upsert(session.session_id, result, started_at)

    r = result_repo.get(session.session_id)
    assert r is not None
    assert r.score == 87268
    assert r.judgements.cool == 312

    # best_score
    assert result_repo.best_score("popn-1:HYPER:0") == 87268

    # list_recent
    recent = result_repo.list_recent(limit=5)
    assert recent
    assert recent[0][0] == session.session_id


def test_daily_counter_repo(db: sqlite3.Connection) -> None:
    repo = DailyCounterRepository(db)
    d = date(2026, 5, 18)
    repo.ensure_business_day(d)
    cumulative = repo.add(d, Judgements(10, 2, 1, 0))
    assert cumulative == Judgements(10, 2, 1, 0)
    cumulative = repo.add(d, Judgements(5, 3, 0, 1))
    assert cumulative == Judgements(15, 5, 1, 1)
    repo.reset(d)
    assert repo.get(d) == Judgements()


def test_app_kv(db: sqlite3.Connection) -> None:
    repo = AppKvRepository(db)
    assert repo.get("missing") is None
    repo.set("k1", "v1")
    assert repo.get("k1") == "v1"
    repo.set("k1", "v2")
    assert repo.get("k1") == "v2"
    repo.delete("k1")
    assert repo.get("k1") is None


def test_session_status_update(db: sqlite3.Connection) -> None:
    SongRepository(db).upsert(_make_song())
    chart = ChartRepository(db).get("popn-1:EX:0")
    assert chart is not None
    sess_repo = PlaySessionRepository(db)
    started = datetime(2026, 5, 18, 14, 0, tzinfo=UTC)
    session = sess_repo.create(chart=chart, started_at=started, business_date=date(2026, 5, 18))
    sess_repo.set_status(session.session_id, SessionStatus.COMPLETED, ended_at=started)
    fetched = sess_repo.get(session.session_id)
    assert fetched is not None
    assert fetched.final_status == SessionStatus.COMPLETED
    assert fetched.ended_at is not None


def test_song_get_missing_returns_none(db: sqlite3.Connection) -> None:
    assert SongRepository(db).get("does-not-exist") is None


def test_song_upsert_many_counts(db: sqlite3.Connection) -> None:
    repo = SongRepository(db)
    n = repo.upsert_many([_make_song()])
    assert n == 1
    assert repo.get("popn-1") is not None


def test_song_count(db: sqlite3.Connection) -> None:
    repo = SongRepository(db)
    assert repo.count() == 0
    repo.upsert(_make_song())
    assert repo.count() == 1


def test_fuzzy_search_on_empty_db_returns_empty(db: sqlite3.Connection) -> None:
    # 候補が 1 件も無い → 空リスト
    assert SongRepository(db).fuzzy_search("なにかの楽曲") == []


def test_fuzzy_search_blank_query_returns_empty(db: sqlite3.Connection) -> None:
    SongRepository(db).upsert(_make_song())
    # 正規化後に空になるクエリ
    assert SongRepository(db).fuzzy_search("") == []


def test_result_get_missing_returns_none(db: sqlite3.Connection) -> None:
    assert ResultRepository(db).get("does-not-exist") is None


def test_result_list_by_chart(db: sqlite3.Connection) -> None:
    SongRepository(db).upsert(_make_song())
    chart = ChartRepository(db).get("popn-1:HYPER:0")
    assert chart is not None
    sess_repo = PlaySessionRepository(db)
    result_repo = ResultRepository(db)
    started = datetime(2026, 5, 18, 14, 0, tzinfo=UTC)
    session = sess_repo.create(chart=chart, started_at=started, business_date=date(2026, 5, 18))
    result_repo.upsert(
        session.session_id,
        Result(
            score=91000,
            judgements=Judgements(300, 10, 3, 1),
            combo=314,
            clear_type=ClearType.FULL_COMBO,
            medal=Medal.STAR_GOLD,
            rank=Rank.S,
            best_score_diff=None,
        ),
        started,
    )
    rows = result_repo.list_by_chart("popn-1:HYPER:0")
    assert len(rows) == 1
    assert rows[0][0] == session.session_id
    assert rows[0][2].score == 91000
