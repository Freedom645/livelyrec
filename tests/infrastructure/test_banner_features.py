"""banner_features モジュールの単体テスト（FR-BAN-001〜002）。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from livelyrec.infrastructure.banner_features import (
    DEFAULT_TARGET_SIZE,
    dhash64,
    hamming,
    hash_from_hex,
    hex_from_hash,
    phash64,
    prepare_gray,
)


def _make_gradient(w: int = 390, h: int = 94, seed: int = 0) -> np.ndarray:
    """決定論的なグラデーション画像を生成（BGR）。"""
    rng = np.random.default_rng(seed)
    gradient = np.linspace(0, 255, w * h, dtype=np.uint8).reshape(h, w)
    noise = rng.integers(0, 16, size=(h, w), dtype=np.uint8)
    gray = cv2.add(gradient, noise)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class TestPhashDhashDeterminism:
    """同一入力に対する出力の決定論性。"""

    def test_phash_is_deterministic(self) -> None:
        img = _make_gradient(seed=42)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h1 = phash64(gray)
        h2 = phash64(gray)
        assert h1 == h2

    def test_dhash_is_deterministic(self) -> None:
        img = _make_gradient(seed=42)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h1 = dhash64(gray)
        h2 = dhash64(gray)
        assert h1 == h2

    def test_phash_fits_in_64bit(self) -> None:
        img = _make_gradient(seed=7)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h = phash64(gray)
        assert 0 <= h < (1 << 64)

    def test_dhash_fits_in_64bit(self) -> None:
        img = _make_gradient(seed=7)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h = dhash64(gray)
        assert 0 <= h < (1 << 64)


class TestHamming:
    def test_self_distance_is_zero(self) -> None:
        assert hamming(0xdeadbeefdeadbeef, 0xdeadbeefdeadbeef) == 0

    def test_symmetry(self) -> None:
        a, b = 0x0123456789abcdef, 0xfedcba9876543210
        assert hamming(a, b) == hamming(b, a)

    def test_complementary_is_64(self) -> None:
        a = 0x0000000000000000
        b = 0xffffffffffffffff
        assert hamming(a, b) == 64

    def test_single_bit_diff(self) -> None:
        assert hamming(0, 1) == 1
        assert hamming(0, 0b1010) == 2


class TestPrepareGray:
    def test_returns_gray_of_target_size(self) -> None:
        img = _make_gradient(w=1366, h=768)
        gray = prepare_gray(img, (100, 100, 600, 300))
        assert gray is not None
        assert gray.shape == (DEFAULT_TARGET_SIZE[1], DEFAULT_TARGET_SIZE[0])
        assert gray.dtype == np.uint8

    def test_returns_none_when_roi_out_of_frame(self) -> None:
        img = _make_gradient(w=1366, h=768)
        assert prepare_gray(img, (1000, 0, 2000, 100)) is None
        assert prepare_gray(img, (-10, 0, 100, 100)) is None
        assert prepare_gray(img, (100, 200, 50, 100)) is None  # x2 < x1

    def test_custom_target_size(self) -> None:
        img = _make_gradient()
        gray = prepare_gray(img, (0, 0, 200, 50), target_size=(64, 32))
        assert gray is not None
        assert gray.shape == (32, 64)


class TestHashEncoding:
    @pytest.mark.parametrize(
        "value",
        [
            0,
            1,
            0xdeadbeefdeadbeef,
            (1 << 64) - 1,
        ],
    )
    def test_round_trip(self, value: int) -> None:
        text = hex_from_hash(value)
        assert text.startswith("0x")
        assert len(text) == 2 + 16  # "0x" + 16 hex digits
        assert hash_from_hex(text) == value

    def test_pad_to_16_digits(self) -> None:
        assert hex_from_hash(0xf) == "0x000000000000000f"

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            hex_from_hash(-1)
        with pytest.raises(ValueError):
            hex_from_hash(1 << 64)

    def test_missing_prefix_raises(self) -> None:
        with pytest.raises(ValueError):
            hash_from_hex("deadbeefdeadbeef")
