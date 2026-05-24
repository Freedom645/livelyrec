"""画像の解像度・アスペクト比正規化。

詳細: docs/design/10_詳細設計_画像認識.md §2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from livelyrec.shared.constants import SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH

logger = logging.getLogger("livelyrec.recognizer.normalize")


@dataclass(frozen=True)
class NormalizedFrame:
    image_bgr: np.ndarray
    original_size: tuple[int, int]
    aspect_ratio: float


def normalize_frame(image_bgr: np.ndarray) -> NormalizedFrame:
    """入力 BGR 画像を 1366x768 にリサイズし、メタ情報を返す。"""
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("empty image")
    h, w = image_bgr.shape[:2]
    aspect = w / max(h, 1)
    if abs(aspect - SCREEN_BASE_WIDTH / SCREEN_BASE_HEIGHT) > 0.05:
        logger.warning(
            "aspect ratio %.3f deviates from 16:9 (1.778)", aspect
        )
    if (w, h) != (SCREEN_BASE_WIDTH, SCREEN_BASE_HEIGHT):
        resized = cv2.resize(
            image_bgr, (SCREEN_BASE_WIDTH, SCREEN_BASE_HEIGHT), interpolation=cv2.INTER_LINEAR
        )
    else:
        resized = image_bgr
    return NormalizedFrame(
        image_bgr=resized,
        original_size=(w, h),
        aspect_ratio=aspect,
    )


def crop(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """1366x768 基準の Box で切り出す。"""
    x1, y1, x2, y2 = box
    return frame[y1:y2, x1:x2]
