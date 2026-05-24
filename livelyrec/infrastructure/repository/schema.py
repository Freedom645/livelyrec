"""SQLite スキーマ定義（DDL）。

詳細: docs/design/07_詳細設計_DB設計.md §2
"""

from __future__ import annotations

LATEST_SCHEMA_VERSION = 1

DDL_V1 = """
CREATE TABLE IF NOT EXISTS song (
    song_id    TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    title_norm TEXT NOT NULL,
    genre      TEXT,
    has_upper  INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_song_title_norm ON song(title_norm);

CREATE TABLE IF NOT EXISTS chart (
    chart_id   TEXT PRIMARY KEY,
    song_id    TEXT NOT NULL REFERENCES song(song_id) ON DELETE CASCADE,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('EASY','NORMAL','HYPER','EX','UPPER')),
    is_upper   INTEGER NOT NULL DEFAULT 0,
    level      INTEGER,
    UNIQUE (song_id, difficulty, is_upper)
);
CREATE INDEX IF NOT EXISTS idx_chart_song ON chart(song_id);

CREATE TABLE IF NOT EXISTS play_session (
    session_id    TEXT PRIMARY KEY,
    chart_id      TEXT NOT NULL REFERENCES chart(chart_id) ON DELETE RESTRICT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    business_date TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    final_status  TEXT NOT NULL CHECK (final_status IN
                      ('IN_PROGRESS','COMPLETED','SKIPPED','RETRIED_OUT','ABANDONED')),
    obs_scene     TEXT,
    obs_source    TEXT,
    resolution    TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_business_date ON play_session(business_date);
CREATE INDEX IF NOT EXISTS idx_session_chart ON play_session(chart_id);

CREATE TABLE IF NOT EXISTS result (
    session_id       TEXT PRIMARY KEY REFERENCES play_session(session_id) ON DELETE CASCADE,
    score            INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100000),
    cool             INTEGER NOT NULL CHECK (cool >= 0),
    great            INTEGER NOT NULL CHECK (great >= 0),
    good             INTEGER NOT NULL CHECK (good >= 0),
    bad              INTEGER NOT NULL CHECK (bad >= 0),
    combo            INTEGER NOT NULL CHECK (combo >= 0),
    clear_type       TEXT NOT NULL CHECK (clear_type IN
                         ('PERFECT','FULL_COMBO','CLEAR','FAILED')),
    medal            TEXT NOT NULL,
    rank             TEXT NOT NULL,
    best_score_diff  INTEGER,
    recorded_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_result_score ON result(score);

CREATE TABLE IF NOT EXISTS retry (
    retry_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES play_session(session_id) ON DELETE CASCADE,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retry_session ON retry(session_id);

CREATE TABLE IF NOT EXISTS business_day (
    business_date TEXT PRIMARY KEY,
    rolled_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_keycount (
    business_date TEXT NOT NULL REFERENCES business_day(business_date) ON DELETE CASCADE,
    judgement     TEXT NOT NULL CHECK (judgement IN ('COOL','GREAT','GOOD','BAD','TOTAL')),
    count         INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (business_date, judgement)
);

CREATE TABLE IF NOT EXISTS app_kv (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    note       TEXT
);
"""
