"""DigitTemplateRecognizer（判定数テンプレートマッチング）のテスト。

KONAMI 公式アセットは使わず、numpy で合成したリング状の二値パターンを
テンプレート兼数字形状として用い、色マスク・連結成分・マッチングを検証する。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from livelyrec.infrastructure.ocr.digit_template import (
    ColorRange,
    DigitTemplateRecognizer,
)

_RED_BGR = (0, 0, 255)  # good 判定の色帯（H≈0）に入る純赤


def _ring(h: int, w: int, border: int) -> np.ndarray:
    """外枠 border px が 255、内部 0 の矩形リングパターン。"""
    a = np.zeros((h, w), dtype=np.uint8)
    a[:border, :] = 255
    a[-border:, :] = 255
    a[:, :border] = 255
    a[:, -border:] = 255
    return a


def _bar(h: int, w: int) -> np.ndarray:
    """中央縦バーのみ 255。リングとは形状が大きく異なる。"""
    a = np.zeros((h, w), dtype=np.uint8)
    a[:, w // 2 - 4 : w // 2 + 4] = 255
    return a


def _ring_roi(width: int = 60, x_positions: tuple[int, ...] = (10,)) -> np.ndarray:
    """指定位置に赤いリング（22x16, border 4）を描いた BGR ROI。"""
    roi = np.zeros((26, width, 3), dtype=np.uint8)
    ring = _ring(22, 16, 4)
    for x in x_positions:
        sub = roi[2:24, x : x + 16]
        sub[ring == 255] = _RED_BGR
    return roi


# ---- ロード ----

def test_load_from_missing_dir_is_empty() -> None:
    rec = DigitTemplateRecognizer.load_from_dir(Path("does_not_exist_xyz"))
    assert not rec.loaded()


def test_load_from_dir_loads_png(tmp_path: Path) -> None:
    cv2.imwrite(str(tmp_path / "0.png"), _ring(44, 32, 8))
    cv2.imwrite(str(tmp_path / "7.png"), _ring(40, 28, 6))
    rec = DigitTemplateRecognizer.load_from_dir(tmp_path)
    assert rec.loaded()


def test_load_from_dir_skips_invalid_file(tmp_path: Path) -> None:
    (tmp_path / "3.png").write_bytes(b"not a real image")
    cv2.imwrite(str(tmp_path / "0.png"), _ring(44, 32, 8))
    rec = DigitTemplateRecognizer.load_from_dir(tmp_path)
    assert rec.loaded()  # 0.png は読めるためロード済み


def test_load_from_empty_dir_not_loaded(tmp_path: Path) -> None:
    rec = DigitTemplateRecognizer.load_from_dir(tmp_path)
    assert not rec.loaded()


# ---- recognize: 早期リターン ----

def test_recognize_without_templates_returns_empty() -> None:
    rec = DigitTemplateRecognizer({})
    assert rec.recognize(_ring_roi(), "good") == ("", 0.0)


def test_recognize_unknown_judge_returns_empty() -> None:
    rec = DigitTemplateRecognizer({0: _ring(44, 32, 8)})
    assert rec.recognize(_ring_roi(), "not_a_judge") == ("", 0.0)


def test_recognize_blank_roi_returns_empty() -> None:
    rec = DigitTemplateRecognizer({0: _ring(44, 32, 8)})
    assert rec.recognize(np.zeros((26, 60, 3), dtype=np.uint8), "good") == ("", 0.0)


def test_recognize_tiny_blob_rejected() -> None:
    # 4x4 の小ブロックは高さ・面積フィルタで弾かれる
    rec = DigitTemplateRecognizer({0: _ring(44, 32, 8)}, match_threshold=0.5)
    roi = np.zeros((26, 60, 3), dtype=np.uint8)
    roi[2:6, 10:14] = _RED_BGR
    assert rec.recognize(roi, "good") == ("", 0.0)


# ---- recognize: マッチング ----

def test_recognize_single_digit() -> None:
    rec = DigitTemplateRecognizer({0: _ring(44, 32, 8)}, match_threshold=0.5)
    text, score = rec.recognize(_ring_roi(), "good")
    assert text == "0"
    assert score >= 0.5


def test_recognize_multiple_digits_left_to_right() -> None:
    rec = DigitTemplateRecognizer({0: _ring(44, 32, 8)}, match_threshold=0.5)
    roi = _ring_roi(width=80, x_positions=(8, 32, 56))
    text, _ = rec.recognize(roi, "good")
    assert text == "000"


def test_recognize_below_threshold_returns_empty() -> None:
    # ROI はリング型、テンプレは縦バー型 → マッチスコアが高閾値に届かない
    rec = DigitTemplateRecognizer({1: _bar(44, 32)}, match_threshold=0.95)
    text, _ = rec.recognize(_ring_roi(), "good")
    assert text == ""


# ---- 色マスク ----

def test_color_mask_normal_range() -> None:
    roi = np.full((10, 10, 3), _RED_BGR, dtype=np.uint8)
    color = ColorRange(h_lo=0, h_hi=15)
    mask = DigitTemplateRecognizer._color_mask(roi, color)
    assert mask.shape == (10, 10)
    assert (mask > 0).any()


def test_color_mask_wraparound_range() -> None:
    # h_lo > h_hi の色相環ラップアラウンド分岐
    roi = np.full((10, 10, 3), _RED_BGR, dtype=np.uint8)
    color = ColorRange(h_lo=170, h_hi=10)
    mask = DigitTemplateRecognizer._color_mask(roi, color)
    assert (mask > 0).any()  # 純赤(H≈0)はラップアラウンド帯に含まれる
