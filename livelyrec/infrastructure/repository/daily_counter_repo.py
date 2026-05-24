"""業務日打鍵カウンタのリポジトリ。"""

from __future__ import annotations

import sqlite3
from datetime import date

from livelyrec.domain.score import Judgements

from ._common import now_iso

_JUDGEMENTS = ("COOL", "GREAT", "GOOD", "BAD", "TOTAL")


class DailyCounterRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ensure_business_day(self, business_date: date) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO business_day (business_date, rolled_at) VALUES (?, ?)",
                (business_date.isoformat(), now_iso()),
            )
            for j in _JUDGEMENTS:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO daily_keycount (business_date, judgement, count, updated_at)
                    VALUES (?, ?, 0, ?)
                    """,
                    (business_date.isoformat(), j, now_iso()),
                )

    def add(self, business_date: date, delta: Judgements) -> Judgements:
        """delta を加算し、加算後の累計を返す。"""
        self.ensure_business_day(business_date)
        ts = now_iso()
        bd = business_date.isoformat()
        with self._conn:
            for name, value in (
                ("COOL", delta.cool),
                ("GREAT", delta.great),
                ("GOOD", delta.good),
                ("BAD", delta.bad),
                ("TOTAL", delta.total),
            ):
                if value <= 0:
                    continue
                self._conn.execute(
                    """
                    UPDATE daily_keycount
                    SET count = count + ?, updated_at = ?
                    WHERE business_date = ? AND judgement = ?
                    """,
                    (value, ts, bd, name),
                )
        return self.get(business_date)

    def get(self, business_date: date) -> Judgements:
        rows = self._conn.execute(
            "SELECT judgement, count FROM daily_keycount WHERE business_date = ?",
            (business_date.isoformat(),),
        ).fetchall()
        d: dict[str, int] = {r["judgement"]: r["count"] for r in rows}
        return Judgements(
            cool=d.get("COOL", 0),
            great=d.get("GREAT", 0),
            good=d.get("GOOD", 0),
            bad=d.get("BAD", 0),
        )

    def reset(self, business_date: date) -> None:
        self.ensure_business_day(business_date)
        with self._conn:
            self._conn.execute(
                "UPDATE daily_keycount SET count = 0, updated_at = ? WHERE business_date = ?",
                (now_iso(), business_date.isoformat()),
            )
