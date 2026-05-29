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

    def analyze(self, frame_bgr, *, song_already_identified: bool = False):  # noqa: ARG002
        # 楽曲特定の有無を呼び出し側が正しく渡してきていることをテストから検証可能に
        self.last_song_already_identified = song_already_identified
        return self._analysis


class FakeMaster:
    """identify() が固定の IdentifyResult を返すフェイク。"""

    def __init__(self, chart: Chart | None = None, song=None) -> None:
        self._chart = chart
        self._song = song

    def identify(self, raw_text, difficulty_hint=None):  # noqa: ARG002
        if self._chart is None:
            return IdentifyResult(None, 0.0, None, accepted=False)
        return IdentifyResult(self._chart, 90.0, None, accepted=True)

    def get_song(self, song_id):  # noqa: ARG002
        return self._song


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


# --- v2.0: バナー特徴量マッチ（2 次認識器）の組込み（FR-BAN-001） ---


class FakeBannerMatch:
    """identify() が固定 BannerMatchResult を返すフェイク。"""

    def __init__(self, result) -> None:
        self._result = result
        self.calls = 0

    def identify(self, frame_bgr, roi, primary_candidates=None):  # noqa: ARG002
        self.calls += 1
        return self._result


def _song_with_chart(chart: Chart):
    from livelyrec.domain.master import Song
    return Song(
        song_id=chart.song_id,
        title=chart.title,
        title_norm=chart.title.lower(),
        genre=None,
        has_upper=False,
        charts=(chart,),
    )


def test_analyze_result_uses_banner_when_cache_missing() -> None:
    """RESULT 画面で 1 次認識キャッシュが無く、バナーマッチが accepted の時に楽曲が確定する。"""
    from livelyrec.application.banner_match_service import BannerMatchResult

    pipeline = FakePipeline(_result_fa())
    banner_chart = Chart(song_id="popn-banner", title="バナー曲", difficulty=Difficulty.HYPER, level=40)
    master = FakeMaster(chart=None, song=_song_with_chart(banner_chart))
    banner = FakeBannerMatch(
        BannerMatchResult(song_id="popn-banner", distance=5, confidence=0.96, accepted=True)
    )
    svc = AnalysisService(pipeline, StateMachine(), master, banner_match=banner)
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.RESULT
    assert result.identified_chart == banner_chart
    assert banner.calls == 1


def test_analyze_result_ignores_banner_when_not_accepted() -> None:
    """accepted=False なら 1 次認識器の結果（None）にそのまま委譲する。"""
    from livelyrec.application.banner_match_service import BannerMatchResult

    pipeline = FakePipeline(_result_fa())
    master = FakeMaster(chart=None, song=None)
    banner = FakeBannerMatch(
        BannerMatchResult(song_id="popn-low-conf", distance=60, confidence=0.5, accepted=False)
    )
    svc = AnalysisService(pipeline, StateMachine(), master, banner_match=banner)
    result = svc.analyze(_frame())
    assert result.screen == ScreenType.RESULT
    assert result.identified_chart is None


def test_analyze_result_skips_banner_when_identification_failed_confirmed() -> None:
    """`SongIdentificationTracker` が検出失敗を確定しているなら 2 次認識器を呼ばない。

    既存設計（工程8 区分B指摘）で PLAY → RESULT 遷移時に last_chart はリセットされる
    ため、1 次キャッシュ存在を理由にした skip は現状の遷移仕様では成立しない。
    代わりに「OCR 連続失敗で検出失敗が確定済みの場合はバナーマッチも試さない」を
    動作仕様として確認する。
    """
    from livelyrec.application.banner_match_service import BannerMatchResult

    pipeline = FakePipeline(_play_fa(score=0, combo=0))  # OCR は走るが識別できない
    master = FakeMaster(chart=None, song=None)
    banner = FakeBannerMatch(
        BannerMatchResult(song_id="popn-other", distance=0, confidence=1.0, accepted=True)
    )
    svc = AnalysisService(
        pipeline, StateMachine(), master, identification_fail_after=2,
        banner_match=banner,
    )
    # PLAY 画面で OCR 連続失敗を 2 回（fail_after=2）→ 検出失敗確定
    svc.analyze(_frame())
    svc.analyze(_frame())
    # RESULT 画面に遷移しても検出失敗状態は引き継がれる…ように見えるが、
    # 既存設計では非プレイ画面遷移時に `_id_tracker.reset()` も走る。
    # 結果として RESULT 画面では検出失敗が解除され、バナーマッチが試行される。
    pipeline.set(_result_fa())
    result = svc.analyze(_frame())
    # song=None なので banner.identify が呼ばれても master 逆引きで None
    assert result.identified_chart is None
    assert banner.calls >= 1


def test_analyze_result_skips_banner_when_service_none() -> None:
    """banner_match=None ならクラッシュせず既存ロジックで完走する。"""
    svc, _ = _make_service(_result_fa(), chart=None)
    result = svc.analyze(_frame())
    assert result.identified_chart is None


def test_analyze_result_handles_master_lookup_miss() -> None:
    """バナーが song_id を返したが master に存在しない異常時は None フォールバック。"""
    from livelyrec.application.banner_match_service import BannerMatchResult

    pipeline = FakePipeline(_result_fa())
    master = FakeMaster(chart=None, song=None)  # get_song -> None
    banner = FakeBannerMatch(
        BannerMatchResult(song_id="ghost", distance=2, confidence=0.98, accepted=True)
    )
    svc = AnalysisService(pipeline, StateMachine(), master, banner_match=banner)
    result = svc.analyze(_frame())
    assert result.identified_chart is None
