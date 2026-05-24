"""業務日打鍵カウンタ。

詳細: docs/design/05_基本設計書.md §9.6、docs/design/02_要件定義書.md FR-REC-034〜036
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .score import Judgements


@dataclass
class DailyCounter:
    """1業務日分の判定別打鍵数を保持する。

    画面から取得した「累計判定数」の前回値との差分を都度 push する想定。
    """

    business_date: date
    cumulative: Judgements = field(default_factory=Judgements)

    def add_delta(self, delta: Judgements) -> Judgements:
        """累計に delta を加算する。負の delta は無視（クリップ）。"""
        if delta.total < 0:
            return self.cumulative
        self.cumulative = self.cumulative + delta
        return self.cumulative

    def rollover(self, new_date: date) -> Judgements:
        """業務日を切替え、累計をリセットして直前の累計を返す。"""
        prev = self.cumulative
        self.business_date = new_date
        self.cumulative = Judgements()
        return prev
