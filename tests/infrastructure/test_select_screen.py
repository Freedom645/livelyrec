"""SELECT 画面認識ユーティリティの単体テスト（FR-BAN-002, v2.0）。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from livelyrec.domain.score import Difficulty
from livelyrec.infrastructure.recognizer.roi_defs import SELECT_ROI
from livelyrec.infrastructure.recognizer.select_screen import (
    detect_difficulty_color,
    detect_upper_mark,
    load_upper_template,
)

REPO = Path(__file__).resolve().parents[2]


def _make_frame_with_patch(roi_key: str, patch: np.ndarray) -> np.ndarray:
    """1366×768 BGR フレームの指定 SELECT_ROI 領域に patch を貼り込む。"""
    x1, y1, x2, y2 = SELECT_ROI[roi_key]
    h, w = patch.shape[:2]
    assert (w, h) == (x2 - x1, y2 - y1), (
        f"patch shape {(w, h)} != ROI shape {(x2-x1, y2-y1)} for {roi_key}"
    )
    frame = np.zeros((768, 1366, 3), dtype=np.uint8)
    frame[y1:y2, x1:x2] = patch
    return frame


def _make_uniform_hsv_patch(roi_key: str, h: int, s: int, v: int) -> np.ndarray:
    """指定 ROI 形状の単色 HSV パッチを BGR で生成。"""
    x1, y1, x2, y2 = SELECT_ROI[roi_key]
    hsv = np.full(((y2 - y1), (x2 - x1), 3), (h, s, v), dtype=np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


# ---- UPPER テンプレート ----


@pytest.fixture
def upper_template() -> np.ndarray:
    return load_upper_template(REPO / "templates" / "select" / "upper_mark.png")


class TestLoadUpperTemplate:
    def test_template_loadable(self, upper_template: np.ndarray) -> None:
        x1, y1, x2, y2 = SELECT_ROI["upper_mark"]
        assert upper_template.shape == (y2 - y1, x2 - x1)
        assert upper_template.dtype == np.uint8

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_upper_template(tmp_path / "missing.png")


# ---- UPPER マーク検出 ----


class TestDetectUpperMark:
    def test_self_match_returns_high_score(self, upper_template: np.ndarray) -> None:
        # テンプレ自身を ROI に貼り込めばスコアは 1.0 近く
        patch_bgr = cv2.cvtColor(upper_template, cv2.COLOR_GRAY2BGR)
        frame = _make_frame_with_patch("upper_mark", patch_bgr)
        is_upper, score = detect_upper_mark(frame, upper_template)
        assert is_upper is True
        assert score > 0.99

    def test_uniform_dark_returns_low_score(
        self, upper_template: np.ndarray
    ) -> None:
        # 全黒パッチは UPPER ロゴと相関しない
        x1, y1, x2, y2 = SELECT_ROI["upper_mark"]
        frame = np.zeros((768, 1366, 3), dtype=np.uint8)
        is_upper, score = detect_upper_mark(frame, upper_template)
        assert is_upper is False
        # 一様画像との相関は -1.0〜1.0 のどこかだが少なくとも 0.6 未満
        assert score < 0.6

    def test_threshold_boundary(self, upper_template: np.ndarray) -> None:
        patch_bgr = cv2.cvtColor(upper_template, cv2.COLOR_GRAY2BGR)
        frame = _make_frame_with_patch("upper_mark", patch_bgr)
        # スコアは ~1.0 想定。しきい値を 1.5 にすれば届かない
        is_upper, score = detect_upper_mark(frame, upper_template, threshold=1.5)
        assert is_upper is False
        assert score > 0.9

    def test_roi_out_of_frame_returns_false(
        self, upper_template: np.ndarray
    ) -> None:
        small = np.zeros((100, 100, 3), dtype=np.uint8)
        is_upper, score = detect_upper_mark(small, upper_template)
        assert is_upper is False
        assert score == 0.0

    def test_template_shape_mismatch_safe_false(self) -> None:
        # テンプレを別形状で渡しても落ちず False
        bad_template = np.zeros((10, 10), dtype=np.uint8)
        x1, y1, x2, y2 = SELECT_ROI["upper_mark"]
        frame = np.zeros((768, 1366, 3), dtype=np.uint8)
        is_upper, score = detect_upper_mark(frame, bad_template)
        assert is_upper is False
        assert score == 0.0


# ---- 難易度色検出 ----


class TestDetectDifficultyColor:
    @pytest.mark.parametrize(
        "hue, expected",
        [
            (26, Difficulty.HYPER),
            (44, Difficulty.NORMAL),
            (113, Difficulty.EASY),
            (175, Difficulty.EX),
        ],
    )
    def test_center_hues(self, hue: int, expected: Difficulty) -> None:
        patch = _make_uniform_hsv_patch("difficulty_color", hue, 200, 200)
        frame = _make_frame_with_patch("difficulty_color", patch)
        assert detect_difficulty_color(frame) == expected

    @pytest.mark.parametrize(
        "hue, expected",
        [
            (15, Difficulty.HYPER),      # HYPER 中心 26 から距離 11
            (37, Difficulty.NORMAL),     # NORMAL 中心 44 から距離 7（HYPER 中心 26 からは 11）
            (56, Difficulty.NORMAL),     # NORMAL 中心 44 から距離 12（EASY 中心 113 からは遠い）
            (104, Difficulty.EASY),      # EASY 中心 113 から距離 9
            (166, Difficulty.EX),        # EX 中心 175 から距離 9
        ],
    )
    def test_tolerance_band(self, hue: int, expected: Difficulty) -> None:
        patch = _make_uniform_hsv_patch("difficulty_color", hue, 200, 200)
        frame = _make_frame_with_patch("difficulty_color", patch)
        assert detect_difficulty_color(frame) == expected

    @pytest.mark.parametrize("hue", [70, 90, 140])
    def test_unknown_hue_returns_none(self, hue: int) -> None:
        patch = _make_uniform_hsv_patch("difficulty_color", hue, 200, 200)
        frame = _make_frame_with_patch("difficulty_color", patch)
        assert detect_difficulty_color(frame) is None

    def test_low_saturation_returns_none(self) -> None:
        # 彩度不足は無彩色とみなし判定不能
        patch = _make_uniform_hsv_patch("difficulty_color", 26, 30, 200)
        frame = _make_frame_with_patch("difficulty_color", patch)
        assert detect_difficulty_color(frame) is None

    def test_roi_out_of_frame_returns_none(self) -> None:
        small = np.zeros((100, 100, 3), dtype=np.uint8)
        assert detect_difficulty_color(small) is None

    def test_ex_at_circular_boundary(self) -> None:
        # H は環状なので H=179 も EX(175)± tolerance に入る
        patch = _make_uniform_hsv_patch("difficulty_color", 179, 200, 200)
        frame = _make_frame_with_patch("difficulty_color", patch)
        assert detect_difficulty_color(frame) == Difficulty.EX


# ---- 実機サンプルでの End-to-End ----


class TestEndToEndOnSamples:
    """tests/fixtures/sample/選曲画面/ の 13 件で UPPER/難易度を再現する。"""

    @pytest.fixture
    def samples(self) -> list[Path]:
        return sorted(
            (REPO / "tests/fixtures/sample/選曲画面").glob("*.png")
        )

    UPPER_TRUTH = {
        "12-16-07", "12-16-11", "12-16-15", "12-16-18",
    }

    def _name(self, p: Path) -> str:
        return p.name.replace("Screenshot 2026-05-18 ", "").replace(".png", "")

    def test_upper_mark_on_real_samples(
        self, samples: list[Path], upper_template: np.ndarray,
    ) -> None:
        for path in samples:
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None or img.shape[:2] != (768, 1366):
                continue
            is_upper, score = detect_upper_mark(img, upper_template)
            expected = self._name(path) in self.UPPER_TRUTH
            assert is_upper is expected, (
                f"{self._name(path)}: is_upper={is_upper} (score={score:.3f}) "
                f"expected={expected}"
            )

    def test_difficulty_color_on_real_samples(
        self, samples: list[Path],
    ) -> None:
        # 実機実測 4 サンプルの真値（ユーザ提供 ROI 由来）
        expected_map = {
            "12-14-34": Difficulty.HYPER,
            "12-15-15": Difficulty.HYPER,
            "12-15-09": Difficulty.NORMAL,
            "12-15-02": Difficulty.EASY,
            "12-15-19": Difficulty.EX,
        }
        for path in samples:
            name = self._name(path)
            if name not in expected_map:
                continue
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None or img.shape[:2] != (768, 1366):
                continue
            actual = detect_difficulty_color(img)
            assert actual == expected_map[name], (
                f"{name}: got={actual} expected={expected_map[name]}"
            )
