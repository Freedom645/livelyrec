"""プレイセッションリポジトリ。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime

from livelyrec.domain.score import Chart, Difficulty, PlaySession, SessionStatus

from ._common import dt_to_iso, iso_to_dt


class PlaySessionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def create(
        self,
        chart: Chart,
        started_at: datetime,
        business_date: date,
        obs_scene: str | None = None,
        obs_source: str | None = None,
        resolution: str | None = None,
    ) -> PlaySession:
        session = PlaySession(
            session_id=self.new_id(),
            chart=chart,
            started_at=started_at,
            business_date=business_date,
            attempt_count=1,
            final_status=SessionStatus.IN_PROGRESS,
            obs_scene=obs_scene,
            obs_source=obs_source,
            resolution=resolution,
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO play_session
                (session_id, chart_id, started_at, business_date, attempt_count,
                 final_status, obs_scene, obs_source, resolution)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    chart.chart_id,
                    dt_to_iso(started_at),
                    business_date.isoformat(),
                    session.attempt_count,
                    session.final_status.value,
                    obs_scene,
                    obs_source,
                    resolution,
                ),
            )
        return session

    def increment_attempt(self, session_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE play_session SET attempt_count = attempt_count + 1 WHERE session_id = ?",
                (session_id,),
            )

    def append_retry(self, session_id: str, occurred_at: datetime) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO retry (retry_id, session_id, occurred_at) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, session_id, dt_to_iso(occurred_at)),
            )

    def set_status(
        self,
        session_id: str,
        status: SessionStatus,
        ended_at: datetime | None = None,
    ) -> None:
        with self._conn:
            if ended_at is not None:
                self._conn.execute(
                    "UPDATE play_session SET final_status = ?, ended_at = ? WHERE session_id = ?",
                    (status.value, dt_to_iso(ended_at), session_id),
                )
            else:
                self._conn.execute(
                    "UPDATE play_session SET final_status = ? WHERE session_id = ?",
                    (status.value, session_id),
                )

    def get(self, session_id: str) -> PlaySession | None:
        row = self._conn.execute(
            """
            SELECT ps.session_id, ps.chart_id, ps.started_at, ps.ended_at, ps.business_date,
                   ps.attempt_count, ps.final_status, ps.obs_scene, ps.obs_source, ps.resolution,
                   c.song_id, c.difficulty, c.is_upper, c.level,
                   s.title, s.genre
            FROM play_session ps
            JOIN chart c ON ps.chart_id = c.chart_id
            JOIN song s ON c.song_id = s.song_id
            WHERE ps.session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            return None
        chart = Chart(
            song_id=row["song_id"],
            title=row["title"],
            difficulty=Difficulty(row["difficulty"]),
            is_upper=bool(row["is_upper"]),
            genre=row["genre"],
            level=row["level"],
        )
        retries_rows = self._conn.execute(
            "SELECT occurred_at FROM retry WHERE session_id = ? ORDER BY occurred_at",
            (session_id,),
        ).fetchall()
        return PlaySession(
            session_id=row["session_id"],
            chart=chart,
            started_at=iso_to_dt(row["started_at"]),
            ended_at=iso_to_dt(row["ended_at"]) if row["ended_at"] else None,
            business_date=date.fromisoformat(row["business_date"]),
            attempt_count=row["attempt_count"],
            final_status=SessionStatus(row["final_status"]),
            obs_scene=row["obs_scene"],
            obs_source=row["obs_source"],
            resolution=row["resolution"],
            retries=[iso_to_dt(r["occurred_at"]) for r in retries_rows],
        )
