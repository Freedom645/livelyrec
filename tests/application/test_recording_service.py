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


# ---- FR-REC-039 / FR-STR-008: 検出失敗時のハンドリング ----

def test_handle_play_creates_failed_detection_session() -> None:
    """song_identification_failed=True で chart=None の検出失敗セッションが作られる。"""
    svc, sr, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.PLAY, confidence=0.9, identified_chart=None,
            song_identification_failed=True, raw_song_text="??",
        )
    )
    assert len(sr.created) == 1
    assert sr.created[0].chart is None  # NULL セッション
    started = next(e for e in events if e["type"] == "play.started")
    assert started["payload"]["chart_id"] is None
    assert started["payload"]["title"] == "検出失敗"
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert nps
    assert nps[-1]["payload"]["identified"] is False
    assert nps[-1]["payload"]["display_title"] == "検出失敗"


def test_now_playing_changed_for_identified_session() -> None:
    """楽曲特定済みプレイ開始時にも now_playing.changed が配信される。"""
    svc, _, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert nps
    p = nps[-1]["payload"]
    assert p["identified"] is True
    assert p["chart"]["title"] == "テスト楽曲"
    assert p["display_title"] == "テスト楽曲"
    assert p["source"] == "play"


# --- v2.0: SELECT 画面で確定した楽曲を now_playing.changed で配信（FR-STR-007 ③） ---


def _select_chart(song_id: str = "popn-sel", title: str = "選曲楽曲") -> Chart:
    return Chart(
        song_id=song_id, title=title,
        difficulty=Difficulty.EX, is_upper=True, level=48,
    )


def test_select_chart_emits_now_playing_when_no_session() -> None:
    """プレイセッション無し時、SELECT 画面で確定した chart が now_playing.changed として配信される。"""
    svc, _, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    chart = _select_chart()
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.SELECT, confidence=0.85, select_chart=chart,
        )
    )
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert nps
    p = nps[-1]["payload"]
    assert p["identified"] is True
    assert p["chart"]["chart_id"] == chart.chart_id
    assert p["chart"]["is_upper"] is True
    assert p["chart"]["difficulty"] == "EX"
    assert p["display_title"] == "選曲楽曲"
    assert p["source"] == "select"
    assert p["session_id"] is None


def test_select_chart_change_emits_only_on_diff() -> None:
    """同じ chart_id で複数回 SELECT 画面に来ても、now_playing.changed は 1 回だけ発火。"""
    svc, _, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    chart = _select_chart()
    for _ in range(3):
        svc._handle_analysis(
            AnalysisResult(
                screen=ScreenType.SELECT, confidence=0.9, select_chart=chart,
            )
        )
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert len(nps) == 1


def test_select_chart_different_emits_again() -> None:
    """カーソル移動で chart_id が変われば再度 now_playing.changed が出る。"""
    svc, _, _, _ = _service()
    events: list[dict] = []
    svc.add_listener(events.append)
    chart_a = _select_chart(song_id="popn-a", title="曲A")
    chart_b = _select_chart(song_id="popn-b", title="曲B")
    svc._handle_analysis(AnalysisResult(screen=ScreenType.SELECT, confidence=0.9, select_chart=chart_a))
    svc._handle_analysis(AnalysisResult(screen=ScreenType.SELECT, confidence=0.9, select_chart=chart_b))
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert len(nps) == 2
    assert nps[0]["payload"]["display_title"] == "曲A"
    assert nps[1]["payload"]["display_title"] == "曲B"


def test_select_chart_ignored_during_play_session() -> None:
    """プレイセッション中の SELECT 画面は select_chart を反映しない（プレイ中楽曲が優先）。"""
    svc, _, _, _ = _service()
    # PLAY セッションを開始
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    events: list[dict] = []
    svc.add_listener(events.append)
    # SELECT 画面の chart を与えても now_playing.changed は出ない
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.SELECT, confidence=0.9, select_chart=_select_chart(),
        )
    )
    nps = [e for e in events if e["type"] == "now_playing.changed"]
    assert not nps


def test_select_chart_cleared_on_play_entry() -> None:
    """SELECT 中の chart が PLAY 画面進入時にクリアされる（次回 SELECT で再度発火する）。"""
    svc, _, _, _ = _service()
    chart = _select_chart()
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.SELECT, confidence=0.9, select_chart=chart)
    )
    # PLAY 画面に入る
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    # この時点で _current_select_chart はクリアされている想定
    assert svc._current_select_chart is None


def test_handle_result_for_failed_detection_session() -> None:
    """検出失敗セッションでもリザルト記録は走り、display_title='検出失敗' で配信される。"""
    svc, sr, rr, _ = _service()
    # 検出失敗でプレイ開始
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.PLAY, confidence=0.9, identified_chart=None,
            song_identification_failed=True, raw_song_text="??",
        )
    )
    events: list[dict] = []
    svc.add_listener(events.append)
    _feed_result(svc, AnalysisResult(
        screen=ScreenType.RESULT, confidence=0.9, identified_chart=None,
        song_identification_failed=True,
        result_score=50000, result_clear_type="CLEAR",
    ))
    assert len(rr.upserts) == 1  # 検出失敗でも result は記録
    assert any(s[1] == SessionStatus.COMPLETED for s in sr.statuses)
    rec = next(e for e in events if e["type"] == "result.recorded")
    assert rec["payload"]["chart"] is None
    assert rec["payload"]["display_title"] == "検出失敗"


# ---- FR-REC-046 / FR-DEV-002: writer 連携 ----

class _SpyResultWriter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def is_enabled(self) -> bool: return True
    def set_enabled(self, enabled: bool) -> None: ...
    def set_output_dir(self, output_dir) -> None: ...
    def save(self, frame_bgr, song_title, score, ts=None) -> None:  # noqa: ARG002
        self.calls.append((song_title, score))


class _SpyBannerWriter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def is_enabled(self) -> bool: return True
    def set_enabled(self, enabled: bool) -> None: ...
    def set_output_dir(self, output_dir) -> None: ...
    def save(self, frame_bgr, song_title, ts=None) -> None:  # noqa: ARG002
        self.calls.append((song_title,))


def test_writers_called_on_result_when_frame_provided() -> None:
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    spy_r, spy_b = _SpyResultWriter(), _SpyBannerWriter()
    svc = RecordingService(
        obs=object(), analysis=object(), session_repo=sr,
        result_repo=rr, daily_repo=dr,
        result_writer=spy_r, banner_writer=spy_b,
    )
    # プレイ開始
    svc._handle_analysis(
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART)
    )
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    for _ in range(3):
        svc._handle_analysis(AnalysisResult(
            screen=ScreenType.RESULT, confidence=0.9, identified_chart=_CHART,
            result_score=87000, result_clear_type="CLEAR",
        ), frame=frame)
    assert spy_r.calls == [("テスト楽曲", 87000)]
    assert spy_b.calls == [("テスト楽曲",)]


def test_banner_writer_skipped_on_failed_detection_session() -> None:
    """検出失敗セッションでは banner_writer は呼ばれない（楽曲不明のため学習データ無意味）。"""
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    spy_r, spy_b = _SpyResultWriter(), _SpyBannerWriter()
    svc = RecordingService(
        obs=object(), analysis=object(), session_repo=sr,
        result_repo=rr, daily_repo=dr,
        result_writer=spy_r, banner_writer=spy_b,
    )
    svc._handle_analysis(
        AnalysisResult(
            screen=ScreenType.PLAY, confidence=0.9, identified_chart=None,
            song_identification_failed=True, raw_song_text="??",
        )
    )
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    for _ in range(3):
        svc._handle_analysis(AnalysisResult(
            screen=ScreenType.RESULT, confidence=0.9, identified_chart=None,
            song_identification_failed=True,
            result_score=50000, result_clear_type="CLEAR",
        ), frame=frame)
    # 自動スクショは検出失敗でも保存（title=None なので unknown）
    assert spy_r.calls == [(None, 50000)]
    # バナーは保存しない
    assert spy_b.calls == []


def test_set_result_capture_propagates_to_writer() -> None:
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    states: list[bool] = []

    class W:
        def is_enabled(self): return False
        def set_enabled(self, enabled): states.append(enabled)
        def set_output_dir(self, output_dir): ...
        def save(self, *a, **kw): ...

    svc = RecordingService(
        obs=object(), analysis=object(), session_repo=sr,
        result_repo=rr, daily_repo=dr, result_writer=W(),
    )
    svc.set_result_capture(True)
    svc.set_result_capture(False)
    assert states == [True, False]
