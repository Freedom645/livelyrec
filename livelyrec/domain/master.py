"""楽曲マスタのドメインオブジェクト。

詳細: docs/design/05_基本設計書.md §6、docs/design/10_詳細設計_画像認識.md §6
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

try:
    import jaconv  # type: ignore[import-not-found]
    _HAS_JACONV = True
except ImportError:
    _HAS_JACONV = False

from .score import Chart, Difficulty


@dataclass(frozen=True)
class Song:
    """マスタ上の楽曲。"""

    song_id: str
    title: str
    title_norm: str
    genre: str | None = None
    has_upper: bool = False
    charts: tuple[Chart, ...] = field(default_factory=tuple)


def normalize_song_title(s: str) -> str:
    """楽曲名をマッチング用に正規化する。

    - NFKC で全角→半角等を統一
    - 空白除去
    - 一部記号除去
    - カタカナ→ひらがな（jaconv 利用可能なとき）
      OCR が「ぽ→ほ」誤読する案件で、カタカナ・ひらがな混在を解消するため
    - 小文字化
    """
    if not s:
        return ""
    norm = unicodedata.normalize("NFKC", s)
    norm = re.sub(r"[\s　]+", "", norm)
    norm = re.sub(r"[!?！？…・♥♡★☆※]", "", norm)
    if _HAS_JACONV:
        norm = jaconv.kata2hira(norm)
    return norm.lower()


def parse_difficulty(label: str) -> Difficulty | None:
    """OCR で読み取った難易度ラベル文字列から Difficulty を推定する。"""
    if not label:
        return None
    s = label.strip().upper().replace(" ", "")
    if "UPPER" in s or "UPP" in s:
        return Difficulty.UPPER
    if s.startswith("EX") or "EXTRA" in s:
        return Difficulty.EX
    if s.startswith("HYP") or s.startswith("H"):
        return Difficulty.HYPER
    if s.startswith("NOR") or s.startswith("N"):
        return Difficulty.NORMAL
    if s.startswith("EAS") or s.startswith("5BUT") or s == "E":
        return Difficulty.EASY
    return None
