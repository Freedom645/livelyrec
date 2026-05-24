"""プレイ画面のリトライ検出。

詳細: docs/design/10_詳細設計_画像認識.md §5.1.3
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayFrameSnapshot:
    score: int | None
    cool: int | None
    great: int | None
    good: int | None
    bad: int | None
    combo: int | None


class RetryDetector:
    """連続フレームでスコア/判定/コンボが「全て0にリセット」されたらリトライ。"""

    def __init__(self, window: int = 5) -> None:
        self._buf: deque[PlayFrameSnapshot] = deque(maxlen=window)

    def push(self, snap: PlayFrameSnapshot) -> bool:
        """フレームを取り込み、当該フレームでリトライが発生したかを返す。"""
        is_retry = False
        if self._buf:
            prev = self._buf[-1]
            if self._is_retry(prev, snap):
                is_retry = True
                self._buf.clear()
        self._buf.append(snap)
        return is_retry

    def reset(self) -> None:
        self._buf.clear()

    @staticmethod
    def _is_retry(prev: PlayFrameSnapshot, cur: PlayFrameSnapshot) -> bool:
        # prev に有意な値があり、cur で全てが 0 に
        prev_has_value = any(
            (v is not None and v > 0)
            for v in (prev.score, prev.combo, prev.cool, prev.great, prev.good, prev.bad)
        )
        if not prev_has_value:
            return False
        cur_all_zero = (
            (cur.combo == 0)
            and ((cur.cool or 0) == 0)
            and ((cur.great or 0) == 0)
            and ((cur.good or 0) == 0)
            and ((cur.bad or 0) == 0)
        )
        return cur_all_zero
