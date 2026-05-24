"""業務日打鍵カウンタのテスト。"""

from __future__ import annotations

from datetime import date

from livelyrec.domain.daily_counter import DailyCounter
from livelyrec.domain.score import Judgements


def test_initial_counter_is_zero() -> None:
    dc = DailyCounter(business_date=date(2026, 5, 18))
    assert dc.cumulative.total == 0


def test_add_delta_accumulates() -> None:
    dc = DailyCounter(business_date=date(2026, 5, 18))
    dc.add_delta(Judgements(cool=10, great=2, good=1, bad=0))
    dc.add_delta(Judgements(cool=5, great=3, good=0, bad=1))
    assert dc.cumulative == Judgements(cool=15, great=5, good=1, bad=1)
    assert dc.cumulative.total == 22


def test_rollover_resets_and_returns_previous() -> None:
    dc = DailyCounter(business_date=date(2026, 5, 18))
    dc.add_delta(Judgements(cool=100, great=20, good=5, bad=2))
    prev = dc.rollover(date(2026, 5, 19))
    assert prev == Judgements(cool=100, great=20, good=5, bad=2)
    assert dc.business_date == date(2026, 5, 19)
    assert dc.cumulative.total == 0


def test_add_delta_ignores_negative_total() -> None:
    # 負の delta（前回値より減少した異常ケース）は累計に反映しない
    dc = DailyCounter(business_date=date(2026, 5, 18))
    dc.add_delta(Judgements(cool=10, great=2, good=1, bad=0))
    returned = dc.add_delta(Judgements(cool=-5, great=0, good=0, bad=0))
    assert returned == Judgements(cool=10, great=2, good=1, bad=0)
    assert dc.cumulative == Judgements(cool=10, great=2, good=1, bad=0)


def test_judgements_diff_clips_negative() -> None:
    a = Judgements(cool=10, great=5, good=2, bad=1)
    b = Judgements(cool=15, great=4, good=2, bad=1)
    d = a.diff(b)
    assert d.cool == 0  # クリップされる
    assert d.great == 1
    assert d.good == 0
    assert d.bad == 0
