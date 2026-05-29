"""BannerMatchService の単体テスト（FR-BAN-001, §5.3 しきい値境界）。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from livelyrec.application.banner_match_service import (
    DEFAULT_ACCEPT_THRESHOLD,
    DEFAULT_CANDIDATE_THRESHOLD,
    BannerFeature,
    BannerFeaturesLoadError,
    BannerMatchResult,
    BannerMatchService,
)
from livelyrec.infrastructure.banner_features import (
    DEFAULT_TARGET_SIZE,
    dhash64,
    hex_from_hash,
    phash64,
    prepare_gray,
)


def _make_frame_with_banner(
    banner: np.ndarray,
    frame_size: tuple[int, int] = (1366, 768),
    roi: tuple[int, int, int, int] = (489, 233, 879, 327),
) -> np.ndarray:
    """1366×768 フレームの ROI にバナーを貼り込む。"""
    w, h = frame_size
    frame = np.full((h, w, 3), 64, dtype=np.uint8)
    x1, y1, x2, y2 = roi
    resized = cv2.resize(banner, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = resized
    return frame


def _gradient_banner(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w, h = DEFAULT_TARGET_SIZE
    gradient = np.linspace(0, 255, w * h, dtype=np.uint8).reshape(h, w)
    noise = rng.integers(0, 32, size=(h, w), dtype=np.uint8)
    gray = cv2.add(gradient, noise)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _feature_from_banner(song_id: str, banner: np.ndarray) -> BannerFeature:
    gray = cv2.cvtColor(
        cv2.resize(banner, DEFAULT_TARGET_SIZE, interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY,
    )
    return BannerFeature(
        song_id=song_id, phash=phash64(gray), dhash=dhash64(gray), src=()
    )


@pytest.fixture
def roi() -> tuple[int, int, int, int]:
    return (489, 233, 879, 327)


@pytest.fixture
def banner_a() -> np.ndarray:
    return _gradient_banner(seed=11)


@pytest.fixture
def banner_b() -> np.ndarray:
    return _gradient_banner(seed=22)


@pytest.fixture
def feat_a(banner_a: np.ndarray) -> BannerFeature:
    return _feature_from_banner("song-a", banner_a)


@pytest.fixture
def feat_b(banner_b: np.ndarray) -> BannerFeature:
    return _feature_from_banner("song-b", banner_b)


class TestIdentify:
    def test_returns_none_when_features_empty(
        self, banner_a: np.ndarray, roi: tuple[int, int, int, int]
    ) -> None:
        svc = BannerMatchService(features=[])
        frame = _make_frame_with_banner(banner_a, roi=roi)
        assert svc.identify(frame, roi) is None

    def test_returns_none_when_roi_out_of_frame(
        self, feat_a: BannerFeature
    ) -> None:
        svc = BannerMatchService(features=[feat_a])
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        assert svc.identify(frame, (0, 0, 200, 200)) is None

    def test_accepts_when_distance_is_zero(
        self,
        feat_a: BannerFeature,
        feat_b: BannerFeature,
        banner_a: np.ndarray,
        roi: tuple[int, int, int, int],
    ) -> None:
        svc = BannerMatchService(features=[feat_a, feat_b])
        frame = _make_frame_with_banner(banner_a, roi=roi)
        result = svc.identify(frame, roi)
        assert result is not None
        assert result.song_id == "song-a"
        # ROI クロップ + リサイズ後の特徴量は登録時と一致する想定
        assert result.distance == 0
        assert result.accepted is True
        assert result.confidence == pytest.approx(1.0)

    def test_returns_best_match_object(
        self,
        feat_a: BannerFeature,
        feat_b: BannerFeature,
        banner_a: np.ndarray,
        roi: tuple[int, int, int, int],
    ) -> None:
        svc = BannerMatchService(features=[feat_a, feat_b])
        frame = _make_frame_with_banner(banner_a, roi=roi)
        result = svc.identify(frame, roi)
        assert isinstance(result, BannerMatchResult)


class TestThresholdBoundary:
    """しきい値境界（accept=20, candidate=40）の動作。"""

    def _build_with_distance(self, distance: int) -> tuple[BannerMatchService, np.ndarray, tuple[int, int, int, int]]:
        """指定距離になるように feature と入力を組み立てる。"""
        roi = (489, 233, 879, 327)
        banner = _gradient_banner(seed=99)
        gray = prepare_gray(_make_frame_with_banner(banner, roi=roi), roi)
        assert gray is not None
        q_phash = phash64(gray)
        q_dhash = dhash64(gray)
        # 指定 distance を pHash 側に乗せる（低位ビットを反転）
        flip_mask = 0
        for i in range(min(distance, 64)):
            flip_mask |= 1 << i
        feat = BannerFeature(
            song_id="target",
            phash=q_phash ^ flip_mask,
            dhash=q_dhash,
            src=(),
        )
        svc = BannerMatchService(features=[feat])
        frame = _make_frame_with_banner(banner, roi=roi)
        return svc, frame, roi

    def test_accept_at_boundary_inclusive(self) -> None:
        svc, frame, roi = self._build_with_distance(DEFAULT_ACCEPT_THRESHOLD)
        result = svc.identify(frame, roi)
        assert result is not None
        assert result.distance == DEFAULT_ACCEPT_THRESHOLD
        assert result.accepted is True

    def test_reject_just_above_accept(self) -> None:
        svc, frame, roi = self._build_with_distance(DEFAULT_ACCEPT_THRESHOLD + 1)
        result = svc.identify(frame, roi)
        assert result is not None
        assert result.distance == DEFAULT_ACCEPT_THRESHOLD + 1
        assert result.accepted is False

    def test_accept_in_candidate_band_when_primary_overlaps(self) -> None:
        svc, frame, roi = self._build_with_distance(DEFAULT_ACCEPT_THRESHOLD + 5)
        result = svc.identify(frame, roi, primary_candidates=["target"])
        assert result is not None
        assert result.accepted is True

    def test_reject_in_candidate_band_when_primary_disjoint(self) -> None:
        svc, frame, roi = self._build_with_distance(DEFAULT_ACCEPT_THRESHOLD + 5)
        result = svc.identify(frame, roi, primary_candidates=["someone-else"])
        assert result is not None
        assert result.accepted is False

    def test_reject_above_candidate_even_with_primary_match(self) -> None:
        svc, frame, roi = self._build_with_distance(DEFAULT_CANDIDATE_THRESHOLD + 1)
        result = svc.identify(frame, roi, primary_candidates=["target"])
        assert result is not None
        assert result.accepted is False


class TestConstructorValidation:
    def test_invalid_accept_threshold(self) -> None:
        with pytest.raises(ValueError):
            BannerMatchService(features=[], accept_threshold=-1)
        with pytest.raises(ValueError):
            BannerMatchService(features=[], accept_threshold=129)

    def test_candidate_must_be_at_least_accept(self) -> None:
        with pytest.raises(ValueError):
            BannerMatchService(
                features=[], accept_threshold=30, candidate_threshold=20
            )


class TestFromJson:
    def _make_json(
        self,
        tmp_path: Path,
        features: list[BannerFeature],
        schema_version: int = 1,
        target_size: tuple[int, int] = DEFAULT_TARGET_SIZE,
    ) -> Path:
        doc = {
            "version": "2026-05-29T00:00:00Z",
            "schema_version": schema_version,
            "target_size": list(target_size),
            "songs": [
                {
                    "song_id": f.song_id,
                    "phash": hex_from_hash(f.phash),
                    "dhash": hex_from_hash(f.dhash),
                    "src": list(f.src),
                }
                for f in features
            ],
        }
        path = tmp_path / "banner_features.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_load_round_trip(
        self, tmp_path: Path, feat_a: BannerFeature, feat_b: BannerFeature
    ) -> None:
        path = self._make_json(tmp_path, [feat_a, feat_b])
        svc = BannerMatchService.from_json(path)
        assert svc.feature_count == 2
        assert svc.target_size == DEFAULT_TARGET_SIZE

    def test_unsupported_schema_version_raises(
        self, tmp_path: Path, feat_a: BannerFeature
    ) -> None:
        path = self._make_json(tmp_path, [feat_a], schema_version=99)
        with pytest.raises(BannerFeaturesLoadError):
            BannerMatchService.from_json(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(BannerFeaturesLoadError):
            BannerMatchService.from_json(tmp_path / "nonexistent.json")

    def test_skips_malformed_entries(
        self, tmp_path: Path, feat_a: BannerFeature
    ) -> None:
        doc = {
            "schema_version": 1,
            "target_size": list(DEFAULT_TARGET_SIZE),
            "songs": [
                {
                    "song_id": feat_a.song_id,
                    "phash": hex_from_hash(feat_a.phash),
                    "dhash": hex_from_hash(feat_a.dhash),
                },
                {"song_id": "broken"},  # phash/dhash 欠落 → skip
                {"song_id": "bad-hex", "phash": "deadbeef", "dhash": "0x0"},  # prefix 不正
            ],
        }
        path = tmp_path / "banner_features.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        svc = BannerMatchService.from_json(path)
        assert svc.feature_count == 1


class TestReload:
    def test_reload_replaces_features(
        self,
        tmp_path: Path,
        feat_a: BannerFeature,
        feat_b: BannerFeature,
    ) -> None:
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        path_a.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "target_size": list(DEFAULT_TARGET_SIZE),
                    "songs": [
                        {
                            "song_id": feat_a.song_id,
                            "phash": hex_from_hash(feat_a.phash),
                            "dhash": hex_from_hash(feat_a.dhash),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        path_b.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "target_size": list(DEFAULT_TARGET_SIZE),
                    "songs": [
                        {
                            "song_id": f.song_id,
                            "phash": hex_from_hash(f.phash),
                            "dhash": hex_from_hash(f.dhash),
                        }
                        for f in (feat_a, feat_b)
                    ],
                }
            ),
            encoding="utf-8",
        )
        svc = BannerMatchService.from_json(path_a)
        assert svc.feature_count == 1
        n = svc.reload(path_b)
        assert n == 2
        assert svc.feature_count == 2
