"""画面分析サービス。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §3.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from livelyrec.domain.score import Chart, Judgements
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline
from livelyrec.infrastructure.recognizer.retry_detector import (
    PlayFrameSnapshot,
    RetryDetector,
)

from .master_service import MasterService, SongStabilizer

logger = logging.getLogger("livelyrec.analysis")


@dataclass
class AnalysisResult:
    screen: ScreenType
    confidence: float
    raw_song_text: str | None = None
    identified_chart: Chart | None = None
    # プレイ画面のメトリクス
    play_score: int | None = None
    play_combo: int | None = None
    play_judgements: Judgements | None = None  # プレイ画面下部の判定数累計（FR-REC-034）
    retry_detected: bool = False
    # リザルト画面のメトリクス
    result_score: int | None = None
    result_combo: int | None = None
    result_judgements: Judgements | None = None
    result_clear_type: str | None = None


class AnalysisService:
    """1フレームの認識結果をドメイン層と擦り合わせるサービス。"""

    def __init__(
        self,
        pipeline: RecognitionPipeline,
        state_machine: StateMachine,
        master: MasterService,
    ) -> None:
        self._pipeline = pipeline
        self._state = state_machine
        self._master = master
        self._retry = RetryDetector(window=5)
        self._song_stab = SongStabilizer(window=7, min_majority=0.5)
        self._last_chart: Chart | None = None

    def analyze(self, frame_bgr: np.ndarray) -> AnalysisResult:
        # 楽曲特定済みなら楽曲名 OCR をスキップしてプレイ中の連続 OCR 呼び出し
        # を最小化する（PaddleOCR ネイティブ層の access violation 対策、I-027）。
        analysis = self._pipeline.analyze(
            frame_bgr, song_already_identified=self._last_chart is not None
        )
        screen = analysis.detection.screen
        accepted = self._state.transition(screen)
        if not accepted:
            # 状態が確定していない場合は detection.screen ではなく状態マシン側を採用
            screen = self._state.current

        if screen != ScreenType.PLAY:
            # 楽曲外画面では特定状態をリセットし、次の楽曲を新規に認識し直す。
            # これをしないと前楽曲の特定結果が持ち越され、スコアが1つ前の
            # 楽曲に紐づいて記録される（工程8 区分B指摘）。
            self._song_stab.reset()
            self._last_chart = None

        if screen == ScreenType.PLAY and analysis.play_metrics is not None:
            pm = analysis.play_metrics
            # 楽曲特定（難易度バッジのテーマ色をヒントに正しい譜面を選ぶ）
            id_result = self._master.identify(
                pm.raw_song_text, difficulty_hint=pm.difficulty
            )
            chart_id = id_result.chart.chart_id if id_result.chart else None
            stable_id = self._song_stab.push(chart_id)
            if (
                stable_id is not None
                and chart_id == stable_id
                and (self._last_chart is None or self._last_chart.chart_id != stable_id)
            ):
                # 多数決で安定し、かつ今フレームの特定が安定値と一致したら更新
                self._last_chart = id_result.chart

            # リトライ検出
            snap = PlayFrameSnapshot(
                score=pm.score, cool=None, great=None, good=None, bad=None,
                combo=pm.combo,
            )
            retry = self._retry.push(snap)

            return AnalysisResult(
                screen=screen,
                confidence=analysis.detection.confidence,
                raw_song_text=pm.raw_song_text,
                identified_chart=self._last_chart,
                play_score=pm.score,
                play_combo=pm.combo,
                play_judgements=pm.judgements,
                retry_detected=retry,
            )

        if screen == ScreenType.RESULT and analysis.result_metrics is not None:
            rm = analysis.result_metrics
            return AnalysisResult(
                screen=screen,
                confidence=analysis.detection.confidence,
                identified_chart=self._last_chart,
                result_score=rm.score,
                result_combo=rm.combo,
                result_judgements=rm.judgements,
                result_clear_type=rm.clear_type.value if rm.clear_type else None,
            )

        # その他画面: 楽曲・状態のみ
        return AnalysisResult(
            screen=screen,
            confidence=analysis.detection.confidence,
            identified_chart=self._last_chart,
        )

    def reset(self) -> None:
        self._state.reset()
        self._retry.reset()
        self._song_stab.reset()
        self._last_chart = None
