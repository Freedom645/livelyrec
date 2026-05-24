"""SQLite 接続とマイグレーション。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .schema import DDL_V1, LATEST_SCHEMA_VERSION


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
    # v1 まで
    conn.executescript(DDL_V1)
    if _current_version(conn) < 1:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at, note) VALUES (?, ?, ?)",
            (1, _now_iso(), "initial schema"),
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
