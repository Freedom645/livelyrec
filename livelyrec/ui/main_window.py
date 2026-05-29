"""メインウィンドウ。

詳細: docs/design/09_詳細設計_UI設計.md §2
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from livelyrec.application.export_service import CsvOptions, ExportService
from livelyrec.application.recording_service import RecordingService
from livelyrec.application.update_service import UpdateService
from livelyrec.infrastructure.config_store import AppSettings, ConfigStore
from livelyrec.infrastructure.obs_client import OBSClient, ObsConfig
from livelyrec.shared.network import resolve_advertised_host
from livelyrec.ui.settings_dialog import SettingsDialog
from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel
from livelyrec.ui.widgets.broadcast_url_panel import BroadcastUrlPanel
from livelyrec.ui.widgets.connection_panel import ConnectionPanel
from livelyrec.ui.widgets.daily_counter_panel import DailyCounterPanel
from livelyrec.ui.widgets.recent_results_panel import RecentResultsPanel
from livelyrec.ui.widgets.record_status_panel import RecordStatusPanel


class MainWindow(QMainWindow):
    def __init__(
        self,
        recording: RecordingService,
        config_store: ConfigStore,
        settings: AppSettings,
        export_service: ExportService,
        update_service: UpdateService,
        logs_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("LivelyRec")
        self.resize(900, 600)

        self._recording = recording
        self._config = config_store
        self._settings = settings
        self._export = export_service
        self._update = update_service
        self._logs_dir = logs_dir

        self._vm = RecordingViewModel(self)
        # Service → VM の橋渡し。post_event がワーカースレッドから
        # メインスレッドへスレッド安全にイベントを渡す。
        self._recording.add_listener(self._vm.post_event)
        self._vm.error_occurred.connect(self._on_error)

        self._conn_panel = ConnectionPanel(
            self._vm, self._on_start, self._on_stop, self._on_settings, self
        )
        self._status_panel = RecordStatusPanel(self._vm, self)
        self._daily_panel = DailyCounterPanel(
            self._vm, settings.recording.business_day_rollover_hour, self
        )
        self._recent_panel = RecentResultsPanel(self._vm, parent=self)
        self._url_panel = BroadcastUrlPanel(self._build_browser_urls(settings), self)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        top = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()
        left.addWidget(self._conn_panel)
        left.addWidget(self._status_panel)
        left.addWidget(self._url_panel)
        left.addStretch(1)
        right.addWidget(self._daily_panel)
        right.addWidget(self._recent_panel)
        top.addLayout(left, stretch=3)
        top.addLayout(right, stretch=2)
        outer.addLayout(top)

        self.setCentralWidget(central)
        self._setup_menus()
        self._setup_statusbar()

    # ---- メニュー ----
    def _setup_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("ファイル(&F)")
        act_export = QAction("CSV エクスポート(&E)…", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._on_export)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_quit = QAction("終了(&X)", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        rec_menu = bar.addMenu("記録(&R)")
        act_start = QAction("記録開始(&S)", self)
        act_start.setShortcut(QKeySequence("Ctrl+S"))
        act_start.triggered.connect(self._on_start)
        rec_menu.addAction(act_start)
        act_stop = QAction("記録停止(&P)", self)
        act_stop.setShortcut(QKeySequence("Ctrl+P"))
        act_stop.triggered.connect(self._on_stop)
        rec_menu.addAction(act_stop)

        tools_menu = bar.addMenu("ツール(&T)")
        act_settings = QAction("設定(&O)…", self)
        act_settings.triggered.connect(self._on_settings)
        tools_menu.addAction(act_settings)
        act_check_update = QAction("アップデートを確認(&U)", self)
        act_check_update.triggered.connect(self._on_check_update)
        tools_menu.addAction(act_check_update)
        act_open_logs = QAction("ログフォルダを開く(&L)", self)
        act_open_logs.triggered.connect(self._open_logs_folder)
        tools_menu.addAction(act_open_logs)

        help_menu = bar.addMenu("ヘルプ(&H)")
        act_about = QAction("バージョン情報(&A)…", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)

    def _setup_statusbar(self) -> None:
        sb = QStatusBar(self)
        sb.showMessage("Ready")
        self.setStatusBar(sb)

    # ---- 操作ハンドラ ----
    def _on_start(self) -> None:
        self._recording.start()

    def _on_stop(self) -> None:
        self._recording.stop()

    def _on_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self, source_fetcher=self._fetch_obs_sources)
        if dlg.exec() == SettingsDialog.Accepted:
            self._settings = dlg.to_settings()
            self._config.save(self._settings)
            # 即時反映できる設定はここで適用する（デバッグ撮影、自動スクショ、開発者バナー）
            self._recording.set_debug_capture(self._settings.recording.debug_capture)
            self._recording.set_result_capture(
                self._settings.result_capture.enabled,
                Path(self._settings.result_capture.output_dir)
                if self._settings.result_capture.output_dir
                else None,
            )
            self._recording.set_banner_capture(
                self._settings.developer.banner_capture_enabled,
                Path(self._settings.developer.banner_dir)
                if self._settings.developer.banner_dir
                else None,
            )
            QMessageBox.information(
                self,
                "設定保存",
                "設定を保存しました。一部の項目はアプリ再起動後に反映されます。",
            )

    def _build_browser_urls(self, settings: AppSettings) -> dict[str, str]:
        """配信支援ブラウザソースの 4 URL を構築する。"""
        adv_host = resolve_advertised_host(
            settings.websocket_server.host,
            settings.websocket_server.lan_publish,
        )
        port = settings.websocket_server.port
        suffix = ""
        if settings.websocket_server.lan_publish and settings.websocket_server.token:
            suffix = f"?token={settings.websocket_server.token}"

        def _u(path: str) -> str:
            return f"http://{adv_host}:{port}/browser/{path}/{suffix}"

        return {
            "打鍵数カウンタ": _u("keycount"),
            "現在のプレイ楽曲": _u("now-playing"),
            "選曲中の楽曲のスコア履歴 (v1.x はプレースホルダ実装)": _u(
                "now-playing-history"
            ),
            "直近 10 件のプレイ履歴": _u("recent"),
        }

    def _fetch_obs_sources(self, host: str, port: int, password: str) -> list[str]:
        """設定ダイアログからの要求で OBS の入力ソース一覧を取得する。"""
        probe = OBSClient(
            ObsConfig(host=host, port=port, password=password, source_name="")
        )
        probe.connect()
        try:
            return probe.list_sources()
        finally:
            probe.disconnect()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV エクスポート", "livelyrec_export.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            n = self._export.export_all(Path(path), CsvOptions())
            QMessageBox.information(self, "エクスポート完了", f"{n} 件を出力しました。")
        except Exception as e:
            QMessageBox.warning(self, "エクスポート失敗", str(e))

    def _on_check_update(self) -> None:
        result = self._update.check()
        if result.error:
            QMessageBox.information(self, "アップデート", f"確認に失敗しました: {result.error}")
            return
        if result.has_update and result.latest is not None:
            QMessageBox.information(
                self,
                "新しいバージョン",
                f"v{result.current_version} → {result.latest.tag_name}\n"
                f"{result.latest.html_url}",
            )
        else:
            QMessageBox.information(self, "アップデート", "最新版を使用しています。")

    def _open_logs_folder(self) -> None:
        import os
        import sys
        path = str(self._logs_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            QMessageBox.warning(self, "失敗", str(e))

    def _on_about(self) -> None:
        # v2.0: バナー画像参照元の出典属性表示と免責表示を含む AboutDialog を使用
        # （FR-BAN-008）。リッチテキスト対応のため独立ダイアログ。
        from livelyrec.ui.about_dialog import AboutDialog
        AboutDialog(self).exec()

    # ---- エラー表示 ----
    @Slot(dict)
    def _on_error(self, payload: dict) -> None:
        QMessageBox.warning(
            self,
            "記録エラー",
            str(payload.get("message", "不明なエラーが発生しました。")),
        )

    # ---- 終了処理 ----
    def closeEvent(self, event) -> None:  # noqa: N802
        self._recording.stop()
        event.accept()
