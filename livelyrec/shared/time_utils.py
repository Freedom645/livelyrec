"""業務日計算ほか時刻関連ユーティリティ。

詳細: docs/design/05_基本設計書.md §9.6、docs/design/02_要件定義書.md FR-REC-035
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


def business_date_of(now: datetime, rollover_hour: int) -> date:
    """指定時刻が属する業務日を返す。

    業務日切替は毎日 rollover_hour 時。例えば rollover_hour=6 ならば
    AM6:00 までは前日の業務日として扱う。

    >>> from datetime import datetime
    >>> business_date_of(datetime(2026, 5, 18, 5, 59), 6)
    datetime.date(2026, 5, 17)
    >>> business_date_of(datetime(2026, 5, 18, 6, 0), 6)
    datetime.date(2026, 5, 18)
    """
    if now.hour < rollover_hour:
        return (now - timedelta(days=1)).date()
    return now.date()


def next_rollover_at(now: datetime, rollover_hour: int) -> datetime:
    """次の業務日切替時刻（now より厳密に後）を返す。"""
    candidate = datetime.combine(now.date(), time(hour=rollover_hour, tzinfo=now.tzinfo))
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
