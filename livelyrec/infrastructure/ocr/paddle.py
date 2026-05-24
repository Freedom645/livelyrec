"""PaddleOCR ラッパ。

詳細: docs/design/poc/01_ocr_engine_selection.md、docs/design/poc/02_roi_ocr_evaluation.md
"""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

from livelyrec.shared.exceptions import OcrEngineError

from .base import OcrEngine, OcrItem

logger = logging.getLogger("livelyrec.ocr")


class PaddleOcrEngine(OcrEngine):
    """PaddleOCR 2.7.x の薄いラッパ。スレッド安全のためロックで保護する。"""

    def __init__(self, lang: str = "japan") -> None:
        self._lang = lang
        self._ocr = None
        self._lock = threading.Lock()

    def _ensure_initialized(self) -> None:
        if self._ocr is not None:
            return
        try:
            from paddleocr import PaddleOCR  # 遅延 import
            self._ocr = PaddleOCR(lang=self._lang, use_angle_cls=False, show_log=False)
        except Exception as e:
            raise OcrEngineError(f"failed to initialize PaddleOCR: {e}") from e

    def warm_up(self) -> None:
        self._ensure_initialized()
        # ダミー画像で初回推論を済ませる（PoC #02 申し送り F-4）
        dummy = np.full((40, 80, 3), 255, dtype=np.uint8)
        cv2.putText(dummy, "1", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        try:
            with self._lock:
                self._ocr.ocr(dummy, cls=False)
        except Exception as e:
            logger.warning("warm_up ignored exception: %s", e)

    def recognize(self, image_bgr: np.ndarray) -> list[OcrItem]:
        self._ensure_initialized()
        if image_bgr is None or image_bgr.size == 0:
            return []
        try:
            with self._lock:
                raw = self._ocr.ocr(image_bgr, cls=False)
        except Exception as e:
            raise OcrEngineError(str(e)) from e
        if not raw or not raw[0]:
            return []
        items: list[OcrItem] = []
        for line in raw[0]:
            try:
                box = line[0]
                text, score = line[1]
                bbox = tuple((float(p[0]), float(p[1])) for p in box)
                items.append(OcrItem(text=text, confidence=float(score), bbox=bbox))
            except Exception:
                continue
        return items
