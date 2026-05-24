"""RecordingService の純ロジック部のテスト。

OBS 取得→分析→記録のスレッド駆動メインループ（``_run`` / ``_connect_and_loop``）は
結合テストの範囲とし、本テストでは分析結果ハンドリング・状態遷移・イベント発火・
PNG デコードといった単体検証可能な部分を対象とする。
リポジトリはフェイクで差し替える。
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from livelyrec.application.analysis_service import AnalysisResult
from livelyrec.application.recording_service import RecordingService, _decode_png_to_bgr
from livelyrec.domain.score import Chart, Difficulty, Judgements, PlaySession, SessionStatus
from livelyrec.domain.state import RecordingState, ScreenType

_CHART = Chart(song_id="popn-1", title="テスト楽曲", difficulty=Difficulty.HYPER, level=36)


class FakeSessionRepo:
    def __init__(self) -> None:
        self.created: list[PlaySession] = []
        self.retries: list[tuple] = []
        self.attempts: list[str] = []
        self.statuses: list[tuple] = []
        self._counter = 0

    def create(self, chart, started_at, business_date, **kwargs):  # noqa: ARG002
        self._counter += 1
        sess = PlaySession(
            session_id=f"sess-{self._counter}",
            chart=chart,
            started_at=started_at,
            business_date=business_date,
        )
        self.created.append(sess)
        return sess

    def append_retry(self, session_id, dt) -> None:
        self.retries.append((session_id, dt))

    def increment_attempt(self, session_id) -> None:
        self.attempts.append(session_id)

    def set_status(self, session_id, status, ended_at=None) -> None:
        self.statuses.append((session_id, status, ended_at))


class FakeResultRepo:
    def __init__(self) -> None:
        self.upserts: list[tuple] = []

    def upsert(self, session_id, result, recorded_at) -> None:
        self.upserts.append((session_id, result, recorded_at))


class FakeDailyRepo:
    def __init__(self) -> None:
        self.adds: list[tuple] = []
        self._cumulative = Judgements()

    def add(self, business_date, judgements):
        self.adds.append((business_date, judgements))
        self._cumulative = self._cumulative + judgements
        return self._cumulative

    def get(self, business_date):  # noqa: ARG002
        return self._cumulative


def _service() -> tuple[RecordingService, FakeSessionRepo, FakeResultRepo, FakeDailyRepo]:
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    svc = RecordingService(
        obs=object(),
        analysis=object(),
        session_repo=sr,
        result_repo=rr,
        daily_repo=dr,
    )
    return svc, sr, rr, dr


def _feed_result(svc: RecordingService, ar: AnalysisResult, times: int = 3) -> None:
    """リザルト記録の安定化（I-017）に合わせ、同一リザルトを複数フレーム投入する。"""
    for _ in range(times):
        svc._handle_analysis(ar)


# ---- _handle_play ----

def test_handle_play_creates_session_once() -> None:
    svc, sr, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    ar = AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    svc._handle_analysis(ar)
    svc._handle_analysis(ar)  # 2回目はセッション継続中なので新規作成しない
    assert len(sr.created) == 1
    assert any(e["type"] == "play.started" for e in events)
    started = next(e for e in events if e["type"] == "play.started")
    assert started["payload"]["title"] == "テスト楽曲"
    assert "36" in started["payload"]["difficulty"]  # level=36 を含む


def test_handle_play_without_chart_does_not_create_session() -> None:
    svc, sr, _, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=None)
    )
    assert sr.created == []


def test_handle_play_retry_records_attempt() -> None:
    svc, sr, _, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART, retry_detected=True
        )
    )
    assert len(sr.retries) == 1
    assert len(sr.attempts) == 1


# ---- _handle_result ----

def test_handle_result_records_full_result() -> None:
    svc, sr, rr, dr = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    events: list[dict] = []
    svc.add_listener(events.append)
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT,
        confidence=0.95,
        identified_chart=_CHART,
        result_score=87268,
        result_combo=329,
        result_judgements=Judgements(312, 18, 5, 2),
        result_clear_type="CLEAR",
    ))
    assert len(rr.upserts) == 1
    assert rr.upserts[0][1].score == 87268
    assert any(s[1] == SessionStatus.COMPLETED for s in sr.statuses)
    assert len(dr.adds) == 1
    assert any(e["type"] == "result.recorded" for e in events)
    recorded = next(e for e in events if e["type"] == "result.recorded")
    assert recorded["payload"]["title"] == "テスト楽曲"


def test_handle_result_emits_judgements_tick() -> None:
    # リザルト確定で日次カウンタ更新通知（judgements.tick）が発火する（FR-REC-034）
    svc, _, _, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    events: list[dict] = []
    svc.add_listener(events.append)
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT,
        confidence=0.95,
        identified_chart=_CHART,
        result_score=87268,
        result_combo=329,
        result_judgements=Judgements(312, 18, 5, 2),
        result_clear_type="CLEAR",
    ))
    ticks = [e for e in events if e["type"] == "judgements.tick"]
    assert ticks, "judgements.tick が発火していない"
    total = ticks[-1]["payload"]["daily_total"]
    assert total["cool"] == 312
    assert total["total"] == 337


def test_emit_state_snapshot_emits_judgements_tick() -> None:
    # 起動直後の初期表示用: emit_state_snapshot で日次カウンタが通知される
    svc, _, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    svc.emit_state_snapshot()
    ticks = [e for e in events if e["type"] == "judgements.tick"]
    assert ticks, "emit_state_snapshot で judgements.tick が発火していない"
    assert "daily_total" in ticks[0]["payload"]


def test_handle_result_without_session_is_skipped() -> None:
    svc, _, rr, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.RESULT,
            confidence=0.9,
            result_score=80000,
            result_clear_type="CLEAR",
        )
    )
    assert rr.upserts == []
    assert any(e["type"] == "result.skipped" for e in events)


def test_handle_result_missing_metrics_not_recorded() -> None:
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.RESULT,
            confidence=0.9,
            identified_chart=_CHART,
            result_score=None,
            result_clear_type=None,
        )
    )
    assert rr.upserts == []


def test_handle_result_score_is_clamped() -> None:
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT,
        confidence=0.9,
        identified_chart=_CHART,
        result_score=999999,
        result_clear_type="CLEAR",
    ))
    assert rr.upserts[0][1].score == 100000


def test_handle_result_invalid_clear_type_defaults_to_clear() -> None:
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT,
        confidence=0.9,
        identified_chart=_CHART,
        result_score=70000,
        result_clear_type="UNKNOWN_TYPE",
    ))
    assert rr.upserts[0][1].clear_type.value == "CLEAR"


def test_handle_result_records_when_clear_type_is_none() -> None:
    # clear_type 未検出（None）でも score があれば CLEAR 既定で記録する（I-016c）
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT,
        confidence=0.9,
        identified_chart=_CHART,
        result_score=70000,
        result_clear_type=None,
    ))
    assert len(rr.upserts) == 1
    assert rr.upserts[0][1].clear_type.value == "CLEAR"


def test_handle_result_single_frame_does_not_record(tmp_path) -> None:  # noqa: ARG001
    # 1フレームのみでは記録しない（アニメーション途中の可能性 / I-017）
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.RESULT, confidence=0.9, identified_chart=_CHART,
            result_score=50000, result_clear_type="CLEAR",
        )
    )
    assert rr.upserts == []


def test_handle_result_records_after_score_stabilizes() -> None:
    # スコアが変動 → 安定 で、安定後の値が記録される（I-017）
    svc, _, rr, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    # アニメーション中（値が変動）
    for score in (10000, 40000):
        svc._handle_analysis(AnalysisResult(
            screen=ScreenType.RESULT, confidence=0.9, identified_chart=_CHART,
            result_score=score, result_clear_type="CLEAR",
        ))
    assert rr.upserts == []
    # 値が安定（同値が続く）→ 記録
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT, confidence=0.9, identified_chart=_CHART,
        result_score=87000, result_clear_type="CLEAR",
    ))
    assert len(rr.upserts) == 1
    assert rr.upserts[0][1].score == 87000


def test_save_debug_frame_writes_png(tmp_path) -> None:
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    svc = RecordingService(
        obs=object(), analysis=object(), session_repo=sr,
        result_repo=rr, daily_repo=dr, debug_dir=tmp_path, debug_capture=True,
    )
    svc._save_debug_frame(np.zeros((20, 30, 3), dtype=np.uint8), ScreenType.PLAY)
    saved = list(tmp_path.glob("*.png"))
    assert len(saved) == 1
    assert "play" in saved[0].name


def test_set_debug_capture_toggles_at_runtime() -> None:
    # デバッグ撮影は実行中に切り替えられる（設定変更の即時反映）
    svc, *_ = _service()
    assert svc._debug_capture is False
    svc.set_debug_capture(True)
    assert svc._debug_capture is True
    svc.set_debug_capture(False)
    assert svc._debug_capture is False


# ---- 状態遷移・イベント ----

def test_set_state_emits_only_on_change() -> None:
    svc, *_ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    svc._set_state(RecordingState.CONNECTING)
    svc._set_state(RecordingState.CONNECTING)  # 同一状態 → 発火しない
    state_events = [e for e in events if e["type"] == "state.changed"]
    assert len(state_events) == 1
    assert svc.state == RecordingState.CONNECTING


def test_emit_isolates_listener_exception() -> None:
    svc, *_ = _service()

    def bad(_event: dict) -> None:
        raise RuntimeError("listener boom")

    good_events: list[dict] = []
    svc.add_listener(bad)
    svc.add_listener(good_events.append)
    svc._set_state(RecordingState.RECORDING)  # bad が例外でも good には届く
    assert len(good_events) == 1


def test_stop_from_initial_sets_stopped() -> None:
    svc, *_ = _service()
    svc.stop()
    assert svc.state == RecordingState.STOPPED


def test_stop_abandons_current_session() -> None:
    svc, sr, _, _ = _service()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    svc.stop()
    assert any(s[1] == SessionStatus.ABANDONED for s in sr.statuses)
    assert svc.state == RecordingState.STOPPED


# ---- PNG デコード ----

def test_decode_png_roundtrip() -> None:
    img = np.full((4, 6, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    decoded = _decode_png_to_bgr(buf.tobytes())
    assert decoded.shape == (4, 6, 3)


def test_decode_png_invalid_raises() -> None:
    with pytest.raises(ValueError):
        _decode_png_to_bgr(b"not a png at all")
