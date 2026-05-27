"""スコア・譜面・セッション関連のドメインオブジェクト。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §3.2、docs/design/07_詳細設計_DB設計.md §2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class Difficulty(str, Enum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    HYPER = "HYPER"
    EX = "EX"
    UPPER = "UPPER"


class ClearType(str, Enum):
    PERFECT = "PERFECT"
    FULL_COMBO = "FULL_COMBO"
    CLEAR = "CLEAR"
    FAILED = "FAILED"


class Medal(str, Enum):
    STAR_GOLD = "STAR_GOLD"
    STAR_SILVER = "STAR_SILVER"
    STAR_BRONZE = "STAR_BRONZE"
    DIAMOND_GOLD = "DIAMOND_GOLD"
    DIAMOND_SILVER = "DIAMOND_SILVER"
    DIAMOND_BRONZE = "DIAMOND_BRONZE"
    CIRCLE = "CIRCLE"
    NONE = "NONE"


class Rank(str, Enum):
    # pop'n music lively のクリアランクは 8 種（asagaolabo Wiki page 4795）
    S = "S"
    AAA = "AAA"
    AA = "AA"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class SessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    RETRIED_OUT = "RETRIED_OUT"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True)
class Chart:
    """譜面（楽曲×難易度）。"""

    song_id: str
    title: str
    difficulty: Difficulty
    is_upper: bool = False
    genre: str | None = None
    level: int | None = None

    @property
    def chart_id(self) -> str:
        return f"{self.song_id}:{self.difficulty.value}:{int(self.is_upper)}"


@dataclass(frozen=True)
class Judgements:
    """判定数（COOL/GREAT/GOOD/BAD）。"""

    cool: int = 0
    great: int = 0
    good: int = 0
    bad: int = 0

    @property
    def total(self) -> int:
        return self.cool + self.great + self.good + self.bad

    def __add__(self, other: Judgements) -> Judgements:
        return Judgements(
            cool=self.cool + other.cool,
            great=self.great + other.great,
            good=self.good + other.good,
            bad=self.bad + other.bad,
        )

    def diff(self, other: Judgements) -> Judgements:
        """self - other を返す（負にはならず、負成分は 0 にクリップ）。"""
        return Judgements(
            cool=max(0, self.cool - other.cool),
            great=max(0, self.great - other.great),
            good=max(0, self.good - other.good),
            bad=max(0, self.bad - other.bad),
        )


@dataclass(frozen=True)
class Result:
    """リザルト画面で確定する1プレイの記録結果。"""

    score: int
    judgements: Judgements
    combo: int
    clear_type: ClearType
    medal: Medal
    rank: Rank
    best_score_diff: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100000:
            raise ValueError(f"score must be in [0, 100000], got {self.score}")
        if self.combo < 0:
            raise ValueError(f"combo must be >= 0, got {self.combo}")


@dataclass
class PlaySession:
    """プレイセッション。リトライ含む1譜面のプレイ単位。

    `chart=None` は楽曲名 OCR が特定不能だった「検出失敗セッション」を表す（FR-REC-039）。
    """

    session_id: str
    chart: Chart | None
    started_at: datetime
    business_date: date
    attempt_count: int = 1
    final_status: SessionStatus = SessionStatus.IN_PROGRESS
    result: Result | None = None
    obs_scene: str | None = None
    obs_source: str | None = None
    resolution: str | None = None
    ended_at: datetime | None = None
    retries: list[datetime] = field(default_factory=list)
