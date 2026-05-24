"""画像認識パイプライン本体。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from livelyrec.domain.state import ScreenType

from .extractors import (
    PlayMetrics,
    ResultMetrics,
    extract_play_metrics,
    extract_result_metrics,
)
from .normalize import NormalizedFrame, normalize_frame
from .screen_detector import ScreenDetection, ScreenDetector

logger = logging.getLogger("livelyrec.recognizer.pipeline")


@dataclass(frozen=True)
class FrameAnalysis:
    frame: NormalizedFrame
    detection: ScreenDetection
    play_metrics: PlayMetrics | None = None
    result_metrics: ResultMetrics | None = None


class RecognitionPipeline:
    """フレーム1枚に対する解析を行う。"""

    def __init__(self, ocr, digit_recognizer, screen_signatures_path=None) -> None:
        self._ocr = ocr
        self._digit = digit_recognizer
        self._screen = ScreenDetector(ocr, signatures_path=screen_signatures_path)

    def analyze(self, image_bgr: np.ndarray) -> FrameAnalysis:
        norm = normalize_frame(image_bgr)
        detection = self._screen.detect(norm.image_bgr)

        play = None
        result = None
        try:
            if detection.screen == ScreenType.PLAY:
                play = extract_play_metrics(norm.image_bgr, self._ocr, self._digit)
            elif detection.screen == ScreenType.RESULT:
                result = extract_result_metrics(
                    norm.image_bgr, self._ocr, self._digit
                )
        except Exception as e:
            logger.warning("metric extraction failed: %s", e)

        return FrameAnalysis(
            frame=norm,
            detection=detection,
            play_metrics=play,
            result_metrics=result,
        )
