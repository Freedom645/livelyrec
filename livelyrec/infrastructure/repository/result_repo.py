"""リザルトリポジトリ。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from livelyrec.domain.score import (
    ClearType,
    Judgements,
    Medal,
    Rank,
    Result,
)

from ._common import dt_to_iso, iso_to_dt, now_iso


class ResultRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        session_id: str,
        result: Result,
        recorded_at: datetime | None = None,
    ) -> None:
        ts = dt_to_iso(recorded_at) if recorded_at is not None else now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO result
                (session_id, score, cool, great, good, bad, combo,
                 clear_type, medal, rank, best_score_diff, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    score=excluded.score, cool=excluded.cool, great=excluded.great,
                    good=excluded.good, bad=excluded.bad, combo=excluded.combo,
                    clear_type=excluded.clear_type, medal=excluded.medal, rank=excluded.rank,
                    best_score_diff=excluded.best_score_diff, recorded_at=excluded.recorded_at
                """,
                (
                    session_id,
                    result.score,
                    result.judgements.cool,
                    result.judgements.great,
                    result.judgements.good,
                    result.judgements.bad,
                    result.combo,
                    result.clear_type.value,
                    result.medal.value,
                    result.rank.value,
                    result.best_score_diff,
                    ts,
                ),
            )

    def get(self, session_id: str) -> Result | None:
        row = self._conn.execute(
            "SELECT * FROM result WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return _row_to_result(row)

    def best_score(self, chart_id: str) -> int | None:
        row = self._conn.execute(
            """
            SELECT MAX(r.score) AS s
            FROM result r
            JOIN play_session ps ON r.session_id = ps.session_id
            WHERE ps.chart_id = ?
            """,
            (chart_id,),
        ).fetchone()
        return int(row["s"]) if row and row["s"] is not None else None

    def list_by_chart(self, chart_id: str, limit: int = 20) -> list[tuple[str, datetime, Result]]:
        rows = self._conn.execute(
            """
            SELECT r.*, ps.session_id AS sid, ps.started_at AS started
            FROM result r
            JOIN play_session ps ON r.session_id = ps.session_id
            WHERE ps.chart_id = ?
            ORDER BY ps.started_at DESC
            LIMIT ?
            """,
            (chart_id, limit),
        ).fetchall()
        results: list[tuple[str, datetime, Result]] = []
        for row in rows:
            results.append((row["sid"], iso_to_dt(row["started"]), _row_to_result(row)))
        return results

    def list_recent(self, limit: int = 10) -> list[tuple[str, datetime, str, Result]]:
        """直近のリザルトN件を (session_id, started_at, chart_id, Result) で返す。"""
        rows = self._conn.execute(
            """
            SELECT r.*, ps.session_id AS sid, ps.started_at AS started, ps.chart_id AS cid
            FROM result r
            JOIN play_session ps ON r.session_id = ps.session_id
            ORDER BY ps.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            (row["sid"], iso_to_dt(row["started"]), row["cid"], _row_to_result(row))
            for row in rows
        ]


def _row_to_result(row: sqlite3.Row) -> Result:
    return Result(
        score=row["score"],
        judgements=Judgements(
            cool=row["cool"],
            great=row["great"],
            good=row["good"],
            bad=row["bad"],
        ),
        combo=row["combo"],
        clear_type=ClearType(row["clear_type"]),
        medal=Medal(row["medal"]),
        rank=Rank(row["rank"]),
        best_score_diff=row["best_score_diff"],
    )
