"""フレーム正規化（normalize_frame / crop）のテスト。"""

from __future__ import annotations

import numpy as np
import pytest

from livelyrec.infrastructure.recognizer.normalize import crop, normalize_frame
from livelyrec.shared.constants import SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH


def test_normalize_resizes_to_base_resolution() -> None:
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    nf = normalize_frame(img)
    assert nf.image_bgr.shape == (SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH, 3)
    assert nf.original_size == (640, 480)


def test_normalize_keeps_base_resolution_untouched() -> None:
    img = np.zeros((SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH, 3), dtype=np.uint8)
    nf = normalize_frame(img)
    # 既に基準解像度ならリサイズせず同一配列を返す
    assert nf.image_bgr is img
    assert nf.original_size == (SCREEN_BASE_WIDTH, SCREEN_BASE_HEIGHT)


def test_normalize_records_aspect_ratio() -> None:
    img = np.zeros((SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH, 3), dtype=np.uint8)
    nf = normalize_frame(img)
    assert abs(nf.aspect_ratio - SCREEN_BASE_WIDTH / SCREEN_BASE_HEIGHT) < 0.01


def test_normalize_non_16_9_still_resizes() -> None:
    # 4:3 のアスペクト比でも警告のうえリサイズされる
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    nf = normalize_frame(img)
    assert nf.image_bgr.shape == (SCREEN_BASE_HEIGHT, SCREEN_BASE_WIDTH, 3)


def test_normalize_none_raises() -> None:
    with pytest.raises(ValueError):
        normalize_frame(None)  # type: ignore[arg-type]


def test_normalize_empty_raises() -> None:
    with pytest.raises(ValueError):
        normalize_frame(np.zeros((0, 0, 3), dtype=np.uint8))


def test_crop_extracts_box() -> None:
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    frame[10:20, 30:40] = 255
    cropped = crop(frame, (30, 10, 40, 20))
    assert cropped.shape == (10, 10, 3)
    assert (cropped == 255).all()
