"""リザルトリポジトリ。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from livelyrec.domain.score import (
    ClearType,
    Judgements,
    Medal,
    Rank,
    Result,
)

from ._common import dt_to_iso, iso_to_dt, now_iso


@dataclass(frozen=True)
class RecentEntry:
    """直近のプレイ履歴1件（/browser/recent 用、FR-STR-009）。

    `chart_id is None` のときは楽曲名 OCR が特定できなかった検出失敗セッション
    （FR-REC-039）であり、`song_title` / `difficulty` も None になる。
    """

    session_id: str
    started_at: datetime
    chart_id: str | None
    song_title: str | None
    difficulty: str | None       # Difficulty.value
    level: int | None
    score: int | None
    clear_type: str | None       # ClearType.value
    rank: str | None             # Rank.value
    medal: str | None            # Medal.value


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

    def list_results_for_export(
        self, limit: int = 10000
    ) -> list[tuple[str, datetime, str, Result]]:
        """CSV エクスポート用に、Result のあるセッション（楽曲特定済み）を新しい順に返す。

        旧 `list_recent` の戻り値仕様を維持。検出失敗（chart_id NULL）や
        リザルト未取得（SKIPPED 等）のセッションは含めない。
        """
        rows = self._conn.execute(
            """
            SELECT r.*, ps.session_id AS sid, ps.started_at AS started, ps.chart_id AS cid
            FROM result r
            JOIN play_session ps ON r.session_id = ps.session_id
            WHERE ps.chart_id IS NOT NULL
            ORDER BY ps.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            (row["sid"], iso_to_dt(row["started"]), row["cid"], _row_to_result(row))
            for row in rows
        ]

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

    def list_recent(self, limit: int = 10) -> list[RecentEntry]:
        """直近の N 件を RecentEntry で返す（/browser/recent 用、FR-STR-009）。

        - リザルト未取得（SKIPPED 等）のセッションも含めるため `play_session` を
          基点に `result` を LEFT JOIN する。
        - `chart_id IS NULL` の検出失敗セッションも含める。楽曲タイトル等は NULL。
        - 件数は時刻降順、最大 `limit` 件。
        """
        rows = self._conn.execute(
            """
            SELECT ps.session_id AS sid,
                   ps.started_at AS started,
                   ps.chart_id   AS cid,
                   c.difficulty  AS difficulty,
                   c.level       AS level,
                   s.title       AS title,
                   r.score       AS score,
                   r.clear_type  AS clear_type,
                   r.rank        AS rank,
                   r.medal       AS medal
            FROM play_session ps
            LEFT JOIN chart c  ON ps.chart_id = c.chart_id
            LEFT JOIN song  s  ON c.song_id   = s.song_id
            LEFT JOIN result r ON ps.session_id = r.session_id
            ORDER BY ps.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            RecentEntry(
                session_id=row["sid"],
                started_at=iso_to_dt(row["started"]),
                chart_id=row["cid"],
                song_title=row["title"],
                difficulty=row["difficulty"],
                level=row["level"],
                score=row["score"],
                clear_type=row["clear_type"],
                rank=row["rank"],
                medal=row["medal"],
            )
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
