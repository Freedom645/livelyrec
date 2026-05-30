"""SELECT 画面の認識ユーティリティ（FR-BAN-002, v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §6.2、§13.2

選曲画面で特定したバナー（楽曲）に対し、UPPER 譜面マークの有無と
難易度色マークを判定して `(song_id, difficulty, is_upper)` の組
= chart_id を確定するためのヘルパ群。

- :func:`detect_upper_mark`: SELECT_ROI["upper_mark"] にテンプレ画像
  `templates/select/upper_mark.png` をマッチングして UPPER 譜面選択中かを判定
- :func:`detect_difficulty_color`: SELECT_ROI["difficulty_color"] の HSV
  平均色相から EASY/NORMAL/HYPER/EX を 4 値分類
- :func:`load_upper_template`: テンプレ画像をグレースケールで読み込む
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from livelyrec.domain.score import Difficulty

from .roi_defs import SELECT_ROI

logger = logging.getLogger("livelyrec.recognizer.select")

# UPPER テンプレートマッチのしきい値（実機 13 サンプル検証で
# UPPER 譜面 0.964-0.996、通常譜面 -0.065〜0.035 と margin 充分）
DEFAULT_UPPER_MATCH_THRESHOLD = 0.6

# 難易度色マークの HSV 色相分類しきい値（実機サンプル実測値）
# 各難易度の中心 H と半径（H 差）を持ち、最も近い難易度を採用
_DIFFICULTY_HUE_TABLE: tuple[tuple[Difficulty, int], ...] = (
    (Difficulty.HYPER, 26),    # 橙
    (Difficulty.NORMAL, 44),   # 黄緑
    (Difficulty.EASY, 113),    # 緑/青
    (Difficulty.EX, 175),      # 桃
)
# H の許容幅（中心から ±この値以内なら採用）
DEFAULT_HUE_TOLERANCE = 12
# 彩度が低すぎる（無彩色）場合は判定不能とする
DEFAULT_SATURATION_MIN = 80


def load_upper_template(path: Path) -> np.ndarray:
    """UPPER 譜面テンプレート画像をグレースケールで読み込む。

    形状が SELECT_ROI["upper_mark"] と一致するかは呼び出し側で検証する。
    """
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"upper template not loadable: {path}")
    return img


def _crop_roi(frame_bgr: np.ndarray, roi_key: str) -> np.ndarray | None:
    roi = SELECT_ROI.get(roi_key)
    if roi is None:
        return None
    x1, y1, x2, y2 = roi
    h, w = frame_bgr.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h or x1 >= x2 or y1 >= y2:
        return None
    return frame_bgr[y1:y2, x1:x2]


def _match_template_at_roi(
    frame_bgr: np.ndarray,
    roi_key: str,
    template_gray: np.ndarray,
) -> float:
    """指定 ROI でテンプレートマッチを試行し、最大相関スコアを返す。

    ROI 範囲外・テンプレ形状不一致・読込不能のときは 0.0 を返す（安全側）。
    """
    crop = _crop_roi(frame_bgr, roi_key)
    if crop is None:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if gray.shape != template_gray.shape:
        logger.warning(
            "%s ROI shape %s != template shape %s",
            roi_key, gray.shape, template_gray.shape,
        )
        return 0.0
    res = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, score, _, _ = cv2.minMaxLoc(res)
    return float(score)


def detect_upper_mark(
    frame_bgr: np.ndarray,
    template_gray: np.ndarray,
    template_gray_left: np.ndarray | None = None,
    threshold: float = DEFAULT_UPPER_MATCH_THRESHOLD,
) -> tuple[bool, float]:
    """SELECT 画面で UPPER 譜面が選択されているかをテンプレートマッチで判定。

    UPPER マークは譜面ごとに固定で「右側」または「左側」に表示される（規則性
    不明、実機サンプルで両側パターン確認、2026-05-31）。`template_gray` で
    右側用テンプレ、`template_gray_left` で左側用テンプレを渡し、どちらかの
    ROI で相関スコアがしきい値超えなら is_upper=True とする。

    Returns:
        (is_upper, score)
        - is_upper: 右側 or 左側のどちらかの ROI で相関スコアが
          `threshold` 以上なら True
        - score: 両側を試行した中の最大スコア（最良マッチ）
        - 両側とも判定不能なら (False, 0.0)
    """
    score_right = _match_template_at_roi(frame_bgr, "upper_mark", template_gray)
    score_left = 0.0
    if template_gray_left is not None:
        score_left = _match_template_at_roi(
            frame_bgr, "upper_mark_left", template_gray_left
        )
    best = max(score_right, score_left)
    return bool(best >= threshold), best


def detect_difficulty_color(
    frame_bgr: np.ndarray,
    tolerance: int = DEFAULT_HUE_TOLERANCE,
    saturation_min: int = DEFAULT_SATURATION_MIN,
) -> Difficulty | None:
    """SELECT 画面の難易度色マーク領域から HSV 平均色相で難易度を分類する。

    Returns:
        Difficulty もしくは None（判定不能：ROI 外 / 彩度不足 / 既知色相と
        どれもマッチしない）
    """
    crop = _crop_roi(frame_bgr, "difficulty_color")
    if crop is None:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h_mean = float(hsv[:, :, 0].mean())
    s_mean = float(hsv[:, :, 1].mean())
    if s_mean < saturation_min:
        return None
    best_diff: Difficulty | None = None
    best_dist = tolerance + 1
    for diff, center_h in _DIFFICULTY_HUE_TABLE:
        # H は環状（0..180）。最短距離を計算
        d = min(abs(h_mean - center_h), 180 - abs(h_mean - center_h))
        if d <= tolerance and d < best_dist:
            best_diff = diff
            best_dist = int(d)
    return best_diff
