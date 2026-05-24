"""画面判別（右下シグネチャ方式）のテスト。

KONAMI 公式アセットは使わず、numpy で合成した HSV フレームで
色相シグネチャ判定と OPTION/RESULT のテンキー点灯分離を検証する。
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from livelyrec.domain.state import ScreenType
from livelyrec.infrastructure.recognizer.roi_defs import (
    SCREEN_OPTION_DOT0_ROI,
    SCREEN_RESULT_DOT8_ROI,
    SCREEN_SIGNATURE_ROI,
)
from livelyrec.infrastructure.recognizer.screen_detector import (
    ScreenDetector,
    load_screen_signatures,
)


def _blank_hsv() -> np.ndarray:
    return np.zeros((768, 1366, 3), dtype=np.uint8)


def _fill(hsv: np.ndarray, box: tuple[int, int, int, int], h: int, s: int, v: int) -> None:
    x1, y1, x2, y2 = box
    hsv[y1:y2, x1:x2] = (h, s, v)


def _frame_with_signature(hue: int, s: int = 200, v: int = 200) -> np.ndarray:
    """右下シグネチャ ROI を指定 HSV で塗ったフレームを合成する。"""
    hsv = _blank_hsv()
    _fill(hsv, SCREEN_SIGNATURE_ROI, hue, s, v)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def _option_result_frame(*, is_result: bool) -> np.ndarray:
    """OPTION/RESULT 用フレーム。テンキーの点灯位置で区別する。"""
    hsv = _blank_hsv()
    _fill(hsv, SCREEN_SIGNATURE_ROI, 6, 200, 150)  # 赤系シグネチャ
    if is_result:
        _fill(hsv, SCREEN_RESULT_DOT8_ROI, 6, 200, 255)  # 「8」点灯
        _fill(hsv, SCREEN_OPTION_DOT0_ROI, 6, 200, 40)   # 「0」消灯
    else:
        _fill(hsv, SCREEN_RESULT_DOT8_ROI, 6, 200, 40)
        _fill(hsv, SCREEN_OPTION_DOT0_ROI, 6, 200, 255)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


@pytest.mark.parametrize(
    "hue, expected",
    [
        (19, ScreenType.SELECT),
        (59, ScreenType.PLAY),
        (79, ScreenType.READY),
        (103, ScreenType.LOAD_TO_READY),
        (120, ScreenType.LOAD_TO_PLAY),
    ],
)
def test_detect_by_hue_signature(hue: int, expected: ScreenType) -> None:
    result = ScreenDetector().detect(_frame_with_signature(hue))
    assert result.screen == expected
    assert result.confidence > 0.5


def test_detect_result_via_dot8_lit() -> None:
    result = ScreenDetector().detect(_option_result_frame(is_result=True))
    assert result.screen == ScreenType.RESULT
    assert result.details["dot8_v"] > result.details["dot0_v"]


def test_detect_option_via_dot0_lit() -> None:
    result = ScreenDetector().detect(_option_result_frame(is_result=False))
    assert result.screen == ScreenType.OPTION
    assert result.details["dot0_v"] > result.details["dot8_v"]


def test_detect_low_saturation_is_unknown() -> None:
    # 過渡フレーム（黒画面・フェード）: 彩度が低い → 判定不能
    result = ScreenDetector().detect(_frame_with_signature(59, s=10, v=200))
    assert result.screen == ScreenType.UNKNOWN
    assert result.confidence == 0.0


def test_detect_unmatched_hue_is_unknown() -> None:
    # どのシグネチャ色相にも該当しない（緑系 H=150）
    result = ScreenDetector().detect(_frame_with_signature(150, s=200, v=200))
    assert result.screen == ScreenType.UNKNOWN


def test_detection_exposes_signature_details() -> None:
    result = ScreenDetector().detect(_frame_with_signature(59))
    assert "sig_h" in result.details
    assert "sig_s" in result.details
    assert "sig_v" in result.details


def test_detector_accepts_ocr_arg_for_compatibility() -> None:
    # OCR は未使用だが、互換のため引数受け取りは維持されている
    detector = ScreenDetector(ocr=object())
    result = detector.detect(_frame_with_signature(19))
    assert result.screen == ScreenType.SELECT


# ---- タイトル/クエスト判定（工程8 ② ハイブリッド）----

def _solid_frame(bgr: tuple[int, int, int]) -> np.ndarray:
    return np.full((768, 1366, 3), bgr, dtype=np.uint8)


def _thumb(frame: np.ndarray) -> np.ndarray:
    return (
        cv2.resize(frame, (32, 18), interpolation=cv2.INTER_AREA)
        .astype(np.float32)
        .flatten()
    )


def _make_signatures(tmp_path, title_frame, quest_frame):
    npz = tmp_path / "screen_signatures.npz"
    np.savez(
        npz,
        title=np.stack([_thumb(title_frame)]).astype(np.uint8),
        quest=np.stack([_thumb(quest_frame)]).astype(np.uint8),
    )
    return npz


def test_load_screen_signatures_missing_returns_empty(tmp_path) -> None:
    title, quest = load_screen_signatures(tmp_path / "nope.npz")
    assert title.size == 0
    assert quest.size == 0


def test_detect_title_and_quest_via_reference(tmp_path) -> None:
    title_frame = _solid_frame((200, 150, 30))
    quest_frame = _solid_frame((30, 180, 200))
    det = ScreenDetector(
        signatures_path=_make_signatures(tmp_path, title_frame, quest_frame)
    )
    assert det.detect(title_frame).screen == ScreenType.TITLE
    assert det.detect(quest_frame).screen == ScreenType.QUEST


def test_game_screen_not_false_matched_as_special(tmp_path) -> None:
    # タイトル/クエスト参照を持っていても、ゲーム画面はシグネチャで正しく判定される
    npz = _make_signatures(
        tmp_path, _solid_frame((200, 150, 30)), _solid_frame((30, 180, 200))
    )
    det = ScreenDetector(signatures_path=npz)
    assert det.detect(_frame_with_signature(59)).screen == ScreenType.PLAY
    assert det.detect(_frame_with_signature(19)).screen == ScreenType.SELECT


def test_detector_without_signatures_uses_signature_only() -> None:
    # signatures 未指定なら従来のシグネチャ方式のみ（タイトル/クエスト判定なし）
    det = ScreenDetector()
    assert det.detect(_frame_with_signature(59)).screen == ScreenType.PLAY
