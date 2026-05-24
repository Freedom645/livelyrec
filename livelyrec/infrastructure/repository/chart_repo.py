"""譜面リポジトリ。"""

from __future__ import annotations

import sqlite3

from livelyrec.domain.score import Chart, Difficulty


class ChartRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, chart_id: str) -> Chart | None:
        row = self._conn.execute(
            """
            SELECT c.chart_id, c.song_id, c.difficulty, c.is_upper, c.level,
                   s.title, s.genre
            FROM chart c
            JOIN song s ON c.song_id = s.song_id
            WHERE c.chart_id = ?
            """,
            (chart_id,),
        ).fetchone()
        if not row:
            return None
        return Chart(
            song_id=row["song_id"],
            title=row["title"],
            difficulty=Difficulty(row["difficulty"]),
            is_upper=bool(row["is_upper"]),
            genre=row["genre"],
            level=row["level"],
        )

    def list_by_song(self, song_id: str) -> list[Chart]:
        rows = self._conn.execute(
            """
            SELECT c.chart_id, c.song_id, c.difficulty, c.is_upper, c.level,
                   s.title, s.genre
            FROM chart c
            JOIN song s ON c.song_id = s.song_id
            WHERE c.song_id = ?
            ORDER BY c.is_upper, c.difficulty
            """,
            (song_id,),
        ).fetchall()
        return [
            Chart(
                song_id=r["song_id"],
                title=r["title"],
                difficulty=Difficulty(r["difficulty"]),
                is_upper=bool(r["is_upper"]),
                genre=r["genre"],
                level=r["level"],
            )
            for r in rows
        ]
