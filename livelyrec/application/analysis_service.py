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
    # 楽曲名 OCR は走ったが特定不能（連続失敗で確定済み、FR-REC-039）。
    # 真のときは chart_id=NULL の検出失敗セッションを作成する。
    # 偽のときの identified_chart=None は「まだ判定が走っていない」状態。
    song_identification_failed: bool = False
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


class SongIdentificationTracker:
    """プレイ画面で楽曲名 OCR が連続失敗した時点で「検出失敗確定」とする。

    詳細: docs/design/10_詳細設計_画像認識.md §6.4

    - I-027 対応で楽曲名 OCR はプレイ開始直後の数フレームに限定される。
      `record_attempt(None)` が `fail_after` 回連続して呼ばれたら確定する。
    - 一度確定したら同じプレイ中は再試行しない（OCR 呼び出し回数の抑制）。
    - 新しいプレイ画面に入る／楽曲が特定されたら `reset()` で初期化する。
    """

    def __init__(self, fail_after: int = 5) -> None:
        self._fail_after = fail_after
        self._fail_streak = 0
        self._confirmed = False

    def record_attempt(self, identified: Chart | None) -> None:
        if self._confirmed:
            return
        if identified is None:
            self._fail_streak += 1
            if self._fail_streak >= self._fail_after:
                self._confirmed = True
        else:
            self._fail_streak = 0

    def is_confirmed_failed(self) -> bool:
        return self._confirmed

    def reset(self) -> None:
        self._fail_streak = 0
        self._confirmed = False


class AnalysisService:
    """1フレームの認識結果をドメイン層と擦り合わせるサービス。"""

    def __init__(
        self,
        pipeline: RecognitionPipeline,
        state_machine: StateMachine,
        master: MasterService,
        identification_fail_after: int = 5,
    ) -> None:
        self._pipeline = pipeline
        self._state = state_machine
        self._master = master
        self._retry = RetryDetector(window=5)
        self._song_stab = SongStabilizer(window=7, min_majority=0.5)
        self._last_chart: Chart | None = None
        self._last_raw_song_text: str | None = None
        # 楽曲名 OCR の連続失敗を観測して「検出失敗」を確定させる（FR-REC-039）
        self._id_tracker = SongIdentificationTracker(fail_after=identification_fail_after)

    def analyze(self, frame_bgr: np.ndarray) -> AnalysisResult:
        # 楽曲特定済み or 検出失敗確定済みなら楽曲名 OCR をスキップして
        # プレイ中の連続 OCR 呼び出しを最小化する
        # （PaddleOCR ネイティブ層の access violation 対策、I-027）。
        skip_song_ocr = (
            self._last_chart is not None or self._id_tracker.is_confirmed_failed()
        )
        analysis = self._pipeline.analyze(
            frame_bgr, song_already_identified=skip_song_ocr
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
            self._last_raw_song_text = None
            self._id_tracker.reset()

        if screen == ScreenType.PLAY and analysis.play_metrics is not None:
            pm = analysis.play_metrics
            # 楽曲名 OCR がスキップされたフレームでは pm.raw_song_text が None。
            # ピリオドのある特定確定後は raw_song_text を上書きしない。
            if pm.raw_song_text is not None:
                self._last_raw_song_text = pm.raw_song_text
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

            # 楽曲名 OCR が実際に走ったフレーム（pm.raw_song_text is not None）でのみ
            # 検出失敗トラッカに結果を投入する。OCR をスキップしたフレームは数えない。
            if pm.raw_song_text is not None and self._last_chart is None:
                self._id_tracker.record_attempt(id_result.chart)

            # リトライ検出
            snap = PlayFrameSnapshot(
                score=pm.score, cool=None, great=None, good=None, bad=None,
                combo=pm.combo,
            )
            retry = self._retry.push(snap)

            return AnalysisResult(
                screen=screen,
                confidence=analysis.detection.confidence,
                raw_song_text=self._last_raw_song_text,
                identified_chart=self._last_chart,
                song_identification_failed=(
                    self._last_chart is None and self._id_tracker.is_confirmed_failed()
                ),
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
                raw_song_text=self._last_raw_song_text,
                identified_chart=self._last_chart,
                song_identification_failed=(
                    self._last_chart is None and self._id_tracker.is_confirmed_failed()
                ),
                result_score=rm.score,
                result_combo=rm.combo,
                result_judgements=rm.judgements,
                result_clear_type=rm.clear_type.value if rm.clear_type else None,
            )

        # その他画面: 楽曲・状態のみ
        return AnalysisResult(
            screen=screen,
            confidence=analysis.detection.confidence,
            raw_song_text=self._last_raw_song_text,
            identified_chart=self._last_chart,
        )

    def reset(self) -> None:
        self._state.reset()
        self._retry.reset()
        self._song_stab.reset()
        self._last_chart = None
        self._last_raw_song_text = None
        self._id_tracker.reset()
