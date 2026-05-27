"""SQLite 接続とマイグレーション。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .schema import DDL_V2, LATEST_SCHEMA_VERSION, MIGRATE_V1_TO_V2

logger = logging.getLogger("livelyrec.repo")


def open_database(db_path: Path) -> sqlite3.Connection:
    """SQLite に接続し、必要ならマイグレーションを実行する。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    _migrate(conn)
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _migrate(conn: sqlite3.Connection) -> None:
    current = _current_version(conn)
    if current >= LATEST_SCHEMA_VERSION:
        return

    # v2 ベースライン（新規 DB はここでまとめて作成される）。
    # play_session_new 残骸は前回失敗の痕跡として除外しておく。
    conn.execute("DROP TABLE IF EXISTS play_session_new;")
    conn.executescript(DDL_V2)
    if _current_version(conn) < 1:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, note) VALUES (?, ?, ?)",
            (1, _now_iso(), "initial schema"),
        )

    # v1 → v2: 既存 v1 DB は play_session.chart_id が NOT NULL のため、
    # テーブル再作成方式で NULL 許容化＋raw_song_text 追加＋idx_session_started_at 追加。
    if _current_version(conn) < 2:
        try:
            if _is_v1_play_session(conn):
                logger.info("migrating play_session: v1 → v2 (NULL chart_id + raw_song_text)")
                # foreign_keys は外したうえでテーブル再作成（参照整合性は v2 ベース定義で再確立される）
                conn.execute("PRAGMA foreign_keys = OFF;")
                try:
                    conn.executescript(
                        "BEGIN;\n" + MIGRATE_V1_TO_V2 + "\nCOMMIT;"
                    )
                finally:
                    conn.execute("PRAGMA foreign_keys = ON;")
        except sqlite3.OperationalError:
            logger.exception("play_session v1→v2 migration failed")
            raise
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at, note) VALUES (?, ?, ?)",
            (2, _now_iso(), "play_session.chart_id NULL allowed; raw_song_text added"),
        )


def _is_v1_play_session(conn: sqlite3.Connection) -> bool:
    """play_session が v1 スキーマ（chart_id NOT NULL）かどうかを判定する。"""
    rows = conn.execute("PRAGMA table_info(play_session)").fetchall()
    for r in rows:
        # PRAGMA table_info の列順: cid, name, type, notnull, dflt_value, pk
        if r["name"] == "chart_id":
            return bool(r["notnull"])
    return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
