"""画面分析サービス。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §3.4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from livelyrec.domain.score import Chart, Difficulty, Judgements
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline
from livelyrec.infrastructure.recognizer.retry_detector import (
    PlayFrameSnapshot,
    RetryDetector,
)
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI, SELECT_ROI
from livelyrec.infrastructure.recognizer.select_screen import (
    detect_difficulty_color,
    detect_upper_mark,
)

from .banner_match_service import BannerMatchService
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
    # SELECT 画面で確定したカーソル位置楽曲（v2.0、FR-BAN-002 / FR-STR-007 ③）。
    # バナー特徴量マッチ + UPPER マーク + 難易度色から chart_id を確定する。
    # None は「SELECT 画面でない」または「特定不能」を意味する。
    select_chart: Chart | None = None


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
        banner_match: BannerMatchService | None = None,
        upper_template: np.ndarray | None = None,
        upper_template_left: np.ndarray | None = None,
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
        # 2 次認識器: バナー特徴量マッチ（FR-BAN-001、v2.0）
        self._banner_match = banner_match
        # SELECT 画面 UPPER マークテンプレ（FR-BAN-002、v2.0）。
        # UPPER マークは譜面ごとに右側・左側どちらかに表示されるため両方注入する
        # （2026-05-31、実機サンプルで両側パターン確認）。
        # 右側のみ、左側のみ、両方なしのいずれもサポート。
        self._upper_template = upper_template
        self._upper_template_left = upper_template_left
        # SELECT 画面の連続フレーム多数決（カーソル移動安定化用）
        self._select_chart_stab = SongStabilizer(window=5, min_majority=0.6)

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
            # 2 次認識器: プレイ画面 OCR キャッシュが取れていない場合に
            # バナー特徴量マッチで楽曲を特定する（FR-BAN-001、v2.0）。
            # 既に特定済 or 検出失敗確定なら呼び出さない。
            if (
                self._last_chart is None
                and not self._id_tracker.is_confirmed_failed()
                and self._banner_match is not None
            ):
                # RESULT 画面の ResultMetrics には difficulty が含まれないため
                # ヒントなしで譜面選択させる（HYPER 優先のフォールバック）
                chart = self._identify_by_banner(frame_bgr, difficulty_hint=None)
                if chart is not None:
                    self._last_chart = chart
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

        # SELECT 画面: バナー特徴量マッチ + UPPER/難易度色から chart_id を確定（FR-BAN-002）
        select_chart: Chart | None = None
        if screen == ScreenType.SELECT and self._banner_match is not None:
            select_chart = self._identify_select_chart(frame_bgr)
        else:
            # SELECT 画面以外に出たら多数決バッファをリセット
            self._select_chart_stab.reset()

        # その他画面: 楽曲・状態のみ
        return AnalysisResult(
            screen=screen,
            confidence=analysis.detection.confidence,
            raw_song_text=self._last_raw_song_text,
            identified_chart=self._last_chart,
            select_chart=select_chart,
        )

    def reset(self) -> None:
        self._state.reset()
        self._retry.reset()
        self._song_stab.reset()
        self._last_chart = None
        self._last_raw_song_text = None
        self._id_tracker.reset()
        self._select_chart_stab.reset()

    def _identify_select_chart(self, frame_bgr: np.ndarray) -> Chart | None:
        """SELECT 画面のカーソル位置楽曲を chart_id 単位で確定する（FR-BAN-002）。

        フロー:
        1. SELECT_ROI["banner"] でバナー特徴量マッチ → song_id 取得
        2. SELECT_ROI["difficulty_color"] で難易度色判定 → Difficulty
        3. SELECT_ROI["upper_mark"] でテンプレマッチ → is_upper
        4. master の Song から (difficulty, is_upper) に該当する Chart を選ぶ
        5. SongStabilizer で連続フレーム多数決

        いずれかが取れなければ None。多数決が安定するまでも None。
        """
        if self._banner_match is None:
            return None
        try:
            match = self._banner_match.identify(
                frame_bgr=frame_bgr, roi=SELECT_ROI["banner"]
            )
        except Exception:
            logger.warning(
                "banner match raised during SELECT identify", exc_info=True
            )
            return None
        if match is None or not match.accepted:
            # 楽曲未確定 → 多数決バッファに None を投じてリセット気味に
            self._select_chart_stab.push(None)
            return None
        song = self._master.get_song(match.song_id)
        if song is None:
            logger.warning(
                "SELECT: banner matched song_id %s but not found in master DB",
                match.song_id,
            )
            return None

        difficulty = detect_difficulty_color(frame_bgr)
        if difficulty is None:
            # 難易度色が読めないと chart_id を確定できないので None
            self._select_chart_stab.push(None)
            return None

        is_upper = False
        if self._upper_template is not None:
            is_upper, _ = detect_upper_mark(
                frame_bgr,
                self._upper_template,
                template_gray_left=self._upper_template_left,
            )

        # song.charts から (difficulty, is_upper) に該当する譜面を選ぶ
        target = None
        for c in song.charts:
            if c.difficulty == difficulty and c.is_upper == is_upper:
                target = c
                break
        if target is None:
            # 該当譜面が master にない（has_upper=False の楽曲で is_upper=True を
            # 検出した等）。is_upper のみフォールバックして再試行する。
            for c in song.charts:
                if c.difficulty == difficulty:
                    target = c
                    break
        if target is None:
            return None

        # 多数決で安定化（カーソル移動中の瞬間取得を防ぐ）
        stable_id = self._select_chart_stab.push(target.chart_id)
        if stable_id != target.chart_id:
            return None
        return target

    def _identify_by_banner(
        self,
        frame_bgr: np.ndarray,
        difficulty_hint: Difficulty | None,
    ) -> Chart | None:
        """RESULT 画面のバナー領域から楽曲を特定し、Chart を返す（FR-BAN-001）。

        マッチに失敗した場合や受理しなかった場合は None。1 次認識器との
        primary_candidates 突合は本サービスでは行わない（RESULT 画面では
        既にキャッシュ照合済みのため、純粋に Top-1 を採用する）。
        """
        if self._banner_match is None:
            return None
        try:
            result = self._banner_match.identify(
                frame_bgr=frame_bgr, roi=RESULT_ROI["banner"]
            )
        except Exception:
            logger.warning("banner match raised during RESULT identify", exc_info=True)
            return None
        if result is None or not result.accepted:
            return None
        song = self._master.get_song(result.song_id)
        if song is None:
            logger.warning(
                "banner matched song_id %s but not found in master DB",
                result.song_id,
            )
            return None
        # 既存ロジックと同じく難易度ヒントを尊重して譜面を選ぶ
        if difficulty_hint is not None:
            for chart in song.charts:
                if chart.difficulty == difficulty_hint:
                    logger.info(
                        "banner-identified: song=%s difficulty=%s distance=%d",
                        song.title,
                        difficulty_hint.value,
                        result.distance,
                    )
                    return chart
        priority = (
            Difficulty.HYPER,
            Difficulty.EX,
            Difficulty.NORMAL,
            Difficulty.EASY,
            Difficulty.UPPER,
        )
        by_diff = {c.difficulty: c for c in song.charts}
        for p in priority:
            if p in by_diff:
                logger.info(
                    "banner-identified (fallback diff): song=%s difficulty=%s distance=%d",
                    song.title,
                    p.value,
                    result.distance,
                )
                return by_diff[p]
        return song.charts[0] if song.charts else None
