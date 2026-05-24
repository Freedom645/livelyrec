"""KVストア（app_kv）。"""

from __future__ import annotations

import sqlite3

from ._common import now_iso


class AppKvRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM app_kv WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        ts = now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO app_kv (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, ts),
            )

    def delete(self, key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM app_kv WHERE key = ?", (key,))
