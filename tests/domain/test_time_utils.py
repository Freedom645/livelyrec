"""業務日計算ユーティリティのテスト。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from livelyrec.shared.time_utils import business_date_of, next_rollover_at


@pytest.mark.parametrize(
    "now, rollover, expected",
    [
        # 切替前は前日扱い
        (datetime(2026, 5, 18, 0, 0), 6, date(2026, 5, 17)),
        (datetime(2026, 5, 18, 5, 59, 59), 6, date(2026, 5, 17)),
        # 切替後は当日扱い
        (datetime(2026, 5, 18, 6, 0), 6, date(2026, 5, 18)),
        (datetime(2026, 5, 18, 23, 59), 6, date(2026, 5, 18)),
        # rollover=0 は通常日と一致
        (datetime(2026, 5, 18, 0, 0), 0, date(2026, 5, 18)),
        # rollover=23 は前日が長い
        (datetime(2026, 5, 18, 22, 59), 23, date(2026, 5, 17)),
        (datetime(2026, 5, 18, 23, 0), 23, date(2026, 5, 18)),
    ],
)
def test_business_date_of(now: datetime, rollover: int, expected: date) -> None:
    assert business_date_of(now, rollover) == expected


def test_next_rollover_at_today() -> None:
    now = datetime(2026, 5, 18, 5, 0)
    rolled = next_rollover_at(now, 6)
    assert rolled == datetime(2026, 5, 18, 6, 0)


def test_next_rollover_at_tomorrow() -> None:
    now = datetime(2026, 5, 18, 6, 0)
    rolled = next_rollover_at(now, 6)
    assert rolled == datetime(2026, 5, 19, 6, 0)


def test_next_rollover_at_exact_boundary() -> None:
    # 境界時刻ちょうどなら翌日
    now = datetime(2026, 5, 18, 6, 0, 0)
    rolled = next_rollover_at(now, 6)
    assert rolled == datetime(2026, 5, 19, 6, 0, 0)
