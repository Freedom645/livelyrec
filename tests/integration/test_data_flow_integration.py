"""IT-PIPE / IT-MASTER / IT-EXPORT: データフロー連結の結合テスト。

- IT-PIPE-01 : pipeline → analysis_service 連結（合成フレーム）
- IT-MASTER-01: MasterFetcher（実 HTTP GET）→ refresh → DB → identify
- IT-MASTER-02: マスタ取得失敗時のキャッシュフォールバック
- IT-EXPORT-01: repository → ExportService（CSV 出力）連結
"""

from __future__ import annotations

import functools
import http.server
import json
import socket
import threading
from datetime import UTC, date, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from livelyrec.application.analysis_service import AnalysisService
from livelyrec.application.export_service import ExportService
from livelyrec.application.master_service import MasterService
from livelyrec.domain.master import Song, normalize_song_title
from livelyrec.domain.score import (
    Chart,
    ClearType,
    Difficulty,
    Judgements,
    Medal,
    Rank,
    Result,
)
from livelyrec.domain.state import ScreenType, StateMachine
from livelyrec.infrastructure.github_client import MasterFetcher
from livelyrec.infrastructure.ocr.base import OcrItem
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline
from livelyrec.infrastructure.recognizer.roi_defs import SCREEN_SIGNATURE_ROI
from livelyrec.infrastructure.repository import (
    ChartRepository,
    PlaySessionRepository,
    ResultRepository,
    SongRepository,
    open_database,
)
from livelyrec.shared.exceptions import MasterFetchError

pytestmark = pytest.mark.integration


# ---- 補助 ----

def _signature_bgr(hue: int, *, result: bool = False) -> np.ndarray:
    hsv = np.zeros((768, 1366, 3), dtype=np.uint8)
    x1, y1, x2, y2 = SCREEN_SIGNATURE_ROI
    hsv[y1:y2, x1:x2] = (hue, 200, 150 if result else 200)
    if result:
        hsv[674:689, 1309:1324] = (hue, 200, 255)
        hsv[736:751, 1288:1303] = (hue, 200, 40)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _FakeOcr:
    def recognize(self, image_bgr):  # noqa: ARG002
        return [OcrItem("テスト楽曲", 0.9, ())]

    def recognize_text(self, image_bgr):  # noqa: ARG002
        return "CLEAR 90000"


class _FakeDigit:
    def recognize(self, roi, judge):  # noqa: ARG002
        return "", 0.0

    def recognize_rightmost(self, roi, judge, count):  # noqa: ARG002
        return "", 0.0


def _seed_song(conn) -> None:
    SongRepository(conn).upsert(
        Song(
            song_id="popn-test",
            title="テスト楽曲",
            title_norm=normalize_song_title("テスト楽曲"),
            genre=None,
            has_upper=False,
            charts=(
                Chart(song_id="popn-test", title="テスト楽曲",
                      difficulty=Difficulty.HYPER, level=40),
            ),
        )
    )


# ---- IT-PIPE-01: pipeline → analysis_service ----

def test_it_pipe_01_pipeline_to_analysis(tmp_path: Path) -> None:
    conn = open_database(tmp_path / "it_pipe.sqlite3")
    try:
        _seed_song(conn)
        master = MasterService(SongRepository(conn), ChartRepository(conn), fetcher=None)
        pipeline = RecognitionPipeline(_FakeOcr(), _FakeDigit())
        analysis = AnalysisService(pipeline, StateMachine(), master)

        # PLAY フレーム → 画面判別・楽曲特定までが連結して伝播する
        play = analysis.analyze(_signature_bgr(59))
        assert play.screen == ScreenType.PLAY
        assert play.identified_chart is not None
        assert play.identified_chart.song_id == "popn-test"

        # RESULT フレーム → リザルトメトリクスが伝播する
        result = analysis.analyze(_signature_bgr(6, result=True))
        assert result.screen == ScreenType.RESULT
        assert result.result_score == 90000
        assert result.result_clear_type == "CLEAR"
    finally:
        conn.close()


# ---- IT-MASTER-01: MasterFetcher → refresh → identify ----

def test_it_master_01_fetch_refresh_identify(tmp_path: Path) -> None:
    # ローカル HTTP サーバで master.json を配信
    master_data = {
        "songs": [
            {"song_id": "m1", "title": "結合テスト楽曲アルファ",
             "charts": [{"difficulty": "HYPER", "level": 35}]},
            {"song_id": "m2", "title": "結合テスト楽曲ベータ",
             "charts": [{"difficulty": "EX", "level": 45}]},
        ]
    }
    serve_dir = tmp_path / "www"
    serve_dir.mkdir()
    (serve_dir / "master.json").write_text(
        json.dumps(master_data, ensure_ascii=False), encoding="utf-8"
    )
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(serve_dir)
    )
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    conn = open_database(tmp_path / "it_master.sqlite3")
    try:
        fetcher = MasterFetcher(
            endpoint_url=f"http://127.0.0.1:{port}/master.json",
            cache_path=tmp_path / "cache" / "master_cache.json",
        )
        service = MasterService(
            SongRepository(conn), ChartRepository(conn), fetcher=fetcher
        )
        count = service.refresh()
        assert count == 2

        identified = service.identify("結合テスト楽曲アルファ")
        assert identified.accepted
        assert identified.chart is not None
        assert identified.chart.song_id == "m1"
    finally:
        conn.close()
        httpd.shutdown()
        thread.join(timeout=3.0)


# ---- IT-MASTER-02: 取得失敗時のキャッシュフォールバック ----

def test_it_master_02_falls_back_to_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "master_cache.json"
    cached = {"songs": [{"song_id": "c1", "title": "キャッシュ楽曲",
                         "charts": [{"difficulty": "HYPER", "level": 30}]}]}
    cache_path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")

    # 接続先なしのポート → 取得失敗 → キャッシュへフォールバック
    dead_url = f"http://127.0.0.1:{_free_port()}/master.json"
    fetcher = MasterFetcher(endpoint_url=dead_url, cache_path=cache_path)
    data = fetcher.fetch(timeout=2.0)
    assert data == cached


def test_it_master_02b_raises_when_no_cache(tmp_path: Path) -> None:
    # キャッシュも無い状態での取得失敗 → MasterFetchError
    dead_url = f"http://127.0.0.1:{_free_port()}/master.json"
    fetcher = MasterFetcher(
        endpoint_url=dead_url, cache_path=tmp_path / "absent_cache.json"
    )
    with pytest.raises(MasterFetchError):
        fetcher.fetch(timeout=2.0)


# ---- IT-EXPORT-01: repository → ExportService ----

def test_it_export_01_repository_to_csv(tmp_path: Path) -> None:
    conn = open_database(tmp_path / "it_export.sqlite3")
    try:
        SongRepository(conn).upsert(
            Song(
                song_id="e1",
                title="エクスポート楽曲",
                title_norm=normalize_song_title("エクスポート楽曲"),
                genre=None,
                has_upper=False,
                charts=(
                    Chart(song_id="e1", title="エクスポート楽曲",
                          difficulty=Difficulty.HYPER, level=30),
                ),
            )
        )
        chart = ChartRepository(conn).get("e1:HYPER:0")
        assert chart is not None
        session_repo = PlaySessionRepository(conn)
        result_repo = ResultRepository(conn)
        started = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
        for i in range(2):
            sess = session_repo.create(
                chart=chart, started_at=started, business_date=date(2026, 5, 20)
            )
            result_repo.upsert(
                sess.session_id,
                Result(
                    score=80000 + i,
                    judgements=Judgements(100, 5, 2, 1),
                    combo=200,
                    clear_type=ClearType.CLEAR,
                    medal=Medal.CIRCLE,
                    rank=Rank.AA,
                    best_score_diff=None,
                ),
                started,
            )

        out = tmp_path / "export.csv"
        count = ExportService(result_repo).export_all(out)
        assert count == 2
        lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
        assert len(lines) == 3  # ヘッダ + 2 行
        assert lines[0].startswith("business_date")
    finally:
        conn.close()
