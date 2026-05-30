"""LivelyRec エントリポイント。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §8
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from livelyrec.shared.diagnostics import MemoryMonitor
from livelyrec.shared.exceptions import DataFolderNotWritableError
from livelyrec.shared.logging_setup import setup_logging
from livelyrec.shared.paths import AppPaths, ensure_data_folder_writable


def _bootstrap_std_streams() -> None:
    """PyInstaller --windowed ビルドでは sys.stdout / sys.stderr が None になり、
    PaddleOCR の `maybe_download` から呼ばれる tqdm 等が `.write` で AttributeError
    を起こす（I-020）。最低限の代替として `os.devnull` を割り当てる。

    logs_dir が確定したら `_redirect_std_streams_to_file()` でファイルへ
    再リダイレクトする（記録中クラッシュの abort メッセージ等を保存するため）。
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _redirect_std_streams_to_file(logs_dir: Path) -> None:
    """`_bootstrap_std_streams()` の devnull 仮割当を、ファイル出力に差し替える。

    PaddleOCR / paddle / OpenCV 等の C 拡張は stderr に直接 `fprintf` で abort
    メッセージや warn を吐く。これらを取り逃すと、記録中の致命エラーの真因
    （セグフォルト・アサート失敗等）が一切記録に残らない（I-024）。
    """
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = logs_dir / "stdout.log"
        stderr_path = logs_dir / "stderr.log"
        # devnull で開いていた既存ストリームは閉じてから差し替える
        if sys.stdout is not None and getattr(sys.stdout, "name", "") == os.devnull:
            try:
                sys.stdout.close()
            except OSError:
                pass
            sys.stdout = open(stdout_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        if sys.stderr is not None and getattr(sys.stderr, "name", "") == os.devnull:
            try:
                sys.stderr.close()
            except OSError:
                pass
            sys.stderr = open(stderr_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        # ファイル作成に失敗しても起動は継続する
        pass


def _install_faulthandler(logs_dir: Path) -> None:
    """C 拡張のセグフォルト・アサート失敗をスタックトレース付きでダンプする。

    `faulthandler` は SIGSEGV / SIGABRT 等を捕まえて、全スレッドの C/Python の
    スタックを指定ファイルへ書き出す。Python 例外システムを通らないクラッシュ
    （PaddleOCR / OpenCV のネイティブクラッシュ等）の唯一の手がかりになる。
    """
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh_file = (logs_dir / "faulthandler.log").open("a", encoding="utf-8")
        faulthandler.enable(file=fh_file, all_threads=True)
    except OSError:
        pass


def _install_thread_excepthook() -> None:
    """ワーカースレッド内の未捕捉例外を logger.critical に流す。

    `sys.excepthook` はメインスレッドの未捕捉例外しか受け取らない。
    記録ループ・WS サーバスレッド・更新チェックスレッド等で例外が起きると
    Python 3.8+ では `threading.excepthook` 経由で stderr に出るが、UI が
    生存しているとユーザは気付けないため明示的にログへ。
    """
    log = logging.getLogger("livelyrec")

    def _hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.critical(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _hook


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


def _build_banner_match_service(
    settings,
    paths: AppPaths,
    logger: logging.Logger,
    *,
    fetcher_cls,
    service_cls,
    load_error,
    fetch_error,
):
    """v2.0 バナー特徴量マッチサービスを組み立てる（FR-BAN-001〜004）。

    優先順:
    1. ユーザ設定で `banner.match_enabled=False` → None（機能無効）
    2. `banner.endpoint_url` 設定時はそこから取得（ETag 差分対応）
    3. 取得失敗時はローカルキャッシュ（`banner_features_cache_file`）
    4. それも無ければ同梱 seed（`banner_features_seed_file`）
    5. seed も無ければ None（機能無効）

    失敗・パースエラーは WARN ログのみで、本体起動はブロックしない（FR-BAN-001）。
    """
    if not settings.banner.match_enabled:
        logger.info("banner match disabled by config")
        return None
    fetcher = None
    if settings.banner.endpoint_url:
        fetcher = fetcher_cls(
            endpoint_url=settings.banner.endpoint_url,
            cache_path=paths.banner_features_cache_file,
        )
        try:
            fetcher.fetch()
            logger.info(
                "banner features fetched/refreshed from %s",
                settings.banner.endpoint_url,
            )
        except fetch_error:
            logger.warning(
                "banner features fetch failed; falling back to cache/seed",
                exc_info=True,
            )
    candidate_paths = []
    if settings.banner.endpoint_url:
        candidate_paths.append(paths.banner_features_cache_file)
    candidate_paths.append(paths.banner_features_seed_file)
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            svc = service_cls.from_json(path)
            logger.info(
                "banner match service ready: %d features from %s",
                svc.feature_count,
                path,
            )
            return svc
        except load_error:
            logger.warning("banner features load failed: %s", path, exc_info=True)
    logger.info("banner features unavailable; 2nd identifier disabled")
    return None


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
    _bootstrap_std_streams()
    paths = AppPaths.detect()
    try:
        ensure_data_folder_writable(paths)
    except DataFolderNotWritableError as e:
        _show_data_folder_error(paths, str(e))
        return 1

    # logs_dir 確定後に診断系を仕込む。記録中の致命エラーの手がかりを
    # livelyrec_data/logs/{stderr.log, faulthandler.log} および crash/ に残す。
    _redirect_std_streams_to_file(paths.logs_dir)
    _install_faulthandler(paths.logs_dir)
    logger = setup_logging(paths.logs_dir)
    _install_excepthook(paths)
    _install_thread_excepthook()
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
    from livelyrec.application.banner_match_service import (
        BannerFeaturesLoadError,
        BannerMatchService,
    )
    from livelyrec.application.export_service import ExportService
    from livelyrec.application.master_service import MasterService
    from livelyrec.application.recording_service import RecordingService
    from livelyrec.application.update_service import UpdateService
    from livelyrec.domain.state import StateMachine
    from livelyrec.infrastructure.github_client import (
        BannerFeaturesFetcher,
        GitHubClient,
        MasterFetcher,
    )
    from livelyrec.infrastructure.obs_client import OBSClient, ObsConfig
    from livelyrec.shared.exceptions import BannerFeaturesFetchError

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
    # バナー特徴量マスタの取得とサービス組み立て（FR-BAN-001〜004、v2.0）。
    # 取得失敗・パース失敗・設定 OFF いずれも 2 次認識器を無効化して既存処理で継続。
    banner_match = _build_banner_match_service(
        settings, paths, logger,
        fetcher_cls=BannerFeaturesFetcher,
        service_cls=BannerMatchService,
        load_error=BannerFeaturesLoadError,
        fetch_error=BannerFeaturesFetchError,
    )

    # SELECT 画面の UPPER 譜面検出用テンプレ（FR-BAN-002、v2.0）。
    # 同梱配布物（templates/select/upper_mark.png）を読み込み。
    # 未配備時は None を渡し、UPPER 判定は常に False で動作する。
    upper_template = None
    upper_template_path = paths.templates_dir / "select" / "upper_mark.png"
    if upper_template_path.exists():
        try:
            from livelyrec.infrastructure.recognizer.select_screen import (
                load_upper_template,
            )
            upper_template = load_upper_template(upper_template_path)
            logger.info("upper template loaded: %s", upper_template_path)
        except Exception:
            logger.exception("upper template load failed; UPPER detection disabled")
    else:
        logger.info(
            "upper template not found at %s; UPPER detection disabled",
            upper_template_path,
        )

    state = StateMachine()
    analysis = AnalysisService(
        pipeline, state, master,
        banner_match=banner_match,
        upper_template=upper_template,
    )

    obs = OBSClient(ObsConfig(
        host=settings.obs.host,
        port=settings.obs.port,
        password=settings.obs.password,
        source_name=settings.obs.source_name,
    ))

    # 自動スクショ／開発者向けバナー画像の writer（FR-REC-046 / FR-DEV-002）
    from livelyrec.infrastructure.banner_writer import BannerWriter
    from livelyrec.infrastructure.filename_sanitizer import FilenameSanitizer
    from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI
    from livelyrec.infrastructure.result_writer import ResultWriter
    sanitizer = FilenameSanitizer()
    result_writer = ResultWriter(
        enabled=settings.result_capture.enabled,
        output_dir=Path(settings.result_capture.output_dir)
        if settings.result_capture.output_dir
        else paths.result_dir,
        sanitizer=sanitizer,
    )
    banner_writer = BannerWriter(
        enabled=settings.developer.banner_capture_enabled,
        output_dir=Path(settings.developer.banner_dir)
        if settings.developer.banner_dir
        else paths.banner_dir,
        banner_roi=RESULT_ROI["banner"],
        sanitizer=sanitizer,
    )

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
        result_writer=result_writer,
        banner_writer=banner_writer,
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

    # /browser/recent 用: DB 全履歴から最新 N 件（既定 10、許容 1〜50）（FR-STR-009）
    from livelyrec.application.recording_service import DETECTION_FAILED_LABEL

    def _on_recent_history(payload: dict) -> dict:
        request_id = payload.get("request_id")
        try:
            limit = int(payload.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(50, limit))
        entries = result_repo.list_recent(limit=limit)
        return {
            "request_id": request_id,
            "entries": [
                {
                    "session_id": e.session_id,
                    "started_at": e.started_at.isoformat(),
                    "chart_id": e.chart_id,
                    "display_title": e.song_title or DETECTION_FAILED_LABEL,
                    "difficulty": e.difficulty,
                    "level": e.level,
                    "score": e.score,
                    "clear_type": e.clear_type,
                    "rank": e.rank,
                    "medal": e.medal,
                }
                for e in entries
            ],
        }
    ws.register_request_handler("recent.history.request", _on_recent_history)

    # RecordingService → WebSocket への自動転送
    def _forward_to_ws(event: dict) -> None:
        ws.broadcast(event.get("type", ""), event.get("payload", {}) or {})
    recording.add_listener(_forward_to_ws)

    ws.start()

    # メモリ使用量の定期ロギングを開始（I-024/I-025 の手がかり収集）。
    # 60 秒ごとに自プロセス RSS / システム空きメモリを INFO ログへ。
    mem_monitor = MemoryMonitor(interval_sec=60.0)
    mem_monitor.start()

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
        mem_monitor.stop()
        ws.stop()
        try:
            conn.close()
        except Exception:
            pass
        logger.info("LivelyRec exited")


if __name__ == "__main__":
    sys.exit(main())
