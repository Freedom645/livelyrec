"""記録ライフサイクル管理サービス。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §3.3

2026-05-20: OBS クライアントの同期化（obs-websocket-py 移行）に伴い、記録ループを
asyncio から同期スレッドループへ再設計。あわせて結合テストで検出した欠陥を修正:
  - I-010: 再接続を無限再帰からバックオフ反復（有界）へ変更
  - I-011: ソース名未設定を事前検証し、設定/要求エラーと通信切断を分離
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from livelyrec.domain.rank_medal import clear_medal, clear_rank
from livelyrec.domain.score import (
    Chart,
    ClearType,
    Difficulty,
    Judgements,
    PlaySession,
    Result,
    SessionStatus,
)
from livelyrec.domain.state import RecordingState, ScreenType
from livelyrec.infrastructure.banner_writer import BannerWriter
from livelyrec.infrastructure.obs_client import OBSClient
from livelyrec.infrastructure.repository.daily_counter_repo import DailyCounterRepository
from livelyrec.infrastructure.repository.play_session_repo import PlaySessionRepository
from livelyrec.infrastructure.repository.result_repo import ResultRepository
from livelyrec.infrastructure.result_writer import ResultWriter
from livelyrec.shared.exceptions import (
    ObsConfigurationError,
    ObsConnectionError,
    ObsRequestError,
)
from livelyrec.shared.time_utils import business_date_of

from .analysis_service import AnalysisResult, AnalysisService

# 検出失敗時の固定表示文言（FR-STR-008）
DETECTION_FAILED_LABEL = "検出失敗"

logger = logging.getLogger("livelyrec.recording")

Listener = Callable[[dict], None]

# 連続リクエストエラーがこの回数に達したら記録を停止する（暴走防止）
_MAX_CONSECUTIVE_REQUEST_ERRORS = 10
# フレーム取得成功を挟まない連続再接続がこの回数に達したら停止する（接続嵐の防止）
_MAX_CONSECUTIVE_RECONNECTS = 5
# 再接続を試みる前に空ける間隔（秒）。連続再接続のループ化を防ぐ。
_RECONNECT_INTERVAL = 1.0
# 接続バックオフ（秒）。1巡したら打ち切る有界処理。
_RECONNECT_BACKOFF: tuple[float, ...] = (0.0, 1.0, 2.0, 4.0, 8.0)
# デバッグ撮影の保存間隔（秒）
_DEBUG_CAPTURE_INTERVAL = 2.0
# リザルト記録の安定化（I-017）: アニメーション途中の値で記録しないための閾値
_RESULT_STABLE_FRAMES = 3   # スコアが同値で続いたら安定とみなすフレーム数
_RESULT_MAX_FRAMES = 24     # 安定しなくてもこのフレーム数で記録（フォールバック）


class _ResultStabilizer:
    """リザルト画面のアニメーション中ではなく、安定した値で記録するための状態（I-017）。

    pop'n music のリザルト画面はスコア・判定数がカウントアップ表示されるため、
    最初のフレームで記録すると途中の値を読んでしまう。スコアが数フレーム
    同値で続いた（＝アニメーション完了）時点で記録する。
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last_score: int | None = None
        self._stable_count = 0
        self._frame_count = 0
        self.handled = False

    def feed(self, score: int) -> bool:
        """リザルトフレームの score を投入。記録すべき安定タイミングなら True。"""
        self._frame_count += 1
        if score == self._last_score:
            self._stable_count += 1
        else:
            self._last_score = score
            self._stable_count = 1
        return (
            self._stable_count >= _RESULT_STABLE_FRAMES
            or self._frame_count >= _RESULT_MAX_FRAMES
        )


class RecordingService:
    """OBS 取得 → 画像分析 → 記録 のループを管理する。

    OBS クライアントは同期 API のため、記録ループは専用スレッド上の
    単純なポーリングループとして実装する。
    """

    def __init__(
        self,
        obs: OBSClient,
        analysis: AnalysisService,
        session_repo: PlaySessionRepository,
        result_repo: ResultRepository,
        daily_repo: DailyCounterRepository,
        rollover_hour: int = 6,
        fps: int = 2,
        debug_dir: Path | None = None,
        debug_capture: bool = False,
        result_writer: ResultWriter | None = None,
        banner_writer: BannerWriter | None = None,
    ) -> None:
        # constants モジュール経由で参照し、テストで MAX_FPS を monkeypatch
        # 可能にする（録画ループの結合テストで擬似的に fps を上げるため）。
        from livelyrec.shared import constants as _const
        self._obs = obs
        self._analysis = analysis
        self._sessions = session_repo
        self._results = result_repo
        self._daily = daily_repo
        self._rollover_hour = rollover_hour
        # 上限を MAX_FPS で抑制（I-025 対応。設定で大きな値が来ても上限で頭打ち）。
        self._fps = max(1, min(fps, _const.MAX_FPS))
        # 記録中フレームの保存先（ROI 校正用）と、その ON/OFF。
        # ON/OFF は set_debug_capture で実行中に切り替えられる。
        self._debug_dir = debug_dir
        self._debug_capture = debug_capture
        # FR-REC-046 / FR-DEV-002 用ライター。設定変更時に set_*_capture で即時反映。
        self._result_writer = result_writer
        self._banner_writer = banner_writer

        self._state: RecordingState = RecordingState.INITIAL
        self._listeners: list[Listener] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # 現在進行中のセッション
        self._current_session: PlaySession | None = None
        # 現在進行中の譜面（楽曲名・難易度の表示用に保持）。
        # 検出失敗（chart_id=NULL）セッション中は None のまま。
        self._current_chart: Chart | None = None
        # 検出失敗が確定したセッションかどうか（now_playing.changed の display 用）
        self._current_detection_failed: bool = False
        # SELECT 画面で確定したカーソル位置の譜面（v2.0、FR-BAN-002 / FR-STR-007 ③）。
        # プレイセッションが無い時に now_playing.changed の payload に採用される。
        # PLAY 画面に入ったら無効化される。
        self._current_select_chart: Chart | None = None
        # 進行中楽曲のプレイ画面判定数累計（日次カウンタのライブ表示用 / FR-REC-034）
        self._live_judgements: Judgements = Judgements()
        # リザルト記録の安定化状態（I-017）
        self._result_stabilizer = _ResultStabilizer()

    # ---- イベントリスナ ----

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _emit(self, event_type: str, payload: dict) -> None:
        for ls in self._listeners:
            try:
                ls({"type": event_type, "payload": payload})
            except Exception:
                logger.exception("listener failed")

    # ---- ライフサイクル ----

    @property
    def state(self) -> RecordingState:
        return self._state

    def start(self) -> None:
        if self._state in (
            RecordingState.RECORDING,
            RecordingState.RECORDING_UNKNOWN,
            RecordingState.CONNECTING,
        ):
            return
        self._stop_event.clear()
        self._set_state(RecordingState.CONNECTING)
        self._thread = threading.Thread(target=self._run, name="recording", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._state == RecordingState.STOPPED:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=8.0)
            self._thread = None
        # 進行中セッションを ABANDONED に
        if self._current_session is not None:
            try:
                self._sessions.set_status(
                    self._current_session.session_id,
                    SessionStatus.ABANDONED,
                    ended_at=datetime.now(),
                )
            except Exception:
                logger.exception("set_status on stop failed")
            self._current_session = None
            self._current_chart = None
        self._set_state(RecordingState.STOPPED)

    def _set_state(self, new_state: RecordingState) -> None:
        if self._state == new_state:
            return
        self._state = new_state
        self._emit("state.changed", {"recording_state": new_state.value})

    def set_debug_capture(self, enabled: bool) -> None:
        """デバッグ撮影の ON/OFF を実行中に切り替える（設定変更の即時反映用）。"""
        self._debug_capture = enabled

    def set_result_capture(self, enabled: bool, output_dir: Path | None = None) -> None:
        """リザルト自動スクショ（FR-REC-046）の ON/OFF と保存先を実行中に切り替える。"""
        if self._result_writer is None:
            return
        self._result_writer.set_enabled(enabled)
        if output_dir is not None:
            self._result_writer.set_output_dir(output_dir)

    def set_banner_capture(self, enabled: bool, output_dir: Path | None = None) -> None:
        """開発者向けバナー画像保存（FR-DEV-002）の ON/OFF と保存先を実行中に切り替える。"""
        if self._banner_writer is None:
            return
        self._banner_writer.set_enabled(enabled)
        if output_dir is not None:
            self._banner_writer.set_output_dir(output_dir)

    # ---- 主ループ（同期・専用スレッド） ----

    def _run(self) -> None:
        # 事前検証: ソース名未設定なら記録ループに入らず明示エラー（I-011）
        if not self._obs.source_name:
            logger.error("OBS source name is not configured")
            self._emit("error", {
                "code": "NO_SOURCE",
                "message": "OBS のソース名が設定されていません。設定画面でソースを選択してください。",
            })
            self._set_state(RecordingState.INITIAL)
            return

        if not self._connect_with_backoff():
            self._set_state(RecordingState.INITIAL)
            return

        self._set_state(RecordingState.RECORDING_UNKNOWN)
        try:
            self._capture_loop()
        finally:
            self._obs.disconnect()

    def _connect_with_backoff(self) -> bool:
        """バックオフ付きで接続を試みる。成功で True、停止/全失敗で False。

        無限再帰を避けるため、バックオフ列を1巡するだけの有界処理とする（I-010）。
        """
        for delay in _RECONNECT_BACKOFF:
            if self._stop_event.is_set():
                return False
            if delay and self._stop_event.wait(delay):
                return False
            try:
                self._obs.connect()
                return True
            except ObsConnectionError as e:
                logger.warning("OBS connect failed: %s", e)
        self._emit("error", {
            "code": "OBS_CONNECT",
            "message": "OBS に接続できませんでした。OBS の起動・WebSocket 設定・接続情報を確認してください。",
        })
        return False

    def _capture_loop(self) -> None:
        interval = 1.0 / self._fps
        consecutive_request_errors = 0
        consecutive_reconnects = 0
        last_debug = 0.0
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            try:
                png = self._obs.get_source_screenshot_png()
                frame = _decode_png_to_bgr(png)
                analysis = self._analysis.analyze(frame)
                self._handle_analysis(analysis, frame)
                if (
                    self._state == RecordingState.RECORDING_UNKNOWN
                    and analysis.screen != ScreenType.UNKNOWN
                ):
                    self._set_state(RecordingState.RECORDING)
                # フレーム取得に成功したら連続エラーカウンタをリセット
                consecutive_request_errors = 0
                consecutive_reconnects = 0
                if (
                    self._debug_capture
                    and self._debug_dir is not None
                    and t0 - last_debug >= _DEBUG_CAPTURE_INTERVAL
                ):
                    self._save_debug_frame(frame, analysis.screen)
                    last_debug = t0
            except ObsConnectionError as e:
                # 本物の通信切断 → 有界バックオフで再接続（I-010）。
                # フレーム取得成功を挟まない連続再接続が続く場合は接続嵐とみなし停止する。
                consecutive_reconnects += 1
                if consecutive_reconnects > _MAX_CONSECUTIVE_RECONNECTS:
                    logger.error("OBS reconnect storm detected; stopping capture")
                    self._emit("error", {
                        "code": "OBS_UNSTABLE",
                        "message": "OBS との接続が安定しません。記録を停止しました。",
                    })
                    self._set_state(RecordingState.INITIAL)
                    return
                logger.warning(
                    "OBS disconnected (reconnect %d/%d): %s",
                    consecutive_reconnects, _MAX_CONSECUTIVE_RECONNECTS, e,
                )
                self._set_state(RecordingState.CONNECTING)
                self._obs.disconnect()
                # 再接続の間隔を空け、連続再接続がループ化するのを防ぐ
                if self._stop_event.wait(_RECONNECT_INTERVAL):
                    return
                if not self._connect_with_backoff():
                    self._set_state(RecordingState.INITIAL)
                    return
                self._set_state(RecordingState.RECORDING_UNKNOWN)
                continue
            except (ObsConfigurationError, ObsRequestError) as e:
                # 設定/要求エラーは再接続では解決しない。連続発生で記録を停止（I-010/I-011）
                consecutive_request_errors += 1
                logger.warning(
                    "OBS request error (%d/%d): %s",
                    consecutive_request_errors, _MAX_CONSECUTIVE_REQUEST_ERRORS, e,
                )
                if consecutive_request_errors >= _MAX_CONSECUTIVE_REQUEST_ERRORS:
                    logger.error("too many consecutive OBS request errors; stopping capture")
                    self._emit("error", {
                        "code": "OBS_REQUEST",
                        "message": (
                            "OBS リクエストが繰り返し失敗しました。"
                            f"ソース名の設定を確認してください: {e}"
                        ),
                    })
                    self._set_state(RecordingState.INITIAL)
                    return
            except Exception:
                logger.exception("analyze loop iteration failed")
            elapsed = time.perf_counter() - t0
            remaining = interval - elapsed
            if remaining > 0:
                # stop_event でいつでも中断できる待機
                self._stop_event.wait(remaining)

    def _save_debug_frame(self, frame: np.ndarray, screen: ScreenType) -> None:
        """デバッグ用に取得フレームを保存する（ROI 校正・システムテスト用）。"""
        if self._debug_dir is None:
            return
        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%H%M%S_%f")[:-3]
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                (self._debug_dir / f"{stamp}_{screen.value}.png").write_bytes(
                    buf.tobytes()
                )
        except Exception:
            logger.exception("debug frame save failed")

    # ---- 分析結果のハンドリング ----

    def _handle_analysis(
        self, analysis: AnalysisResult, frame: np.ndarray | None = None
    ) -> None:
        self._emit(
            "state.changed",
            {
                "screen": analysis.screen.value,
                "confidence": analysis.confidence,
            },
        )

        if analysis.screen == ScreenType.PLAY:
            self._handle_play(analysis)
        elif analysis.screen == ScreenType.RESULT:
            self._handle_result(analysis, frame)
        else:
            # SELECT/READY/OPTION/ロード等の楽曲外画面で SELECT chart を追跡（v2.0）。
            # PLAY 画面に入っている間は SELECT 楽曲を表示せず、プレイ中楽曲が優先。
            self._handle_select(analysis)

        if (
            analysis.screen not in (ScreenType.PLAY, ScreenType.RESULT)
            and self._live_judgements.total != 0
        ):
            # 楽曲外（選曲/準備/ロード等）に出たらライブ判定数をリセット
            self._live_judgements = Judgements()
            self._emit_judgements_tick()

        if analysis.screen != ScreenType.RESULT:
            # リザルト画面を離れたら安定化状態をリセットし、次のリザルトに備える
            self._result_stabilizer.reset()

        if analysis.screen == ScreenType.PLAY and self._current_select_chart is not None:
            # プレイ画面に入ったら SELECT chart を忘れる（プレイ中楽曲を優先表示）
            self._current_select_chart = None

    def _handle_select(self, analysis: AnalysisResult) -> None:
        """SELECT 画面で確定した chart を `_current_select_chart` に反映し、
        変化があったら `now_playing.changed` を発火する（v2.0、FR-STR-007 ③）。

        プレイセッション中（`_current_session is not None`）は SELECT 楽曲を
        通知しない（プレイ中楽曲が優先表示）。
        """
        if self._current_session is not None:
            return
        new_chart = analysis.select_chart
        prev = self._current_select_chart
        # chart_id ベースで差分判定（同一インスタンスでなくても等価判定）
        prev_id = prev.chart_id if prev is not None else None
        new_id = new_chart.chart_id if new_chart is not None else None
        if prev_id == new_id:
            return
        self._current_select_chart = new_chart
        self._emit_now_playing()

    def _emit_judgements_tick(self) -> None:
        """日次累計＋進行中楽曲のライブ判定数を judgements.tick として通知する。"""
        now = datetime.now()
        try:
            persisted = self._daily.get(business_date_of(now, self._rollover_hour))
        except Exception:
            logger.exception("daily counter read failed")
            return
        total = persisted + self._live_judgements
        self._emit("judgements.tick", {
            "daily_total": {
                "cool": total.cool,
                "great": total.great,
                "good": total.good,
                "bad": total.bad,
                "total": total.total,
            },
        })

    def emit_state_snapshot(self) -> None:
        """現在の日次カウンタを再通知する。

        起動直後の初期表示用。これを呼ばないと最初のリザルトが出るまで
        カウンタが 0 のまま表示される。
        """
        self._emit_judgements_tick()

    def _handle_play(self, analysis: AnalysisResult) -> None:
        # 譜面が確定し、まだセッションが無ければ作成
        if analysis.identified_chart is not None and self._current_session is None:
            now = datetime.now()
            chart = analysis.identified_chart
            self._current_chart = chart
            self._current_detection_failed = False
            self._current_session = self._sessions.create(
                chart=chart,
                started_at=now,
                business_date=business_date_of(now, self._rollover_hour),
                raw_song_text=analysis.raw_song_text,
            )
            difficulty = chart.difficulty.value
            if chart.level is not None:
                difficulty = f"{difficulty} {chart.level}"
            self._emit("play.started", {
                "session_id": self._current_session.session_id,
                "chart_id": chart.chart_id,
                "title": chart.title,
                "difficulty": difficulty,
            })
            self._emit_now_playing()

        # 楽曲名 OCR が連続失敗で確定した「検出失敗」セッション（FR-REC-039）
        elif (
            analysis.identified_chart is None
            and analysis.song_identification_failed
            and self._current_session is None
        ):
            now = datetime.now()
            self._current_chart = None
            self._current_detection_failed = True
            self._current_session = self._sessions.create(
                chart=None,
                started_at=now,
                business_date=business_date_of(now, self._rollover_hour),
                raw_song_text=analysis.raw_song_text,
            )
            self._emit("play.started", {
                "session_id": self._current_session.session_id,
                "chart_id": None,
                "title": DETECTION_FAILED_LABEL,
                "difficulty": None,
            })
            self._emit_now_playing()

        if analysis.retry_detected and self._current_session is not None:
            self._sessions.append_retry(self._current_session.session_id, datetime.now())
            self._sessions.increment_attempt(self._current_session.session_id)
            self._emit("play.retry", {"session_id": self._current_session.session_id})

        # プレイ画面下部の判定数累計をライブ表示へ反映（FR-REC-034）
        pj = analysis.play_judgements
        if pj is not None and pj != self._live_judgements:
            self._live_judgements = pj
            self._emit_judgements_tick()

    def _emit_now_playing(self) -> None:
        """`now_playing.changed` を配信する（FR-STR-007 ②, FR-STR-008 / FR-STR-007 ③）。

        - プレイセッション中: 現プレイ楽曲を送る（既存挙動）
        - プレイセッション外で SELECT 画面 chart が確定中: 選曲中楽曲を送る
          （v2.0、R-027 プレースホルダ廃止）
        - どちらも無い場合は発火しない
        """
        chart: Chart | None
        identified: bool
        business_date: str
        session_id: str | None
        source: str  # "play" or "select"

        if self._current_session is not None:
            chart = self._current_chart
            identified = chart is not None
            business_date = self._current_session.business_date.isoformat()
            session_id = self._current_session.session_id
            source = "play"
        elif self._current_select_chart is not None:
            chart = self._current_select_chart
            identified = True
            business_date = business_date_of(
                datetime.now(), self._rollover_hour
            ).isoformat()
            session_id = None
            source = "select"
        else:
            return

        chart_payload: dict | None = None
        if chart is not None:
            chart_payload = {
                "chart_id": chart.chart_id,
                "song_id": chart.song_id,
                "title": chart.title,
                "genre": chart.genre,
                "difficulty": chart.difficulty.value,
                "is_upper": chart.is_upper,
                "level": chart.level,
            }
        display_title = (
            chart.title if chart is not None else DETECTION_FAILED_LABEL
        )
        self._emit("now_playing.changed", {
            "session_id": session_id,
            "identified": identified,
            "chart": chart_payload,
            "display_title": display_title,
            "business_date": business_date,
            "source": source,
        })

    def _handle_result(
        self, analysis: AnalysisResult, frame: np.ndarray | None = None
    ) -> None:
        stab = self._result_stabilizer
        if stab.handled:
            # このリザルト表示はすでに記録／スキップ済み
            return
        if self._current_session is None:
            # セッションが無い場合は記録できない（プレイ画面を見逃した）
            stab.handled = True
            self._emit("result.skipped", {"reason": "no session"})
            return
        if analysis.result_score is None:
            # スコア未取得時は次フレームを待つ
            return
        # リザルト値の安定化: アニメーション途中の値では記録しない（I-017）
        if not stab.feed(analysis.result_score):
            return
        stab.handled = True
        try:
            clear = ClearType(analysis.result_clear_type)
        except ValueError:
            clear = ClearType.CLEAR
        judges = analysis.result_judgements or Judgements()
        score = max(0, min(100000, analysis.result_score))
        rank = clear_rank(score, cleared=clear != ClearType.FAILED)
        medal = clear_medal(
            clear,
            judges,
            # 記録対象はプレイ中に確定したセッションの譜面（リザルト画面の
            # identified_chart はリセット済みのため使わない）。
            # 検出失敗セッション（chart None）は NORMAL 扱いでメダル算出する。
            self._current_chart.difficulty
            if self._current_chart
            else Difficulty.NORMAL,
        )
        result = Result(
            score=score,
            judgements=judges,
            combo=analysis.result_combo or 0,
            clear_type=clear,
            medal=medal,
            rank=rank,
            best_score_diff=None,
        )
        now = datetime.now()
        self._results.upsert(self._current_session.session_id, result, now)
        self._sessions.set_status(
            self._current_session.session_id,
            SessionStatus.COMPLETED,
            ended_at=now,
        )
        # 日次累計に判定数を加算（リザルトの確定値が累計の正）
        try:
            self._daily.add(business_date_of(now, self._rollover_hour), judges)
        except Exception:
            logger.exception("daily counter update failed")
        # 楽曲完了によりライブ判定数をクリアし、確定後の累計を通知
        self._live_judgements = Judgements()
        self._emit_judgements_tick()

        # 検出失敗時は表示タイトルを「検出失敗」、chart は None とする（FR-STR-008）
        display_title = (
            self._current_chart.title
            if self._current_chart is not None
            else DETECTION_FAILED_LABEL
        )
        chart_payload: dict | None = None
        if self._current_chart is not None:
            c = self._current_chart
            chart_payload = {
                "chart_id": c.chart_id,
                "song_id": c.song_id,
                "title": c.title,
                "genre": c.genre,
                "difficulty": c.difficulty.value,
                "is_upper": c.is_upper,
                "level": c.level,
            }

        self._emit("result.recorded", {
            "session_id": self._current_session.session_id,
            "chart": chart_payload,
            "display_title": display_title,
            "title": self._current_chart.title if self._current_chart else None,
            "score": result.score,
            "rank": result.rank.value,
            "medal": result.medal.value,
            "clear_type": result.clear_type.value,
            "combo": result.combo,
            "judgements": {
                "cool": judges.cool,
                "great": judges.great,
                "good": judges.good,
                "bad": judges.bad,
            },
        })

        # 自動スクショ／開発者バナー画像（FR-REC-046〜048 / FR-DEV-002）。
        # writer 内部で enabled=False や書込み失敗時は黙ってスキップする。
        # frame=None は単体テスト経路（実 OBS フレーム無し）であり、writer 呼び出しを省略。
        if frame is not None:
            if self._result_writer is not None:
                self._result_writer.save(
                    frame_bgr=frame,
                    song_title=self._current_chart.title if self._current_chart else None,
                    score=result.score,
                    ts=now,
                )
            # バナー画像は楽曲特定済みのプレイのみ意味があるため、検出失敗時はスキップ。
            if self._banner_writer is not None and self._current_chart is not None:
                self._banner_writer.save(
                    frame_bgr=frame,
                    song_title=self._current_chart.title,
                    ts=now,
                )

        self._current_session = None
        self._current_chart = None
        self._current_detection_failed = False


def _decode_png_to_bgr(png_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("failed to decode PNG")
    return img
