"""楽曲マスタのリポジトリ。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from rapidfuzz import fuzz, process

from livelyrec.domain.master import Song, normalize_song_title
from livelyrec.domain.score import Chart, Difficulty

from ._common import now_iso


class SongRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, song: Song) -> None:
        ts = now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO song (song_id, title, title_norm, genre, has_upper, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(song_id) DO UPDATE SET
                    title=excluded.title,
                    title_norm=excluded.title_norm,
                    genre=excluded.genre,
                    has_upper=excluded.has_upper,
                    fetched_at=excluded.fetched_at
                """,
                (song.song_id, song.title, song.title_norm, song.genre,
                 int(song.has_upper), ts),
            )
            for chart in song.charts:
                self._conn.execute(
                    """
                    INSERT INTO chart (chart_id, song_id, difficulty, is_upper, level)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(chart_id) DO UPDATE SET
                        level=excluded.level
                    """,
                    (chart.chart_id, chart.song_id, chart.difficulty.value,
                     int(chart.is_upper), chart.level),
                )

    def upsert_many(self, songs: Iterable[Song]) -> int:
        n = 0
        for s in songs:
            self.upsert(s)
            n += 1
        return n

    def get(self, song_id: str) -> Song | None:
        row = self._conn.execute(
            "SELECT song_id, title, title_norm, genre, has_upper FROM song WHERE song_id = ?",
            (song_id,),
        ).fetchone()
        if not row:
            return None
        chart_rows = self._conn.execute(
            "SELECT chart_id, song_id, difficulty, is_upper, level FROM chart WHERE song_id = ?",
            (song_id,),
        ).fetchall()
        charts = tuple(
            Chart(
                song_id=cr["song_id"],
                title=row["title"],
                difficulty=Difficulty(cr["difficulty"]),
                is_upper=bool(cr["is_upper"]),
                genre=row["genre"],
                level=cr["level"],
            )
            for cr in chart_rows
        )
        return Song(
            song_id=row["song_id"],
            title=row["title"],
            title_norm=row["title_norm"],
            genre=row["genre"],
            has_upper=bool(row["has_upper"]),
            charts=charts,
        )

    def list_titles(self) -> list[tuple[str, str]]:
        """(song_id, title_norm) のリストを返す（マッチング用）。"""
        rows = self._conn.execute("SELECT song_id, title_norm FROM song").fetchall()
        return [(r["song_id"], r["title_norm"]) for r in rows]

    def count(self) -> int:
        """登録楽曲数を返す。"""
        row = self._conn.execute("SELECT COUNT(*) FROM song").fetchone()
        return int(row[0]) if row else 0

    def fuzzy_search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[tuple[Song, float]]:
        """正規化済みクエリに対し title_norm 最も近い楽曲を返す。"""
        norm = normalize_song_title(query)
        if not norm:
            return []
        candidates = self.list_titles()
        if not candidates:
            return []
        choices = dict(candidates)
        matches = process.extract(norm, choices, scorer=fuzz.WRatio, limit=limit)
        results: list[tuple[Song, float]] = []
        for _matched_text, score, song_id in matches:
            song = self.get(song_id)
            if song is not None:
                results.append((song, float(score)))
        return results
