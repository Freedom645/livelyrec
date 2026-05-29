"""IT-BAN: バナー特徴量マッチ（2 次認識器）の結合テスト。

詳細: docs/design/11_詳細設計_バナー認識.md §9.2

- IT-BAN-01: RESULT 画面サンプル → ROI 切り出し → BannerMatchService.identify が
  登録済み特徴量を Top-1 として返し、AnalysisService 経由で楽曲が確定する
- IT-BAN-02: SELECT 画面組込みは v2.0 スコープ外（詳細設計 §13.2 で未確定）。
  代わりに「同一フレームに対する複数回 identify が決定論的」を確認
- IT-BAN-03: BannerFeaturesFetcher 失敗時に `_build_banner_match_service` が
  None を返し、AnalysisService が banner_match=None で起動できる（1 次認識器
  のみで完走可能）
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from livelyrec.application.analysis_service import AnalysisService
from livelyrec.application.banner_match_service import (
    BannerFeaturesLoadError,
    BannerMatchService,
)
from livelyrec.application.master_service import IdentifyResult
from livelyrec.domain.master import Song
from livelyrec.domain.score import Chart, ClearType, Difficulty, Judgements
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.banner_features import (
    DEFAULT_TARGET_SIZE,
    dhash64,
    hex_from_hash,
    phash64,
)
from livelyrec.infrastructure.recognizer.extractors import ResultMetrics
from livelyrec.infrastructure.recognizer.normalize import NormalizedFrame
from livelyrec.infrastructure.recognizer.pipeline import FrameAnalysis
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI
from livelyrec.infrastructure.recognizer.screen_detector import ScreenDetection
from livelyrec.shared.exceptions import BannerFeaturesFetchError

pytestmark = pytest.mark.integration


# ---- 補助 ----


def _make_test_banner(seed: int) -> np.ndarray:
    """テスト用バナー画像（390×94 BGR）を決定論的に生成する。"""
    rng = np.random.default_rng(seed)
    w, h = DEFAULT_TARGET_SIZE
    gradient = np.linspace(0, 255, w * h, dtype=np.uint8).reshape(h, w)
    noise = rng.integers(0, 64, size=(h, w), dtype=np.uint8)
    gray = cv2.add(gradient, noise)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _make_result_frame_with_banner(banner: np.ndarray) -> np.ndarray:
    """1366×768 RESULT フレームの banner ROI に指定バナーを貼り込む。"""
    frame = np.full((768, 1366, 3), 32, dtype=np.uint8)
    x1, y1, x2, y2 = RESULT_ROI["banner"]
    resized = cv2.resize(banner, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = resized
    return frame


def _write_features_json(path: Path, songs: list[dict]) -> None:
    doc = {
        "version": "2026-05-29T00:00:00Z",
        "schema_version": 1,
        "target_size": list(DEFAULT_TARGET_SIZE),
        "songs": songs,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _feature_dict_from_banner(song_id: str, banner: np.ndarray) -> dict:
    resized = cv2.resize(banner, DEFAULT_TARGET_SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return {
        "song_id": song_id,
        "phash": hex_from_hash(phash64(gray)),
        "dhash": hex_from_hash(dhash64(gray)),
        "src": ["test:fixture"],
    }


def _result_fa() -> FrameAnalysis:
    return FrameAnalysis(
        frame=NormalizedFrame(
            image_bgr=np.zeros((10, 10, 3), dtype=np.uint8),
            original_size=(1366, 768),
            aspect_ratio=1.778,
        ),
        detection=ScreenDetection(ScreenType.RESULT, 0.95, {}),
        play_metrics=None,
        result_metrics=ResultMetrics(
            clear_type=ClearType.CLEAR,
            score=87268,
            judgements=Judgements(312, 18, 5, 2),
            combo=329,
            best_score_diff=120,
        ),
    )


class _FakePipeline:
    def __init__(self, fa: FrameAnalysis) -> None:
        self._fa = fa

    def analyze(self, frame_bgr, *, song_already_identified: bool = False):  # noqa: ARG002
        return self._fa


class _FakeMaster:
    def __init__(self, song: Song | None) -> None:
        self._song = song

    def identify(self, raw_text, difficulty_hint=None):  # noqa: ARG002
        return IdentifyResult(None, 0.0, None, accepted=False)

    def get_song(self, song_id):  # noqa: ARG002
        return self._song


def _song_with_chart(chart: Chart) -> Song:
    return Song(
        song_id=chart.song_id,
        title=chart.title,
        title_norm=chart.title.lower(),
        genre=None,
        has_upper=False,
        charts=(chart,),
    )


# ---- IT-BAN-01: RESULT 画面 → 楽曲特定（フルフロー） ----


def test_it_ban_01_result_frame_identifies_song_via_banner(tmp_path: Path) -> None:
    """RESULT 画面サンプルフレームから、特徴量マスタ経由で楽曲が特定される。

    `data/banner_features.json` 相当の JSON を一時生成 → BannerMatchService に
    ロード → 該当バナーを ROI に持つ RESULT フレームを `AnalysisService.analyze`
    に流し、`identified_chart` に登録楽曲が乗ることを確認する。
    """
    banner = _make_test_banner(seed=101)
    features_path = tmp_path / "banner_features.json"
    _write_features_json(features_path, [_feature_dict_from_banner("popn-it01", banner)])

    svc = BannerMatchService.from_json(features_path)
    assert svc.feature_count == 1

    chart = Chart(
        song_id="popn-it01", title="IT-BAN-01 song",
        difficulty=Difficulty.HYPER, level=40,
    )
    master = _FakeMaster(song=_song_with_chart(chart))
    pipeline = _FakePipeline(_result_fa())
    analysis = AnalysisService(
        pipeline, StateMachine(), master, banner_match=svc
    )

    frame = _make_result_frame_with_banner(banner)
    result = analysis.analyze(frame)

    assert result.screen == ScreenType.RESULT
    assert result.identified_chart is not None
    assert result.identified_chart.song_id == "popn-it01"


# ---- IT-BAN-02: 同一入力に対する決定論性（v2.0 SELECT 未組込み代替） ----


def test_it_ban_02_same_frame_yields_same_match(tmp_path: Path) -> None:
    """SELECT 画面組込みは v2.0 スコープ外（詳細設計 §13.2）。

    代替として、同一フレームを連続して identify した際の結果が決定論的に
    一致することを確認する（多数決ロジックの前提条件）。
    """
    banner_a = _make_test_banner(seed=201)
    banner_b = _make_test_banner(seed=202)
    features_path = tmp_path / "banner_features.json"
    _write_features_json(
        features_path,
        [
            _feature_dict_from_banner("popn-a", banner_a),
            _feature_dict_from_banner("popn-b", banner_b),
        ],
    )
    svc = BannerMatchService.from_json(features_path)

    frame = _make_result_frame_with_banner(banner_a)
    results = [svc.identify(frame, RESULT_ROI["banner"]) for _ in range(5)]
    assert all(r is not None for r in results)
    song_ids = {r.song_id for r in results}  # type: ignore[union-attr]
    distances = {r.distance for r in results}  # type: ignore[union-attr]
    assert song_ids == {"popn-a"}
    assert distances == {0}


# ---- IT-BAN-03: 取得失敗時のフォールバック ----


def test_it_ban_03_fetch_failure_falls_back_to_none(
    tmp_path: Path, monkeypatch
) -> None:
    """`_build_banner_match_service` 相当: 取得失敗かつ seed 不在のとき
    `BannerMatchService` は組み立てられず、AnalysisService は banner_match=None
    で起動できる（1 次認識器のみで完走可能）。
    """
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(BannerFeaturesLoadError):
        BannerMatchService.from_json(missing)

    # 上の例外を呼び出し側が捕捉 → banner_match=None でサービスを構築
    pipeline = _FakePipeline(_result_fa())
    master = _FakeMaster(song=None)
    analysis = AnalysisService(
        pipeline, StateMachine(), master, banner_match=None
    )
    result = analysis.analyze(_make_result_frame_with_banner(_make_test_banner(seed=301)))
    # 1 次認識器も特定不能なので未確定。重要なのは「クラッシュせず完走する」こと
    assert result.screen == ScreenType.RESULT
    assert result.identified_chart is None


def test_it_ban_03_fetch_error_is_distinct_exception() -> None:
    """BannerFeaturesFetchError は LivelyRecError 階層の独立例外として
    呼び出し側で識別可能（_build_banner_match_service のフォールバック判定用）。
    """
    from livelyrec.shared.exceptions import LivelyRecError

    err = BannerFeaturesFetchError("HTTP 503")
    assert isinstance(err, LivelyRecError)
    assert str(err) == "HTTP 503"
