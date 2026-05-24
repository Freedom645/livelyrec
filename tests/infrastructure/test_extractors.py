"""extractors（画面別メトリクス抽出）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from livelyrec.domain.score import ClearType, Difficulty
from livelyrec.infrastructure.ocr.base import OcrItem
from livelyrec.infrastructure.recognizer.extractors import (
    _detect_clear_type,
    _parse_signed_int,
    digits_only,
    digits_only_aggressive,
    extract_play_difficulty,
    extract_play_metrics,
    extract_result_metrics,
    parse_int_or,
)
from livelyrec.infrastructure.recognizer.roi_defs import PLAY_DIFFICULTY_ROI


@pytest.mark.parametrize(
    "difficulty, bgr",
    [
        (Difficulty.EASY, (255, 198, 46)),
        (Difficulty.NORMAL, (47, 217, 59)),
        (Difficulty.HYPER, (0, 120, 255)),
        (Difficulty.EX, (137, 81, 255)),
    ],
)
def test_extract_play_difficulty_by_theme_color(difficulty, bgr) -> None:
    x1, y1, x2, y2 = PLAY_DIFFICULTY_ROI
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    frame[y1:y2, x1:x2] = bgr
    assert extract_play_difficulty(frame) == difficulty


def test_extract_play_difficulty_returns_none_for_unrelated_color() -> None:
    # テーマ色から離れた色（黒）→ 難易度不明
    assert extract_play_difficulty(np.zeros((768, 1366, 3), dtype=np.uint8)) is None


class FakeOcr:
    """recognize/recognize_text が固定値を返すフェイク OCR。"""

    def __init__(self, items: list[OcrItem] | None = None, text: str = "") -> None:
        self._items = items or []
        self._text = text

    def recognize(self, image_bgr):  # noqa: ARG002
        return self._items

    def recognize_text(self, image_bgr):  # noqa: ARG002
        return self._text


class FakeDigit:
    """judge ごとに固定の数字文字列を返すフェイク数字認識器。"""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._m = mapping or {}

    def recognize(self, roi, judge):  # noqa: ARG002
        if judge in self._m:
            return self._m[judge], 0.9
        return "", 0.0

    def recognize_rightmost(self, roi, judge, count):  # noqa: ARG002
        if judge in self._m:
            return self._m[judge][-count:], 0.9
        return "", 0.0


# ---- 数字パースヘルパ ----

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("030210", "030210"),
        ("Ｓ4Ｂ7", "5487"),
        ("１２３", "123"),
        ("ABC", ""),
        ("score 87268 BEST", "87268"),
        ("Ｏ0ｏ0", "0000"),
        ("", ""),
    ],
)
def test_digits_only(raw: str, expected: str) -> None:
    assert digits_only(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("O0I1B8S5", "00118855"),
        ("l2", "12"),
        ("12O", "120"),
        ("", ""),
    ],
)
def test_digits_only_aggressive(raw: str, expected: str) -> None:
    assert digits_only_aggressive(raw) == expected


def test_parse_int_or_default() -> None:
    assert parse_int_or("000000") == 0
    assert parse_int_or("87268") == 87268
    assert parse_int_or("") is None
    assert parse_int_or("", default=0) == 0
    assert parse_int_or("ABC", default=42) == 42


def test_parse_signed_int() -> None:
    assert _parse_signed_int("+12345") == 12345
    assert _parse_signed_int("-5626") == -5626
    assert _parse_signed_int("90000") == 90000
    assert _parse_signed_int("") is None
    assert _parse_signed_int("abc") is None


# ---- clear_type 判定 ----

@pytest.mark.parametrize(
    "text, expected",
    [
        ("PERFECT", ClearType.PERFECT),
        ("FULL COMBO", ClearType.FULL_COMBO),
        ("STAGE FAILED", ClearType.FAILED),
        ("STAGE CLEAR", ClearType.CLEAR),
        ("クリア表示なし", None),
    ],
)
def test_detect_clear_type(text: str, expected: ClearType | None) -> None:
    roi = np.zeros((20, 60, 3), dtype=np.uint8)
    assert _detect_clear_type(roi, FakeOcr(text=text)) == expected


# ---- プレイ画面メトリクス抽出 ----

def test_extract_play_metrics() -> None:
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    ocr = FakeOcr(items=[OcrItem("テスト曲", 0.88, ())], text="054210")
    pm = extract_play_metrics(frame, ocr)
    assert pm.raw_song_text == "テスト曲"
    assert pm.score == 54210
    assert pm.combo == 54210
    assert pm.song_confidence == pytest.approx(0.88)


def test_extract_play_metrics_no_song_text() -> None:
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    pm = extract_play_metrics(frame, FakeOcr(items=[], text=""))
    assert pm.raw_song_text == ""
    assert pm.song_confidence == 0.0
    assert pm.score is None


# ---- リザルト画面メトリクス抽出 ----

def test_extract_result_metrics_uses_digit_recognizer() -> None:
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    ocr = FakeOcr(text="STAGE CLEAR")
    # score/combo/判定数すべて digit テンプレートマッチングで取得する（I-016）
    digit = FakeDigit({
        "cool": "312", "great": "18", "good": "5", "bad": "2",
        "score": "87268", "combo": "329",
    })
    rm = extract_result_metrics(frame, ocr, digit)
    assert rm.clear_type == ClearType.CLEAR
    assert rm.score == 87268
    assert rm.combo == 329
    assert rm.judgements.cool == 312
    assert rm.judgements.great == 18
    assert rm.judgements.good == 5
    assert rm.judgements.bad == 2


def test_extract_result_metrics_falls_back_to_ocr_for_judges() -> None:
    # 数字認識器が空を返す → OCR フォールバック（英字誤読も数字化）
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    ocr = FakeOcr(text="100")
    rm = extract_result_metrics(frame, ocr, FakeDigit())
    # フォールバック OCR は全 ROI で "100" を返すため判定数は 100 になる
    assert rm.judgements.cool == 100
