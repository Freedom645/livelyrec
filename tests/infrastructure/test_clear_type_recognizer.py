"""clear_type_recognizer の単体テスト（リザルト画面クリアタイプ判定）。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from livelyrec.domain.score import ClearType
from livelyrec.infrastructure.recognizer.clear_type_recognizer import (
    DEFAULT_CLEAR_TYPE_MATCH_THRESHOLD,
    detect_clear_type,
    load_clear_type_templates,
)

REPO = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO / "templates" / "result" / "clear_type"


@pytest.fixture
def templates() -> dict[ClearType, np.ndarray]:
    return load_clear_type_templates(TEMPLATE_DIR)


class TestLoadTemplates:
    def test_loads_available_templates(self, templates: dict) -> None:
        # 4 種すべて同梱（2026-05-31 FULL_COMBO 追加）
        assert ClearType.FAILED in templates
        assert ClearType.CLEAR in templates
        assert ClearType.FULL_COMBO in templates
        assert ClearType.PERFECT in templates

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        result = load_clear_type_templates(tmp_path / "does_not_exist")
        assert result == {}


class TestDetectClearType:
    def test_self_match_returns_each_type(
        self, templates: dict[ClearType, np.ndarray]
    ) -> None:
        """各テンプレ自身を入力に渡せばその ClearType が返る。"""
        for ct, tpl in templates.items():
            got = detect_clear_type(tpl, templates)
            assert got == ct, f"{ct}: expected {ct.value}, got {got}"

    def test_empty_templates_returns_none(self) -> None:
        roi = np.zeros((31, 286, 3), dtype=np.uint8)
        assert detect_clear_type(roi, {}) is None

    def test_below_threshold_returns_none(
        self, templates: dict[ClearType, np.ndarray]
    ) -> None:
        """無関係な真っ黒画像はテンプレと相関しないため None。"""
        roi = np.zeros((31, 286, 3), dtype=np.uint8)
        assert detect_clear_type(roi, templates) is None

    def test_resize_handles_shape_mismatch(
        self, templates: dict[ClearType, np.ndarray]
    ) -> None:
        """テンプレと ROI のサイズが違っても自動リサイズで動作。"""
        # 既存テンプレを別サイズにして渡す（テンプレ側より小さい）
        tpl = templates[ClearType.FAILED]
        roi_resized = cv2.resize(
            tpl, (143, 16), interpolation=cv2.INTER_AREA
        )  # 半分サイズ
        got = detect_clear_type(roi_resized, templates)
        # 内部でテンプレサイズに戻すため、依然として FAILED を最も近いものと
        # 判定するはず（ただしスコアは下がるためしきい値で None になる可能性）
        assert got is None or got == ClearType.FAILED

    def test_threshold_argument(
        self, templates: dict[ClearType, np.ndarray]
    ) -> None:
        """threshold パラメータで判定厳しさを変更できる。"""
        roi = np.zeros((31, 286, 3), dtype=np.uint8)
        # 極めて緩いしきい値なら None ではなく最も近いものが返る
        got = detect_clear_type(roi, templates, threshold=-2.0)
        assert got is not None

    def test_default_threshold_is_05(self) -> None:
        assert DEFAULT_CLEAR_TYPE_MATCH_THRESHOLD == 0.5


class TestEndToEndOnSamples:
    """既存リザルト画面サンプルでの動作確認（PoC #04 結果と整合）。"""

    @pytest.fixture
    def sample_files(self) -> dict[str, str]:
        # サンプル名 → 想定 ClearType（目視確認による）
        return {
            "Screenshot 2026-05-18 12-20-06.png": ClearType.FAILED,  # ぽぽぽかレトロード Failed
            "Screenshot 2026-05-18 12-23-54.png": ClearType.FAILED,  # 同
            "Screenshot 2026-05-18 12-28-30.png": ClearType.FAILED,  # 同
            "Screenshot 2026-05-18 12-22-44.png": ClearType.CLEAR,   # 漆黒のスペシャル… Clear
            "Screenshot 2026-05-18 12-27-52.png": ClearType.CLEAR,
        }

    def test_real_samples(
        self,
        templates: dict[ClearType, np.ndarray],
        sample_files: dict[str, ClearType],
    ) -> None:
        from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI

        sample_dir = REPO / "tests/fixtures/sample/リザルト画面"
        x1, y1, x2, y2 = RESULT_ROI["clear_label"]
        for filename, expected in sample_files.items():
            path = sample_dir / filename
            if not path.exists():
                pytest.skip(f"sample not found: {filename}")
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            assert img is not None
            roi = img[y1:y2, x1:x2]
            got = detect_clear_type(roi, templates)
            assert got == expected, (
                f"{filename}: expected {expected.value}, got "
                f"{got.value if got else 'None'}"
            )
