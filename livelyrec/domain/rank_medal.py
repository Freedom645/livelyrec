"""クリアランク・クリアメダル算出。

詳細: docs/design/10_詳細設計_画像認識.md §7、docs/design/02_要件定義書.md FR-REC-042

クリアランクの閾値は asagaolabo Wiki page 4795 の仕様に基づく（2026-05-22 確定）。
クリアメダルの難易度マッピングは要確認。
"""

from __future__ import annotations

from .score import ClearType, Difficulty, Judgements, Medal, Rank

# クリア時のスコア → ランク（下限スコア, ランク）の降順。
_RANK_TABLE_CLEARED: tuple[tuple[int, Rank], ...] = (
    (98000, Rank.S),
    (95000, Rank.AAA),
    (90000, Rank.AA),
    (82000, Rank.A),
    (72000, Rank.B),
    (62000, Rank.C),
    (50000, Rank.D),
    (0, Rank.E),
)
# クリア失敗時: S/AAA/AA は付かず、82000 以上はすべて A（B 以下はクリア時と同じ）。
_RANK_TABLE_FAILED: tuple[tuple[int, Rank], ...] = (
    (82000, Rank.A),
    (72000, Rank.B),
    (62000, Rank.C),
    (50000, Rank.D),
    (0, Rank.E),
)


def clear_rank(score: int, cleared: bool = True) -> Rank:
    """スコアとクリア成否からクリアランクを算出する。

    - クリア時:   S 98000+ / AAA 95000+ / AA 90000+ / A 82000+ /
                  B 72000+ / C 62000+ / D 50000+ / E。
    - クリア失敗時: S/AAA/AA は付かず、82000 以上はすべて A。B 以下は同一。
    """
    if not 0 <= score <= 100000:
        raise ValueError(f"score must be in [0, 100000], got {score}")
    table = _RANK_TABLE_CLEARED if cleared else _RANK_TABLE_FAILED
    for threshold, rank in table:
        if score >= threshold:
            return rank
    return Rank.E


def clear_medal(
    clear_type: ClearType,
    judgements: Judgements,
    difficulty: Difficulty,
) -> Medal:
    """クリア種類・判定数・難易度からクリアメダルを算出する。"""
    if clear_type == ClearType.FAILED:
        return Medal.NONE
    if clear_type == ClearType.PERFECT:
        return _star_medal(difficulty)
    if clear_type == ClearType.FULL_COMBO:
        return _diamond_medal(difficulty)
    # CLEAR
    return Medal.CIRCLE


def _star_medal(difficulty: Difficulty) -> Medal:
    if difficulty in (Difficulty.EX, Difficulty.UPPER):
        return Medal.STAR_GOLD
    if difficulty == Difficulty.HYPER:
        return Medal.STAR_SILVER
    return Medal.STAR_BRONZE


def _diamond_medal(difficulty: Difficulty) -> Medal:
    if difficulty in (Difficulty.EX, Difficulty.UPPER):
        return Medal.DIAMOND_GOLD
    if difficulty == Difficulty.HYPER:
        return Medal.DIAMOND_SILVER
    return Medal.DIAMOND_BRONZE
