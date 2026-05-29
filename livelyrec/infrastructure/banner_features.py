"""バナー画像特徴量計算ユーティリティ（FR-BAN-001〜002, v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §3

バナー画像（target_size: 390×94px）から知覚ハッシュを算出するためのユーティリティ。
本モジュールはステートを持たず、すべて純粋関数で構成される。

- :func:`phash64`: DCT ベースの 64bit Perceptual Hash
- :func:`dhash64`: 隣接差分ベースの 64bit Difference Hash
- :func:`hamming`: 64bit 整数のハミング距離
- :func:`prepare_gray`: 任意フレームを ROI 切り出し+リサイズ正規化+グレースケール化
"""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_TARGET_SIZE: tuple[int, int] = (390, 94)


def prepare_gray(
    frame_bgr: np.ndarray,
    roi: tuple[int, int, int, int],
    target_size: tuple[int, int] = DEFAULT_TARGET_SIZE,
) -> np.ndarray | None:
    """フレームから ROI を切り出し、target_size にリサイズしてグレースケール化する。

    ROI がフレーム外にある場合は None を返す（呼び出し側で WARN ログ）。
    """
    x1, y1, x2, y2 = roi
    h, w = frame_bgr.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h or x1 >= x2 or y1 >= y2:
        return None
    crop = frame_bgr[y1:y2, x1:x2]
    resized = cv2.resize(crop, target_size, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)


def phash64(gray: np.ndarray) -> int:
    """DCT ベースの 64bit Perceptual Hash を計算する。

    入力は任意サイズのグレースケール画像。32×32 に縮小→DCT→左上 8×8 ブロックの
    DC 成分を除く中央値で 0/1 ビット化し、64bit 整数として返す。
    """
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(small))
    block = dct[:8, :8].flatten()
    median = float(np.median(block[1:]))
    bits = (block > median).astype(np.uint8)
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return h


def dhash64(gray: np.ndarray) -> int:
    """隣接差分ベースの 64bit Difference Hash を計算する。

    入力は任意サイズのグレースケール画像。9×8 に縮小→水平方向の隣接差分を
    取って 8×8 のビット列とし、64bit 整数として返す。
    """
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = (small[:, 1:] > small[:, :-1]).flatten()
    h = 0
    for b in diff:
        h = (h << 1) | int(b)
    return h


def hamming(a: int, b: int) -> int:
    """64bit 整数のハミング距離を返す（Python 3.10+ の int.bit_count を使用）。"""
    return (a ^ b).bit_count()


def hex_from_hash(value: int) -> str:
    """64bit ハッシュ値を `0x` 付き 16 桁ゼロパディングの 16 進文字列に変換する。

    JSON 数値は IEEE754 53bit までしか保証されないため、配布時はこの形式で記録する。
    """
    if not 0 <= value < (1 << 64):
        raise ValueError(f"hash out of 64bit range: {value}")
    return f"0x{value:016x}"


def hash_from_hex(text: str) -> int:
    """`0x` 付き 16 進文字列を 64bit 整数に復元する。"""
    if not text.startswith(("0x", "0X")):
        raise ValueError(f"hash hex must start with 0x: {text!r}")
    value = int(text, 16)
    if not 0 <= value < (1 << 64):
        raise ValueError(f"hash out of 64bit range: {value}")
    return value
