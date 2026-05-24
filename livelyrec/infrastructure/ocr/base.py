"""OCR エンジン抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OcrItem:
    """OCR が抽出した1テキストアイテム。"""
    text: str
    confidence: float
    bbox: tuple[tuple[float, float], ...]


class OcrEngine(ABC):
    """OCR エンジンの抽象インターフェイス。"""

    @abstractmethod
    def warm_up(self) -> None:
        """初回推論の遅延を吸収するためのウォームアップ。"""

    @abstractmethod
    def recognize(self, image_bgr: np.ndarray) -> list[OcrItem]:
        """BGR の numpy 配列を入力に OCR を実行し、テキスト群を返す。"""

    def recognize_text(self, image_bgr: np.ndarray) -> str:
        """全テキストを連結して返すヘルパ。"""
        items = self.recognize(image_bgr)
        return "".join(item.text for item in items)
