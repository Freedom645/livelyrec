"""判定数（色付き太字数字）テンプレートマッチング認識。

詳細: docs/design/poc/03_digit_recognition.md、docs/design/10_詳細設計_画像認識.md §5.2.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("livelyrec.ocr.digit")


@dataclass(frozen=True)
class ColorRange:
    """OpenCV HSV (0-180 hue) の色相帯。

    pop'n music lively の判定数フォントは縦方向グラデーション仕様で、
    上部はハイライトで彩度・色相が大きく変化する（白に近づく＝S が極小、
    かつ H も多少シフトする）。判定数 ROI 周辺は単色（黒）背景のため、
    s_min を低く取っても誤検出のリスクは無い。
    """
    h_lo: int
    h_hi: int
    s_min: int = 15
    v_min: int = 80


# 装飾数字の HSV 色帯（OpenCV の H は 0-180）。判定数（COOL/GREAT/GOOD/BAD）に
# 加え、リザルトの score/combo も同系の装飾フォントのため色キーとして登録する（I-016）。
# H 範囲はサンプル画像の実測 HSV から、グラデーション上端〜下端を覆うよう拡げてある。
JUDGE_COLOR: dict[str, ColorRange] = {
    "cool":  ColorRange(h_lo=135, h_hi=175),  # マゼンタ
    "great": ColorRange(h_lo=15, h_hi=45),    # 黄
    "good":  ColorRange(h_lo=0, h_hi=15),     # 赤（低 H 側）
    "bad":   ColorRange(h_lo=80, h_hi=130),   # 水色（上端は H=120 台まで上がる）
    "score": ColorRange(h_lo=10, h_hi=30, s_min=70, v_min=110),  # リザルトスコア（橙・グレア除外）
    "combo": ColorRange(h_lo=95, h_hi=125),   # リザルトコンボ（青グラデ）
}


@dataclass(frozen=True)
class DigitMatch:
    digit: int
    score: float


class DigitTemplateRecognizer:
    """指定色の数字（0-9）をテンプレートマッチングで読み取る。

    テンプレート画像は ``templates/digits/{resolution}/{0..9}.png`` を想定。
    色によらず数字形状は同一なので、テンプレは色非依存のグレースケール。
    """

    def __init__(
        self,
        templates: dict[int, np.ndarray],
        score_templates: dict[int, np.ndarray] | None = None,
        match_threshold: float = 0.6,
    ) -> None:
        # digit -> binary template (uint8, 0/255)
        self._templates = templates  # combo/判定数用
        self._score_templates = score_templates or {}  # リザルトスコア専用
        self._match_threshold = match_threshold

    @classmethod
    def load_from_dir(cls, dir_path: Path, match_threshold: float = 0.6) -> DigitTemplateRecognizer:
        """`dir/0..9.png` を combo/判定数用、`dir/score/0..9.png` をスコア専用に読む。"""
        templates = cls._load_set(dir_path)
        score_templates = cls._load_set(dir_path / "score")
        if not dir_path.exists():
            logger.warning("digit template directory not found: %s", dir_path)
        elif not templates:
            logger.warning("no digit templates loaded from %s", dir_path)
        return cls(templates, score_templates, match_threshold)

    @staticmethod
    def _load_set(dir_path: Path) -> dict[int, np.ndarray]:
        """ディレクトリ直下の 0.png..9.png を二値テンプレートとして読み込む。"""
        out: dict[int, np.ndarray] = {}
        if not dir_path.exists():
            return out
        for d in range(10):
            p = dir_path / f"{d}.png"
            if not p.exists():
                continue
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            _, bw = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
            out[d] = bw
        return out

    def loaded(self) -> bool:
        return bool(self._templates)

    def _templates_for(self, judge: str) -> dict[int, np.ndarray]:
        """判定キーに対応するテンプレート集合を返す（score は専用集合を優先）。"""
        if judge == "score" and self._score_templates:
            return self._score_templates
        return self._templates

    def recognize(self, roi_bgr: np.ndarray, judge: str) -> tuple[str, float]:
        """指定判定の数字を読み取り、(文字列, 平均スコア) を返す。テンプレ未ロード時は空。"""
        templates = self._templates_for(judge)
        if not templates:
            return "", 0.0
        color = JUDGE_COLOR.get(judge)
        if color is None:
            return "", 0.0
        mask = self._color_mask(roi_bgr, color)
        digit_boxes = self._extract_digit_boxes(mask)
        if not digit_boxes:
            return "", 0.0
        recognized: list[str] = []
        scores: list[float] = []
        for x, y, w, h in sorted(digit_boxes, key=lambda b: b[0]):
            match = self._best_match(mask[y:y + h, x:x + w], templates)
            if match is not None and match.score >= self._match_threshold:
                recognized.append(str(match.digit))
                scores.append(match.score)
        if not recognized:
            return "", 0.0
        return "".join(recognized), sum(scores) / len(scores)

    def recognize_rightmost(
        self, roi_bgr: np.ndarray, judge: str, count: int
    ) -> tuple[str, float]:
        """ROI 内で最も右にある count 個の数字を読み取り (文字列, 平均スコア) を返す。

        「ラベル＋数字」（例: "COOL 0014"）が並ぶプレイ画面の判定数表示から、
        ラベル文字を除いた右端の数字部のみを取得する用途。該当判定が 0 件で
        非表示の場合は空文字を返す。
        """
        templates = self._templates_for(judge)
        if not templates:
            return "", 0.0
        color = JUDGE_COLOR.get(judge)
        if color is None:
            return "", 0.0
        mask = self._color_mask(roi_bgr, color)
        boxes = sorted(self._extract_digit_boxes(mask), key=lambda b: b[0])
        if not boxes:
            return "", 0.0
        recognized: list[str] = []
        scores: list[float] = []
        for x, y, w, h in boxes[-count:]:
            match = self._best_match(mask[y:y + h, x:x + w], templates)
            if match is not None and match.score >= self._match_threshold:
                recognized.append(str(match.digit))
                scores.append(match.score)
        if not recognized:
            return "", 0.0
        return "".join(recognized), sum(scores) / len(scores)

    @staticmethod
    def _color_mask(roi_bgr: np.ndarray, color: ColorRange) -> np.ndarray:
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        if color.h_lo <= color.h_hi:
            m = cv2.inRange(
                hsv,
                (color.h_lo, color.s_min, color.v_min),
                (color.h_hi, 255, 255),
            )
        else:
            m1 = cv2.inRange(hsv, (0, color.s_min, color.v_min), (color.h_hi, 255, 255))
            m2 = cv2.inRange(hsv, (color.h_lo, color.s_min, color.v_min), (180, 255, 255))
            m = cv2.bitwise_or(m1, m2)
        # 軽くオープニングでノイズ除去
        kernel = np.ones((2, 2), np.uint8)
        return cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel)

    @staticmethod
    def _extract_digit_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
        n_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        boxes: list[tuple[int, int, int, int]] = []
        h_full = mask.shape[0]
        for i in range(1, n_labels):
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])
            # 数字候補としてのフィルタ: 高さ閾値・面積・アスペクト比
            # 閾値は絶対値 12px と ROI 高さ 25% のうち大きい方（ROI 高さ依存を緩和）
            if h < max(12, int(h_full * 0.25)):
                continue
            if area < 30:
                continue
            if w / max(h, 1) > 2.0 or h / max(w, 1) > 6.0:
                continue
            boxes.append((x, y, w, h))
        return boxes

    def _best_match(
        self, patch: np.ndarray, templates: dict[int, np.ndarray]
    ) -> DigitMatch | None:
        if patch.size == 0:
            return None
        best: DigitMatch | None = None
        for digit, tpl in templates.items():
            try:
                resized = cv2.resize(patch, (tpl.shape[1], tpl.shape[0]), interpolation=cv2.INTER_NEAREST)
                score = float(cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED).max())
            except Exception:
                continue
            if best is None or score > best.score:
                best = DigitMatch(digit=digit, score=score)
        return best
