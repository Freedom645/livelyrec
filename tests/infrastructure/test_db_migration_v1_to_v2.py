"""v1 → v2 DB マイグレーションのテスト（FR-REC-039）。

v1 で作られた play_session（chart_id NOT NULL）が、open_database 呼び出しによって
chart_id NULL 許容＋raw_song_text 追加＋idx_session_started_at 付きの v2 へ
自動マイグレーションされることを検証する。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from livelyrec.infrastructure.repository.connection import open_database

# v1 当時の DDL（テスト用にここに固定。実装の DDL_V2 と区別するため複製しておく）
_DDL_V1 = """
CREATE TABLE song (
    song_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_norm TEXT NOT NULL,
    genre TEXT,
    has_upper INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);
CREATE TABLE chart (
    chart_id TEXT PRIMARY KEY,
    song_id TEXT NOT NULL REFERENCES song(song_id) ON DELETE CASCADE,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('EASY','NORMAL','HYPER','EX','UPPER')),
    is_upper INTEGER NOT NULL DEFAULT 0,
    level INTEGER,
    UNIQUE (song_id, difficulty, is_upper)
);
CREATE TABLE play_session (
    session_id TEXT PRIMARY KEY,
    chart_id TEXT NOT NULL REFERENCES chart(chart_id) ON DELETE RESTRICT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    business_date TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    final_status TEXT NOT NULL CHECK (final_status IN
        ('IN_PROGRESS','COMPLETED','SKIPPED','RETRIED_OUT','ABANDONED')),
    obs_scene TEXT,
    obs_source TEXT,
    resolution TEXT
);
CREATE TABLE result (
    session_id TEXT PRIMARY KEY REFERENCES play_session(session_id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100000),
    cool INTEGER NOT NULL CHECK (cool >= 0),
    great INTEGER NOT NULL CHECK (great >= 0),
    good INTEGER NOT NULL CHECK (good >= 0),
    bad INTEGER NOT NULL CHECK (bad >= 0),
    combo INTEGER NOT NULL CHECK (combo >= 0),
    clear_type TEXT NOT NULL CHECK (clear_type IN ('PERFECT','FULL_COMBO','CLEAR','FAILED')),
    medal TEXT NOT NULL,
    rank TEXT NOT NULL,
    best_score_diff INTEGER,
    recorded_at TEXT NOT NULL
);
CREATE TABLE retry (
    retry_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES play_session(session_id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL
);
CREATE TABLE business_day (
    business_date TEXT PRIMARY KEY,
    rolled_at TEXT NOT NULL
);
CREATE TABLE daily_keycount (
    business_date TEXT NOT NULL REFERENCES business_day(business_date) ON DELETE CASCADE,
    judgement TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (business_date, judgement)
);
CREATE TABLE app_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT);
INSERT INTO schema_version VALUES (1, datetime('now'), 'initial');
"""


def _seed_v1_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_DDL_V1)
        # song/chart/play_session のサンプルデータ
        conn.execute(
            "INSERT INTO song VALUES ('popn-1','t','t',NULL,0,?)",
            (datetime.now(UTC).isoformat(),),
        )
        conn.execute(
            "INSERT INTO chart VALUES ('popn-1:HYPER:0','popn-1','HYPER',0,36)"
        )
        conn.execute(
            """INSERT INTO play_session
                 (session_id, chart_id, started_at, business_date,
                  attempt_count, final_status)
               VALUES ('s1','popn-1:HYPER:0',?,?,1,'COMPLETED')""",
            (datetime.now(UTC).isoformat(), "2026-05-28"),
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_keeps_existing_rows_and_allows_null_chart_id(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite3"
    _seed_v1_db(db_path)

    conn = open_database(db_path)
    try:
        # schema_version が 2 に更新されている
        version_rows = conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        versions = [r[0] for r in version_rows]
        assert 1 in versions
        assert 2 in versions

        # 既存行が残っている
        row = conn.execute(
            "SELECT chart_id FROM play_session WHERE session_id = 's1'"
        ).fetchone()
        assert row[0] == "popn-1:HYPER:0"

        # chart_id NULL の行が挿入できる
        conn.execute(
            """INSERT INTO play_session
                 (session_id, chart_id, started_at, business_date,
                  attempt_count, final_status, raw_song_text)
               VALUES ('s2', NULL, ?, '2026-05-28', 1, 'COMPLETED', '?')""",
            (datetime.now(UTC).isoformat(),),
        )
        null_row = conn.execute(
            "SELECT chart_id, raw_song_text FROM play_session WHERE session_id='s2'"
        ).fetchone()
        assert null_row[0] is None
        assert null_row[1] == "?"

        # idx_session_started_at が作られている
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_session_started_at",),
        ).fetchall()
        assert idx_rows
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """2 回連続で open しても問題ないこと（再起動時の保護）。"""
    db_path = tmp_path / "old.sqlite3"
    _seed_v1_db(db_path)
    open_database(db_path).close()
    # 2 度目
    conn = open_database(db_path)
    try:
        version_rows = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        assert version_rows[0] == 2
    finally:
        conn.close()
