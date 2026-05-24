"""AnalysisService のテスト。

画面分析サービスが、認識パイプラインの出力を状態マシン・楽曲特定・
リトライ検出と擦り合わせて AnalysisResult を返すことを検証する。
パイプライン／マスタはフェイクで差し替える。
"""

from __future__ import annotations

import numpy as np

from livelyrec.application.analysis_service import AnalysisService
from livelyrec.application.master_service import IdentifyResult
from livelyrec.domain.score import Chart, ClearType, Difficulty, Judgements
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.recognizer.extractors import PlayMetrics, ResultMetrics
from livelyrec.infrastructure.recognizer.normalize import NormalizedFrame
from livelyrec.infrastructure.recognizer.pipeline import FrameAnalysis
from livelyrec.infrastructure.recognizer.screen_detector import ScreenDetection

_CHART = Chart(song_id="popn-1", title="テスト楽曲", difficulty=Difficulty.HYPER, level=36)


def _frame() -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


def _norm() -> NormalizedFrame:
    return NormalizedFrame(image_bgr=_frame(), original_size=(1366, 768), aspect_ratio=1.778)


class FakePipeline:
    """analyze() が設定済みの FrameAnalysis を返すフェイク。"""

    def __init__(self, analysis: FrameAnalysis) -> None:
        self._analysis = analysis

    def set(self, analysis: FrameAnalysis) -> None:
        self._analysis = analysis

    def analyze(self, frame_bgr):  # noqa: ARG002
        return self._analysis


class FakeMaster:
    """identify() が固定の IdentifyResult を返すフェイク。"""

    def __init__(self, chart: Chart | None = None) -> None:
        self._chart = chart

    def identify(self, raw_text, difficulty_hint=None):  # noqa: ARG002
        if self._chart is None:
            return IdentifyResult(None, 0.0, None, accepted=False)
        return IdentifyResult(self._chart, 90.0, None, accepted=True)


def _play_fa(score, combo, screen=ScreenType.PLAY) -> FrameAnalysis:
    return FrameAnalysis(
        frame=_norm(),
        detection=ScreenDetection(screen, 0.9, {}),
        play_metrics=PlayMetrics(
            raw_song_text="テスト楽曲", song_confidence=0.9, score=score, combo=combo
        ),
        result_metrics=None,
    )


def _result_fa() -> FrameAnalysis:
    return FrameAnalysis(
        frame=_norm(),
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


def _make_service(fa: FrameAnalysis, chart: Chart | None = _CHART) -> tuple:
    pipeline = FakePipeline(fa)
    svc = AnalysisService(pipeline, StateMachine(), FakeMaster(chart))
    return svc, pipeline


def test_analyze_play_returns_metrics_and_chart() -> None:
    svc, _ = _make_service(_play_fa(score=5000, combo=100))
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.PLAY
    assert result.play_score == 5000
    assert result.play_combo == 100
    # SongStabilizer は初回 push（1/1）で確定するため、譜面が即特定される
    assert result.identified_chart == _CHART


def test_analyze_play_without_chart_match() -> None:
    svc, _ = _make_service(_play_fa(score=1000, combo=10), chart=None)
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.PLAY
    assert result.identified_chart is None


def test_analyze_result_returns_result_metrics() -> None:
    svc, _ = _make_service(_result_fa())
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.RESULT
    assert result.result_score == 87268
    assert result.result_combo == 329
    assert result.result_judgements == Judgements(312, 18, 5, 2)
    assert result.result_clear_type == "CLEAR"


def test_analyze_detects_retry() -> None:
    svc, pipeline = _make_service(_play_fa(score=8000, combo=200))
    first = svc.analyze(_frame())
    assert first.retry_detected is False
    # 同じプレイ画面で全メトリクスが 0 にリセット → リトライ
    pipeline.set(_play_fa(score=0, combo=0))
    second = svc.analyze(_frame())
    assert second.retry_detected is True


def test_analyze_other_screen_returns_screen_only() -> None:
    fa = FrameAnalysis(
        frame=_norm(),
        detection=ScreenDetection(ScreenType.SELECT, 0.8, {}),
        play_metrics=None,
        result_metrics=None,
    )
    svc, _ = _make_service(fa)
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.SELECT
    assert result.play_score is None
    assert result.result_score is None


def test_analyze_play_screen_without_metrics_returns_generic() -> None:
    # detection は PLAY だが play_metrics 欠落 → 汎用 result にフォールバック
    fa = FrameAnalysis(
        frame=_norm(),
        detection=ScreenDetection(ScreenType.PLAY, 0.7, {}),
        play_metrics=None,
        result_metrics=None,
    )
    svc, _ = _make_service(fa)
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.PLAY
    assert result.play_score is None


def test_analyze_invalid_transition_keeps_current_state() -> None:
    svc, pipeline = _make_service(_play_fa(score=100, combo=1))
    svc.analyze(_frame())  # UNKNOWN -> PLAY 確定
    # PLAY -> SELECT は不正遷移。状態マシンが棄却し screen は PLAY のまま
    pipeline.set(
        FrameAnalysis(
            frame=_norm(),
            detection=ScreenDetection(ScreenType.SELECT, 0.6, {}),
            play_metrics=None,
            result_metrics=None,
        )
    )
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.PLAY


def test_analyze_resets_chart_on_non_play_screen() -> None:
    # プレイ画面で楽曲確定後、非プレイ画面に出ると特定状態がリセットされ、
    # 前楽曲の譜面が次楽曲へ持ち越されない（工程8 区分B指摘の修正）。
    svc, pipeline = _make_service(_play_fa(score=4000, combo=80))
    assert svc.analyze(_frame()).identified_chart == _CHART
    # PLAY -> RESULT は妥当遷移。非プレイ画面なので last_chart はリセットされる
    pipeline.set(_result_fa())
    assert svc.analyze(_frame()).identified_chart is None


def test_reset_clears_state_and_chart() -> None:
    svc, pipeline = _make_service(_play_fa(score=4000, combo=80))
    svc.analyze(_frame())  # last_chart を確定させる
    svc.reset()
    # reset 後は last_chart が無いので、他画面では identified_chart=None
    pipeline.set(
        FrameAnalysis(
            frame=_norm(),
            detection=ScreenDetection(ScreenType.SELECT, 0.8, {}),
            play_metrics=None,
            result_metrics=None,
        )
    )
    result = svc.analyze(_frame())
    assert result.identified_chart is None
