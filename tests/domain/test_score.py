"""スコア・譜面・リザルトのテスト。"""

from __future__ import annotations

import pytest

from livelyrec.domain.score import (
    Chart,
    ClearType,
    Difficulty,
    Judgements,
    Medal,
    Rank,
    Result,
)


def test_chart_id_format() -> None:
    chart = Chart(song_id="popn-1", title="t", difficulty=Difficulty.HYPER)
    assert chart.chart_id == "popn-1:HYPER:0"


def test_upper_chart_id() -> None:
    chart = Chart(song_id="popn-1", title="t", difficulty=Difficulty.UPPER, is_upper=True)
    assert chart.chart_id == "popn-1:UPPER:1"


def test_judgements_add_and_total() -> None:
    a = Judgements(1, 2, 3, 4)
    b = Judgements(10, 20, 30, 40)
    c = a + b
    assert c == Judgements(11, 22, 33, 44)
    assert c.total == 110


def test_result_validates_score_range() -> None:
    with pytest.raises(ValueError):
        Result(
            score=100001,
            judgements=Judgements(),
            combo=0,
            clear_type=ClearType.CLEAR,
            medal=Medal.CIRCLE,
            rank=Rank.E,
        )


def test_result_validates_combo_non_negative() -> None:
    with pytest.raises(ValueError):
        Result(
            score=10000,
            judgements=Judgements(),
            combo=-1,
            clear_type=ClearType.CLEAR,
            medal=Medal.CIRCLE,
            rank=Rank.E,
        )


def test_result_accepts_valid() -> None:
    r = Result(
        score=87268,
        judgements=Judgements(312, 18, 5, 2),
        combo=329,
        clear_type=ClearType.CLEAR,
        medal=Medal.CIRCLE,
        rank=Rank.AAA,
        best_score_diff=1234,
    )
    assert r.score == 87268
    assert r.judgements.total == 337
