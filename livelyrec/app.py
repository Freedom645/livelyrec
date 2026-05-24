"""LivelyRec エントリポイント。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §8
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime

from livelyrec.shared.exceptions import DataFolderNotWritableError
from livelyrec.shared.logging_setup import setup_logging
from livelyrec.shared.paths import AppPaths, ensure_data_folder_writable


def _show_data_folder_error(paths: AppPaths, message: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        _ = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "LivelyRec - データフォルダに書き込めません",
            (
                f"データフォルダ\n{paths.data_dir}\n"
                f"への書き込み権限がありません。\n\n"
                f"Program Files 配下や OneDrive 同期フォルダなど、書き込み制限の\n"
                f"ある場所にインストールされている可能性があります。\n\n"
                f"LivelyRec.exe ごとフォルダを、ドキュメントやデスクトップなどの\n"
                f"書き込み可能な場所に移動してから再度起動してください。\n\n"
                f"詳細: {message}"
            ),
        )
    except Exception:
        print(f"[fatal] {message}", file=sys.stderr)


def _install_excepthook(paths: AppPaths) -> None:
    def excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("livelyrec").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        try:
            paths.crash_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            crash_file = paths.crash_dir / f"crash_{stamp}.log"
            with crash_file.open("w", encoding="utf-8") as f:
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass

    sys.excepthook = excepthook


def main() -> int:
    paths = AppPaths.detect()
    try:
        ensure_data_folder_writable(paths)
    except DataFolderNotWritableError as e:
        _show_data_folder_error(paths, str(e))
        return 1

    logger = setup_logging(paths.logs_dir)
    _install_excepthook(paths)
    logger.info("LivelyRec starting, data_dir=%s", paths.data_dir)

    # 設定ロード
    from livelyrec.infrastructure.config_store import ConfigStore
    config_store = ConfigStore(paths.settings_file)
    settings = config_store.load()

    # DB と Repository
    from livelyrec.infrastructure.repository import (
        AppKvRepository,
        ChartRepository,
        DailyCounterRepository,
        PlaySessionRepository,
        ResultRepository,
        SongRepository,
        open_database,
    )
    conn = open_database(paths.db_file)
    song_repo = SongRepository(conn)
    chart_repo = ChartRepository(conn)
    session_repo = PlaySessionRepository(conn)
    result_repo = ResultRepository(conn)
    daily_repo = DailyCounterRepository(conn)
    _ = AppKvRepository(conn)

    # 認識パイプライン
    from livelyrec.infrastructure.ocr.digit_template import DigitTemplateRecognizer
    from livelyrec.infrastructure.ocr.paddle import PaddleOcrEngine
    from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline

    ocr = PaddleOcrEngine()
    try:
        ocr.warm_up()
    except Exception:
        logger.exception("OCR warm-up failed")
    digit = DigitTemplateRecognizer.load_from_dir(paths.templates_dir / "digits" / "1366x768")
    pipeline = RecognitionPipeline(
        ocr=ocr,
        digit_recognizer=digit,
        screen_signatures_path=paths.templates_dir / "screen_signatures.npz",
    )

    # サービス層
    from livelyrec.application.analysis_service import AnalysisService
    from livelyrec.application.export_service import ExportService
    from livelyrec.application.master_service import MasterService
    from livelyrec.application.recording_service import RecordingService
    from livelyrec.application.update_service import UpdateService
    from livelyrec.domain.state import StateMachine
    from livelyrec.infrastructure.github_client import GitHubClient, MasterFetcher
    from livelyrec.infrastructure.obs_client import OBSClient, ObsConfig

    master_fetcher = (
        MasterFetcher(
            endpoint_url=settings.master.endpoint_url,
            cache_path=paths.data_dir / "master.json",
        )
        if settings.master.endpoint_url
        else None
    )
    master = MasterService(song_repo, chart_repo, fetcher=master_fetcher)
    # 楽曲マスタを DB へ反映する（I-015）。
    # エンドポイント設定時は GitHub Pages 等から取得し最新を優先採用する。
    if master_fetcher is not None:
        try:
            refreshed = master.refresh()
            logger.info("master refreshed from endpoint: %d songs", refreshed)
        except Exception:
            logger.exception("master refresh failed; falling back to bundled seed/cache")
    # DB が空なら同梱の seed マスタを投入する（オフライン初回起動・未設定時の保険）。
    if master.song_count() == 0:
        if paths.master_seed_file.exists():
            try:
                seeded = master.load_from_file(paths.master_seed_file)
                logger.info("master seeded from bundled file: %d songs", seeded)
            except Exception:
                logger.exception("master seed load failed")
        else:
            logger.warning("master seed file not found: %s", paths.master_seed_file)
    state = StateMachine()
    analysis = AnalysisService(pipeline, state, master)

    obs = OBSClient(ObsConfig(
        host=settings.obs.host,
        port=settings.obs.port,
        password=settings.obs.password,
        source_name=settings.obs.source_name,
    ))

    recording = RecordingService(
        obs=obs,
        analysis=analysis,
        session_repo=session_repo,
        result_repo=result_repo,
        daily_repo=daily_repo,
        rollover_hour=settings.recording.business_day_rollover_hour,
        fps=settings.recording.fps,
        debug_dir=paths.debug_dir,
        debug_capture=settings.recording.debug_capture,
    )

    export = ExportService(result_repo)
    github = GitHubClient(owner="OWNER", repo="livelyrec")  # TODO: 実リポジトリ名を反映
    from livelyrec import __version__
    update = UpdateService(github, current_version=__version__)

    # WebSocket Server
    from livelyrec.infrastructure.ws_server import WebSocketServer, WsServerConfig
    ws_cfg = WsServerConfig(
        host=settings.websocket_server.host,
        port=settings.websocket_server.port,
        lan_publish=settings.websocket_server.lan_publish,
        token=settings.websocket_server.token,
    )
    ws = WebSocketServer(ws_cfg, browser_source_dir=paths.browser_source_dir)

    def _on_chart_history(payload: dict) -> dict:
        chart_id = payload.get("chart_id")
        limit = int(payload.get("limit", 5))
        request_id = payload.get("request_id")
        if not chart_id:
            return {"request_id": request_id, "error": "chart_id required"}
        history = result_repo.list_by_chart(chart_id, limit=limit)
        return {
            "request_id": request_id,
            "chart_id": chart_id,
            "best_score": result_repo.best_score(chart_id),
            "history": [
                {
                    "session_id": sid,
                    "recorded_at": started.isoformat(),
                    "score": r.score,
                    "clear_type": r.clear_type.value,
                    "rank": r.rank.value,
                    "medal": r.medal.value,
                    "combo": r.combo,
                    "judgements": {
                        "cool": r.judgements.cool,
                        "great": r.judgements.great,
                        "good": r.judgements.good,
                        "bad": r.judgements.bad,
                    },
                }
                for sid, started, r in history
            ],
        }
    ws.register_request_handler("chart.history.request", _on_chart_history)

    # RecordingService → WebSocket への自動転送
    def _forward_to_ws(event: dict) -> None:
        ws.broadcast(event.get("type", ""), event.get("payload", {}) or {})
    recording.add_listener(_forward_to_ws)

    ws.start()

    # UI 起動
    from PySide6.QtWidgets import QApplication

    from livelyrec.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(
        recording=recording,
        config_store=config_store,
        settings=settings,
        export_service=export,
        update_service=update,
        logs_dir=paths.logs_dir,
    )
    window.show()

    # 起動直後に現在の日次カウンタを通知（パネル・ブラウザソースの初期表示用）。
    # これが無いと最初のリザルトが出るまでカウンタが 0 のまま表示される。
    recording.emit_state_snapshot()

    if settings.update.check_on_startup:
        def _on_update_done(result):
            if result.has_update and result.latest is not None:
                logger.info("update available: %s", result.latest.tag_name)
        update.check_async(_on_update_done)

    try:
        return app.exec()
    finally:
        ws.stop()
        try:
            conn.close()
        except Exception:
            pass
        logger.info("LivelyRec exited")


if __name__ == "__main__":
    sys.exit(main())
