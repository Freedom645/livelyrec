"""IT-REC: recording_service メインループの結合テスト。

`RecordingService` の実スレッド（同期ポーリングループ）を起動し、フェイク OBS から
供給される PNG フレーム列に対して「OBS取得 → デコード → 分析 → 記録」の
連結が動作することを検証する。

- IT-REC-01: 実パイプライン＋実リポジトリでの記録（フルスタック）
- IT-REC-02: リトライ検出がループ経由でリポジトリへ伝播
- IT-REC-03: OBS 切断 → 再接続シーケンス
- IT-REC-04: セッション無しのリザルト観測 → スキップ
- IT-REC-05: ソース名未設定でも暴走しない（I-011 回帰）
- IT-REC-06: 再接続が有界（接続嵐を起こさない / I-010 回帰）
"""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from livelyrec.application.analysis_service import AnalysisResult, AnalysisService
from livelyrec.application.master_service import MasterService
from livelyrec.application.recording_service import RecordingService
from livelyrec.domain.master import Song, normalize_song_title
from livelyrec.domain.score import Chart, Difficulty, PlaySession
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.ocr.base import OcrItem
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline
from livelyrec.infrastructure.recognizer.roi_defs import SCREEN_SIGNATURE_ROI
from livelyrec.infrastructure.repository import (
    ChartRepository,
    DailyCounterRepository,
    PlaySessionRepository,
    ResultRepository,
    SongRepository,
    open_database,
)
from livelyrec.shared.exceptions import ObsConnectionError

pytestmark = pytest.mark.integration

_CHART = Chart(song_id="x", title="t", difficulty=Difficulty.HYPER, level=30)


# ---- 補助 ----

def _wait_for(predicate, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _encode_png(bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", bgr)
    assert ok
    return buf.tobytes()


def _play_png() -> bytes:
    hsv = np.zeros((768, 1366, 3), dtype=np.uint8)
    x1, y1, x2, y2 = SCREEN_SIGNATURE_ROI
    hsv[y1:y2, x1:x2] = (59, 200, 200)  # PLAY シグネチャ
    return _encode_png(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))


def _result_png() -> bytes:
    hsv = np.zeros((768, 1366, 3), dtype=np.uint8)
    x1, y1, x2, y2 = SCREEN_SIGNATURE_ROI
    hsv[y1:y2, x1:x2] = (6, 200, 150)        # 赤系シグネチャ
    hsv[674:689, 1309:1324] = (6, 200, 255)  # 「8」点灯 → RESULT
    hsv[736:751, 1288:1303] = (6, 200, 40)
    return _encode_png(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))


def _blank_png() -> bytes:
    return _encode_png(np.zeros((120, 120, 3), dtype=np.uint8))


# ---- フェイク（obs_client と同じ同期インターフェイス） ----

class FakeOBS:
    """事前に用意した PNG フレーム列を順に返す同期フェイク OBS。"""

    def __init__(self, frames: list[bytes], source_name: str = "popn-source") -> None:
        self._frames = frames
        self._idx = 0
        self.connect_count = 0
        self.disconnect_count = 0
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def connect(self) -> None:
        self.connect_count += 1

    def disconnect(self) -> None:
        self.disconnect_count += 1

    def get_source_screenshot_png(self, *args, **kwargs) -> bytes:  # noqa: ARG002
        frame = self._frames[min(self._idx, len(self._frames) - 1)]
        self._idx += 1
        return frame


class FlakyOBS:
    """指定回数目の取得で一度だけ切断例外を投げる同期フェイク OBS。"""

    def __init__(self, frame: bytes, fail_at: int = 3, source_name: str = "popn-source") -> None:
        self._frame = frame
        self._fail_at = fail_at
        self._calls = 0
        self._failed = False
        self.connect_count = 0
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def connect(self) -> None:
        self.connect_count += 1

    def disconnect(self) -> None:
        pass

    def get_source_screenshot_png(self, *args, **kwargs) -> bytes:  # noqa: ARG002
        self._calls += 1
        if self._calls == self._fail_at and not self._failed:
            self._failed = True
            raise ObsConnectionError("simulated disconnect")
        return self._frame


class AlwaysDisconnectingOBS:
    """取得が常に切断例外になる同期フェイク OBS（再接続の有界性検証用）。"""

    def __init__(self, source_name: str = "popn-source") -> None:
        self.connect_count = 0
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def connect(self) -> None:
        self.connect_count += 1

    def disconnect(self) -> None:
        pass

    def get_source_screenshot_png(self, *args, **kwargs) -> bytes:  # noqa: ARG002
        raise ObsConnectionError("always disconnected")


class FakeOcr:
    def recognize(self, image_bgr):  # noqa: ARG002
        return [OcrItem("テスト楽曲", 0.9, ())]

    def recognize_text(self, image_bgr):  # noqa: ARG002
        return "CLEAR 90000"


class FakeDigit:
    def recognize(self, roi, judge):  # noqa: ARG002
        return "", 0.0

    def recognize_rightmost(self, roi, judge, count):  # noqa: ARG002
        return "", 0.0


class ScriptedAnalysis:
    """analyze() が台本どおりの AnalysisResult を順に返すフェイク。"""

    def __init__(self, results: list[AnalysisResult]) -> None:
        self._results = results
        self._idx = 0

    def analyze(self, frame_bgr) -> AnalysisResult:  # noqa: ARG002
        r = self._results[min(self._idx, len(self._results) - 1)]
        self._idx += 1
        return r


class FakeSessionRepo:
    def __init__(self) -> None:
        self.created: list[PlaySession] = []
        self.retries: list[tuple] = []
        self.attempts: list[str] = []
        self.statuses: list[tuple] = []

    def create(self, chart, started_at, business_date, **kwargs):  # noqa: ARG002
        sess = PlaySession(
            session_id=f"s{len(self.created) + 1}",
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

    def add(self, business_date, judgements):
        self.adds.append((business_date, judgements))
        return judgements


def _select_result() -> AnalysisResult:
    return AnalysisResult(screen=ScreenType.SELECT, confidence=0.9)


# ---- IT-REC-01: フルスタック記録 ----

def test_it_rec_01_full_loop_records_result(tmp_path) -> None:
    conn = open_database(tmp_path / "it_rec.sqlite3")
    try:
        song_repo = SongRepository(conn)
        chart_repo = ChartRepository(conn)
        song_repo.upsert(
            Song(
                song_id="popn-test",
                title="テスト楽曲",
                title_norm=normalize_song_title("テスト楽曲"),
                genre=None,
                has_upper=False,
                charts=(
                    Chart(
                        song_id="popn-test",
                        title="テスト楽曲",
                        difficulty=Difficulty.HYPER,
                        level=40,
                    ),
                ),
            )
        )
        master = MasterService(song_repo, chart_repo, fetcher=None)
        pipeline = RecognitionPipeline(FakeOcr(), FakeDigit())
        analysis = AnalysisService(pipeline, StateMachine(), master)
        session_repo = PlaySessionRepository(conn)
        result_repo = ResultRepository(conn)
        daily_repo = DailyCounterRepository(conn)

        obs = FakeOBS([_play_png()] * 8 + [_result_png()] * 40)
        service = RecordingService(
            obs, analysis, session_repo, result_repo, daily_repo, fps=60
        )
        service.start()
        try:
            # list_recent は IN_PROGRESS（result 未記録）のセッションも含むため、
            # 「score が記録された」を待ち条件にする。
            recorded = _wait_for(
                lambda: any(
                    e.score is not None for e in result_repo.list_recent(5)
                ),
                timeout=10.0,
            )
        finally:
            service.stop()

        assert recorded, "リザルトが記録されなかった"
        recent = [e for e in result_repo.list_recent(5) if e.score is not None]
        assert recent
        assert recent[0].score == 90000
    finally:
        conn.close()


# ---- IT-REC-02: リトライ伝播 ----

def test_it_rec_02_retry_propagates_through_loop() -> None:
    results = [
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART),
        AnalysisResult(
            screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART,
            retry_detected=True,
        ),
        AnalysisResult(screen=ScreenType.PLAY, confidence=0.9, identified_chart=_CHART),
    ]
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    service = RecordingService(
        FakeOBS([_blank_png()] * 200), ScriptedAnalysis(results), sr, rr, dr, fps=60
    )
    service.start()
    try:
        ok = _wait_for(lambda: len(sr.retries) > 0, timeout=10.0)
    finally:
        service.stop()
    assert ok, "リトライがリポジトリへ伝播しなかった"
    assert len(sr.created) == 1
    assert len(sr.attempts) >= 1


# ---- IT-REC-03: 切断 → 再接続 ----

def test_it_rec_03_reconnects_after_obs_disconnect() -> None:
    obs = FlakyOBS(_blank_png(), fail_at=3)
    service = RecordingService(
        obs, ScriptedAnalysis([_select_result()]),
        FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo(), fps=60,
    )
    service.start()
    try:
        ok = _wait_for(lambda: obs.connect_count >= 2, timeout=15.0)
    finally:
        service.stop()
    assert ok, "OBS 切断後の再接続が行われなかった"


# ---- IT-REC-04: セッション無しのリザルト → スキップ ----

def test_it_rec_04_result_without_session_is_skipped() -> None:
    results = [
        AnalysisResult(
            screen=ScreenType.RESULT, confidence=0.9,
            result_score=80000, result_clear_type="CLEAR",
        )
    ]
    sr, rr, dr = FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo()
    service = RecordingService(
        FakeOBS([_blank_png()] * 200), ScriptedAnalysis(results), sr, rr, dr, fps=60
    )
    events: list[dict] = []
    service.add_listener(events.append)
    service.start()
    try:
        ok = _wait_for(
            lambda: any(e["type"] == "result.skipped" for e in events), timeout=10.0
        )
    finally:
        service.stop()
    assert ok, "result.skipped イベントが発火しなかった"
    assert rr.upserts == []


# ---- IT-REC-05: ソース名未設定でも暴走しない（I-011 回帰） ----

def test_it_rec_05_unconfigured_source_does_not_storm() -> None:
    obs = FakeOBS([_blank_png()], source_name="")  # ソース名未設定
    service = RecordingService(
        obs, ScriptedAnalysis([_select_result()]),
        FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo(), fps=60,
    )
    events: list[dict] = []
    service.add_listener(events.append)
    service.start()
    try:
        ok = _wait_for(
            lambda: any(e["type"] == "error" for e in events), timeout=5.0
        )
    finally:
        service.stop()
    assert ok, "ソース名未設定のエラーが通知されなかった"
    # 事前検証で弾かれ、OBS への接続は一度も行われない（接続嵐が起きない）
    assert obs.connect_count == 0
    err = next(e for e in events if e["type"] == "error")
    assert err["payload"]["code"] == "NO_SOURCE"


# ---- IT-REC-06: 再接続が有界（I-010 回帰） ----

def test_it_rec_06_reconnect_is_bounded() -> None:
    obs = AlwaysDisconnectingOBS()
    service = RecordingService(
        obs, ScriptedAnalysis([_select_result()]),
        FakeSessionRepo(), FakeResultRepo(), FakeDailyRepo(), fps=60,
    )
    events: list[dict] = []
    service.add_listener(events.append)
    service.start()
    try:
        ok = _wait_for(
            lambda: any(e["type"] == "error" for e in events), timeout=20.0
        )
    finally:
        service.stop()
    assert ok, "接続嵐防止のエラーで停止しなかった"
    # 再接続回数が有界（無限再帰・接続嵐ではない）
    assert obs.connect_count <= 8
