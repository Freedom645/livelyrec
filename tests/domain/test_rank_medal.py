"""クリアランク・クリアメダル算出のテスト。"""

from __future__ import annotations

import pytest

from livelyrec.domain.rank_medal import clear_medal, clear_rank
from livelyrec.domain.score import ClearType, Difficulty, Judgements, Medal, Rank


@pytest.mark.parametrize(
    "score, expected",
    [
        (100000, Rank.S),
        (98000, Rank.S),
        (97999, Rank.AAA),
        (95000, Rank.AAA),
        (94999, Rank.AA),
        (90000, Rank.AA),
        (89999, Rank.A),
        (82000, Rank.A),
        (81999, Rank.B),
        (72000, Rank.B),
        (71999, Rank.C),
        (62000, Rank.C),
        (61999, Rank.D),
        (50000, Rank.D),
        (49999, Rank.E),
        (0, Rank.E),
    ],
)
def test_clear_rank_cleared_boundaries(score: int, expected: Rank) -> None:
    assert clear_rank(score, cleared=True) == expected


@pytest.mark.parametrize(
    "score, expected",
    [
        # クリア失敗時は S/AAA/AA は付かず 82000 以上はすべて A
        (100000, Rank.A),
        (95000, Rank.A),
        (90000, Rank.A),
        (82000, Rank.A),
        (81999, Rank.B),
        (72000, Rank.B),
        (62000, Rank.C),
        (50000, Rank.D),
        (49999, Rank.E),
        (0, Rank.E),
    ],
)
def test_clear_rank_failed_boundaries(score: int, expected: Rank) -> None:
    assert clear_rank(score, cleared=False) == expected


@pytest.mark.parametrize("invalid_score", [-1, 100001, 200000])
def test_clear_rank_rejects_out_of_range(invalid_score: int) -> None:
    with pytest.raises(ValueError):
        clear_rank(invalid_score)


def test_failed_yields_none_medal() -> None:
    medal = clear_medal(ClearType.FAILED, Judgements(0, 0, 0, 0), Difficulty.EX)
    assert medal == Medal.NONE


@pytest.mark.parametrize(
    "difficulty, expected",
    [
        (Difficulty.EX, Medal.STAR_GOLD),
        (Difficulty.UPPER, Medal.STAR_GOLD),
        (Difficulty.HYPER, Medal.STAR_SILVER),
        (Difficulty.NORMAL, Medal.STAR_BRONZE),
        (Difficulty.EASY, Medal.STAR_BRONZE),
    ],
)
def test_perfect_medal_by_difficulty(difficulty: Difficulty, expected: Medal) -> None:
    medal = clear_medal(ClearType.PERFECT, Judgements(100, 0, 0, 0), difficulty)
    assert medal == expected


@pytest.mark.parametrize(
    "difficulty, expected",
    [
        (Difficulty.EX, Medal.DIAMOND_GOLD),
        (Difficulty.UPPER, Medal.DIAMOND_GOLD),
        (Difficulty.HYPER, Medal.DIAMOND_SILVER),
        (Difficulty.NORMAL, Medal.DIAMOND_BRONZE),
        (Difficulty.EASY, Medal.DIAMOND_BRONZE),
    ],
)
def test_full_combo_medal_by_difficulty(difficulty: Difficulty, expected: Medal) -> None:
    medal = clear_medal(ClearType.FULL_COMBO, Judgements(80, 20, 0, 0), difficulty)
    assert medal == expected


def test_clear_yields_circle_regardless_of_difficulty() -> None:
    for d in Difficulty:
        medal = clear_medal(ClearType.CLEAR, Judgements(60, 20, 10, 10), d)
        assert medal == Medal.CIRCLE
