"""画面種別判別。

詳細: docs/design/10_詳細設計_画像認識.md §3

判別方式（2026-05-21 更新 / 工程8 ② ハイブリッド）:
  1. タイトル/クエスト画面: 参照サムネイル（`screen_signatures.npz`）との
     最近傍距離で先に判定する。これらは右下シグネチャがゲーム画面と偶然
     一致して誤判定されるため、画面全体の低解像度サムネイル照合で分離する。
  2. それ以外: 画面右下 (1286,672)-(1347,754) の HSV 平均（主に色相 H）で
     ゲーム画面を分類する。OPTION と RESULT は色相が近接（H≈6.5）するため、
     テンキー内の特定キー点灯（"8"=RESULT / "0"=OPTION）で分離する。

実測値ベースのリファレンス H 値:
    SELECT=19, PLAY=59, READY=79, LOAD_TO_READY=103, LOAD_TO_PLAY=120, OPTION/RESULT=6.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from livelyrec.domain.state import ScreenType

from .normalize import crop
from .roi_defs import (
    SCREEN_OPTION_DOT0_ROI,
    SCREEN_RESULT_DOT8_ROI,
    SCREEN_SIGNATURE_ROI,
)

logger = logging.getLogger("livelyrec.recognizer.screen")


@dataclass(frozen=True)
class ScreenDetection:
    screen: ScreenType
    confidence: float
    details: dict[str, float]


@dataclass(frozen=True)
class _HueSignature:
    screen: ScreenType
    hue: float
    tol: float = 8.0


# 赤テンキー系は H が近接するため、別途分離ロジックで処理する
_TENKEY_RED_HUE = 6.5
_TENKEY_RED_TOL = 8.0

# 右下シグネチャの一意リファレンス
_HUE_SIGNATURES: tuple[_HueSignature, ...] = (
    _HueSignature(ScreenType.SELECT,        hue=19.0,  tol=8.0),
    _HueSignature(ScreenType.PLAY,          hue=59.0,  tol=8.0),
    _HueSignature(ScreenType.READY,         hue=79.0,  tol=8.0),
    _HueSignature(ScreenType.LOAD_TO_READY, hue=103.0, tol=8.0),
    _HueSignature(ScreenType.LOAD_TO_PLAY,  hue=120.0, tol=8.0),
)

# 過渡フレーム（黒画面・白フェード等）を排除するための彩度閾値。
_S_MIN_FOR_VALID = 80.0

# タイトル/クエスト判定用の低解像度サムネイル
_THUMB_W, _THUMB_H = 32, 18
_THUMB_DIM = _THUMB_W * _THUMB_H * 3
# 参照サムネイルとの距離がこの値以下なら該当画面とみなす（工程8 ② で実測）。
# 実測: タイトル/クエストのクラス内最大 372/1048、他クラス最小 2832/2860。
_SPECIAL_THRESHOLD = 2000.0


def _hue_diff(a: float, b: float, modulo: float = 180.0) -> float:
    """円環距離。OpenCV の H は 0..179。"""
    d = abs(a - b) % modulo
    return min(d, modulo - d)


def _mean_hsv(roi_bgr: np.ndarray) -> tuple[float, float, float]:
    if roi_bgr.size == 0:
        return (0.0, 0.0, 0.0)
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    return (
        float(hsv[..., 0].mean()),
        float(hsv[..., 1].mean()),
        float(hsv[..., 2].mean()),
    )


def _mean_v(roi_bgr: np.ndarray) -> float:
    return _mean_hsv(roi_bgr)[2]


def _thumbnail(frame_bgr: np.ndarray) -> np.ndarray:
    """画面全体の低解像度サムネイル（タイトル/クエスト照合用）。"""
    return (
        cv2.resize(frame_bgr, (_THUMB_W, _THUMB_H), interpolation=cv2.INTER_AREA)
        .astype(np.float32)
        .flatten()
    )


def _min_distance(thumb: np.ndarray, refs: np.ndarray) -> float:
    if refs.size == 0:
        return float("inf")
    return float(np.min(np.linalg.norm(refs - thumb, axis=1)))


def load_screen_signatures(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """`screen_signatures.npz` から title/quest 参照サムネイルを読み込む。

    見つからない／壊れている場合は空配列を返す（タイトル/クエスト判定はスキップ）。
    """
    empty = np.zeros((0, _THUMB_DIM), dtype=np.float32)
    p = Path(path)
    if not p.exists():
        logger.warning("screen signatures not found: %s", p)
        return empty, empty
    try:
        data = np.load(p)
        return data["title"].astype(np.float32), data["quest"].astype(np.float32)
    except Exception:
        logger.warning("failed to load screen signatures: %s", p, exc_info=True)
        return empty, empty


class ScreenDetector:
    """右下シグネチャ＋タイトル/クエスト参照照合による画面判別。

    OCR は不要のため `ocr` 引数は互換のため受け取るが内部では未使用。
    `signatures_path` を渡すとタイトル/クエストの参照照合を有効化する。
    """

    def __init__(  # noqa: ARG002
        self,
        ocr=None,
        signatures_path: str | Path | None = None,
    ) -> None:
        self._ocr = ocr
        if signatures_path is not None:
            self._title_refs, self._quest_refs = load_screen_signatures(signatures_path)
        else:
            empty = np.zeros((0, _THUMB_DIM), dtype=np.float32)
            self._title_refs, self._quest_refs = empty, empty

    def detect(self, frame_bgr: np.ndarray) -> ScreenDetection:
        # 1. タイトル/クエスト画面の判定（参照サムネイル照合）
        special = self._match_special(frame_bgr)
        if special is not None:
            return special

        # 2. 右下シグネチャによるゲーム画面の判定
        sig_roi = crop(frame_bgr, SCREEN_SIGNATURE_ROI)
        h_mean, s_mean, v_mean = _mean_hsv(sig_roi)
        details: dict[str, float] = {
            "sig_h": h_mean,
            "sig_s": s_mean,
            "sig_v": v_mean,
        }

        # 過渡フレーム: 単色領域が彩度低い → 判定不能
        if s_mean < _S_MIN_FOR_VALID:
            return ScreenDetection(ScreenType.UNKNOWN, 0.0, details)

        # OPTION / RESULT (赤テンキー領域) は H が近接するため別途分離
        if _hue_diff(h_mean, _TENKEY_RED_HUE) < _TENKEY_RED_TOL:
            v8 = _mean_v(crop(frame_bgr, SCREEN_RESULT_DOT8_ROI))
            v0 = _mean_v(crop(frame_bgr, SCREEN_OPTION_DOT0_ROI))
            details["dot8_v"] = v8
            details["dot0_v"] = v0
            screen = ScreenType.RESULT if v8 > v0 else ScreenType.OPTION
            diff = abs(v8 - v0)
            conf = min(1.0, 0.6 + diff / 200.0)
            return ScreenDetection(screen, conf, details)

        # それ以外は H で一意マッチ
        best: _HueSignature | None = None
        best_diff = float("inf")
        for sig in _HUE_SIGNATURES:
            d = _hue_diff(h_mean, sig.hue)
            if d < sig.tol and d < best_diff:
                best = sig
                best_diff = d
        if best is None:
            return ScreenDetection(ScreenType.UNKNOWN, 0.0, details)

        details["matched_hue"] = best.hue
        details["hue_diff"] = best_diff
        confidence = max(0.5, 1.0 - best_diff / (best.tol * 2))
        return ScreenDetection(best.screen, confidence, details)

    def _match_special(self, frame_bgr: np.ndarray) -> ScreenDetection | None:
        """タイトル/クエスト画面を参照サムネイル照合で判定する。"""
        if self._title_refs.size == 0 and self._quest_refs.size == 0:
            return None
        thumb = _thumbnail(frame_bgr)
        title_d = _min_distance(thumb, self._title_refs)
        quest_d = _min_distance(thumb, self._quest_refs)
        if title_d <= _SPECIAL_THRESHOLD and title_d <= quest_d:
            conf = max(0.5, 1.0 - title_d / (_SPECIAL_THRESHOLD * 2))
            return ScreenDetection(ScreenType.TITLE, conf, {"thumb_dist": title_d})
        if quest_d <= _SPECIAL_THRESHOLD:
            conf = max(0.5, 1.0 - quest_d / (_SPECIAL_THRESHOLD * 2))
            return ScreenDetection(ScreenType.QUEST, conf, {"thumb_dist": quest_d})
        return None
