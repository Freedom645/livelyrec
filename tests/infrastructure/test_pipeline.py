"""RecognitionPipeline のテスト。

画面判別（実 ScreenDetector）の結果に応じて、プレイ/リザルトの
メトリクス抽出が呼び分けられること、抽出例外が握りつぶされることを検証する。
OCR・数字認識器はフェイクで差し替える。
"""

from __future__ import annotations

import cv2
import numpy as np

from livelyrec.domain.state import ScreenType
from livelyrec.infrastructure.ocr.base import OcrItem
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline
from livelyrec.infrastructure.recognizer.roi_defs import SCREEN_SIGNATURE_ROI


def _frame_with_signature(hue: int, s: int = 200, v: int = 200) -> np.ndarray:
    hsv = np.zeros((768, 1366, 3), dtype=np.uint8)
    x1, y1, x2, y2 = SCREEN_SIGNATURE_ROI
    hsv[y1:y2, x1:x2] = (hue, s, v)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


class FakeOcr:
    def __init__(self, items: list[OcrItem] | None = None, text: str = "") -> None:
        self._items = items or []
        self._text = text

    def recognize(self, image_bgr):  # noqa: ARG002
        return self._items

    def recognize_text(self, image_bgr):  # noqa: ARG002
        return self._text


class FakeDigit:
    def recognize(self, roi, judge):  # noqa: ARG002
        return "", 0.0

    def recognize_rightmost(self, roi, judge, count):  # noqa: ARG002
        return "", 0.0


class RaisingOcr:
    def recognize(self, image_bgr):  # noqa: ARG002
        raise RuntimeError("ocr failure")

    def recognize_text(self, image_bgr):  # noqa: ARG002
        raise RuntimeError("ocr failure")


def test_pipeline_play_screen_extracts_play_metrics() -> None:
    ocr = FakeOcr(items=[OcrItem("テスト曲", 0.9, ())], text="054210")
    pipeline = RecognitionPipeline(ocr, FakeDigit())
    analysis = pipeline.analyze(_frame_with_signature(59))  # PLAY
    assert analysis.detection.screen == ScreenType.PLAY
    assert analysis.play_metrics is not None
    assert analysis.result_metrics is None
    # プレイ画面では楽曲名のみ OCR で取得。score/combo の OCR 呼び出しは
    # I-027 対策で廃止したため None。
    assert analysis.play_metrics.raw_song_text == "テスト曲"
    assert analysis.play_metrics.score is None
    assert analysis.play_metrics.combo is None


def test_pipeline_play_skips_song_ocr_when_already_identified() -> None:
    """analyze(song_already_identified=True) で楽曲名 OCR をスキップ（I-027）。"""
    ocr = FakeOcr(items=[OcrItem("呼ばれない", 0.99, ())], text="")
    pipeline = RecognitionPipeline(ocr, FakeDigit())
    analysis = pipeline.analyze(
        _frame_with_signature(59), song_already_identified=True
    )
    assert analysis.detection.screen == ScreenType.PLAY
    assert analysis.play_metrics is not None
    assert analysis.play_metrics.raw_song_text == ""
    assert analysis.play_metrics.song_confidence == 0.0


def test_pipeline_result_screen_extracts_result_metrics() -> None:
    ocr = FakeOcr(text="STAGE CLEAR")
    pipeline = RecognitionPipeline(ocr, FakeDigit())
    # H≈6 のシグネチャ + dot8 点灯 → RESULT になるフレームを合成
    hsv = np.zeros((768, 1366, 3), dtype=np.uint8)
    sx1, sy1, sx2, sy2 = SCREEN_SIGNATURE_ROI
    hsv[sy1:sy2, sx1:sx2] = (6, 200, 150)
    hsv[674:689, 1309:1324] = (6, 200, 255)  # 「8」点灯
    hsv[736:751, 1288:1303] = (6, 200, 40)   # 「0」消灯
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    analysis = pipeline.analyze(frame)
    assert analysis.detection.screen == ScreenType.RESULT
    assert analysis.result_metrics is not None
    assert analysis.play_metrics is None


def test_pipeline_other_screen_has_no_metrics() -> None:
    pipeline = RecognitionPipeline(FakeOcr(), FakeDigit())
    analysis = pipeline.analyze(_frame_with_signature(19))  # SELECT
    assert analysis.detection.screen == ScreenType.SELECT
    assert analysis.play_metrics is None
    assert analysis.result_metrics is None


def test_pipeline_extraction_exception_is_swallowed() -> None:
    # OCR が例外を投げても analyze は落ちず、メトリクスは None になる
    pipeline = RecognitionPipeline(RaisingOcr(), FakeDigit())
    analysis = pipeline.analyze(_frame_with_signature(59))  # PLAY
    assert analysis.detection.screen == ScreenType.PLAY
    assert analysis.play_metrics is None
