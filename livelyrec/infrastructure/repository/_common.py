"""リポジトリ共通ユーティリティ。"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """UTC 現在時刻の ISO 8601 文字列。"""
    return datetime.now(UTC).isoformat()


def dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)
