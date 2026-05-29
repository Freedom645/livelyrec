"""アプリ設定ダイアログ。

詳細: docs/design/09_詳細設計_UI設計.md §3.6
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from livelyrec.infrastructure.config_store import AppSettings
from livelyrec.shared.network import resolve_advertised_host


def _h_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent=None,
        source_fetcher: Callable[[str, int, str], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("LivelyRec 設定")
        self._settings = settings
        # (host, port, password) を受け取り OBS の入力ソース名一覧を返す関数。
        # UI 層が infrastructure へ直接依存しないよう、呼び出し側から注入する。
        self._source_fetcher = source_fetcher

        tabs = QTabWidget(self)
        tabs.addTab(self._build_obs_tab(), "OBS")
        tabs.addTab(self._build_recording_tab(), "記録")
        tabs.addTab(self._build_ws_tab(), "WebSocket")
        tabs.addTab(self._build_browser_tab(), "配信支援")
        tabs.addTab(self._build_update_tab(), "アップデート")
        tabs.addTab(self._build_master_tab(), "マスタ")
        tabs.addTab(self._build_banner_tab(), "楽曲認識")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_warning_bar())
        layout.addWidget(tabs)
        layout.addWidget(self._build_developer_section())
        layout.addWidget(buttons)

    # ---- 警告バー ----
    def _build_warning_bar(self) -> QWidget:
        w = QLabel(
            "⚠ 設定ファイル `livelyrec_data/settings.json` は **平文** で保存されます。\n"
            "  サポート依頼でフォルダを共有する際は、OBSパスワードを削除してから送付してください。"
        )
        w.setStyleSheet(
            "background-color: #FFF7C2; padding: 8px; border: 1px solid #C9B660;"
        )
        w.setWordWrap(True)
        return w

    # ---- OBS タブ ----
    def _build_obs_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._obs_host = QLineEdit(self._settings.obs.host)
        self._obs_port = QSpinBox()
        self._obs_port.setRange(1, 65535)
        self._obs_port.setValue(self._settings.obs.port)
        # ソース名は手入力では分かりにくいため、OBS から取得して選択できるようにする
        self._obs_source = QComboBox()
        self._obs_source.setEditable(True)
        if self._settings.obs.source_name:
            self._obs_source.addItem(self._settings.obs.source_name)
            self._obs_source.setCurrentText(self._settings.obs.source_name)
        self._obs_source_fetch_btn = QPushButton("OBSから取得")
        self._obs_source_fetch_btn.clicked.connect(self._fetch_obs_sources)
        source_row = QHBoxLayout()
        source_row.addWidget(self._obs_source, stretch=1)
        source_row.addWidget(self._obs_source_fetch_btn)
        self._obs_password = QLineEdit(self._settings.obs.password)
        self._obs_password.setEchoMode(QLineEdit.Password)
        self._obs_password_persist = QCheckBox("パスワードを保存する（無効時は毎起動時に入力）")
        self._obs_password_persist.setChecked(self._settings.obs.password_persist)
        layout.addRow("ホスト:", self._obs_host)
        layout.addRow("ポート:", self._obs_port)
        layout.addRow("ソース名:", source_row)
        layout.addRow("パスワード:", self._obs_password)
        layout.addRow("", self._obs_password_persist)
        return w

    def _fetch_obs_sources(self) -> None:
        """「OBSから取得」ボタン: 現在の接続情報で OBS の入力ソース一覧を取得する。"""
        if self._source_fetcher is None:
            QMessageBox.information(self, "ソース取得", "ソース取得機能が利用できません。")
            return
        host = self._obs_host.text().strip() or "127.0.0.1"
        port = self._obs_port.value()
        password = self._obs_password.text()
        try:
            sources = self._source_fetcher(host, port, password)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "ソース取得失敗",
                "OBS からソース一覧を取得できませんでした。\n"
                "OBS が起動しているか、ホスト・ポート・パスワードが正しいか確認してください。\n\n"
                f"{e}",
            )
            return
        current = self._obs_source.currentText().strip()
        self._obs_source.clear()
        self._obs_source.addItems(sources)
        if current:
            self._obs_source.setCurrentText(current)
        if not sources:
            QMessageBox.information(
                self, "ソース取得", "OBS に入力ソースが見つかりませんでした。"
            )

    # ---- 記録タブ ----
    def _build_recording_tab(self) -> QWidget:
        from livelyrec.shared.constants import MAX_FPS
        w = QWidget()
        layout = QFormLayout(w)
        self._fps = QSpinBox()
        # 0.5 秒間隔（2 fps）で認識・配信支援とも追従に十分なため、
        # CPU/GPU 負荷と OBS スクリーンショット I/O を抑える目的で上限を
        # MAX_FPS に制限（I-025 対応・PO 判断 2026-05-24）。
        self._fps.setRange(1, MAX_FPS)
        self._fps.setValue(min(self._settings.recording.fps, MAX_FPS))
        self._rollover = QSpinBox()
        self._rollover.setRange(0, 23)
        self._rollover.setValue(self._settings.recording.business_day_rollover_hour)
        self._debug_capture = QCheckBox(
            "デバッグ撮影（記録中フレームを livelyrec_data/debug/ に保存）"
        )
        self._debug_capture.setChecked(self._settings.recording.debug_capture)
        layout.addRow("fps:", self._fps)
        layout.addRow("プレイ日切替時刻 (時):", self._rollover)
        layout.addRow("", self._debug_capture)

        # ---- リザルト画面の自動スクリーンショット（FR-REC-046〜048） ----
        layout.addRow(_h_separator())
        self._result_capture_enabled = QCheckBox(
            "リザルト画面を自動でスクリーンショット保存する"
        )
        self._result_capture_enabled.setChecked(self._settings.result_capture.enabled)
        self._result_capture_dir = QLineEdit(
            self._settings.result_capture.output_dir or ""
        )
        self._result_capture_dir.setPlaceholderText(
            "（既定: livelyrec_data/result/）"
        )
        result_dir_browse = QPushButton("参照…")
        result_dir_browse.clicked.connect(
            lambda: self._browse_dir_into(self._result_capture_dir)
        )
        result_dir_row = QHBoxLayout()
        result_dir_row.addWidget(self._result_capture_dir, stretch=1)
        result_dir_row.addWidget(result_dir_browse)
        self._result_capture_freespace = QLabel("")
        self._result_capture_dir.textChanged.connect(
            lambda _t: self._refresh_freespace_label(
                self._result_capture_dir, self._result_capture_freespace
            )
        )
        self._refresh_freespace_label(
            self._result_capture_dir, self._result_capture_freespace
        )
        layout.addRow("", self._result_capture_enabled)
        layout.addRow("保存先:", result_dir_row)
        layout.addRow("", self._result_capture_freespace)
        return w

    # ---- WebSocket タブ ----
    def _build_ws_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._ws_host = QLineEdit(self._settings.websocket_server.host)
        self._ws_port = QSpinBox()
        self._ws_port.setRange(1, 65535)
        self._ws_port.setValue(self._settings.websocket_server.port)
        self._ws_lan = QCheckBox("LAN公開（外部接続を許可。家庭内LANを想定）")
        self._ws_lan.setChecked(self._settings.websocket_server.lan_publish)
        # 外部連携ツール（プラグイン等）向けの WS URI。メイン画面では表示せず
        # 設定からのみ参照できるようにする。表示時点の host/port/lan_publish から
        # 算出する読み取り専用フィールド＋コピーボタン。
        self._ws_uri = QLineEdit(self._build_ws_uri())
        self._ws_uri.setReadOnly(True)
        ws_uri_copy = QPushButton("コピー")
        ws_uri_copy.clicked.connect(self._copy_ws_uri)
        ws_uri_row = QHBoxLayout()
        ws_uri_row.addWidget(self._ws_uri, stretch=1)
        ws_uri_row.addWidget(ws_uri_copy)
        layout.addRow("ホスト:", self._ws_host)
        layout.addRow("ポート:", self._ws_port)
        layout.addRow("", self._ws_lan)
        layout.addRow("外部連携URI:", ws_uri_row)
        # ホスト・ポート・LAN公開フラグの変更時に WS URI 表示を追従させる
        self._ws_host.textChanged.connect(lambda _t: self._refresh_ws_uri())
        self._ws_port.valueChanged.connect(lambda _v: self._refresh_ws_uri())
        self._ws_lan.toggled.connect(lambda _c: self._refresh_ws_uri())
        return w

    def _build_ws_uri(self) -> str:
        host = (self._ws_host.text().strip() or "127.0.0.1") if hasattr(
            self, "_ws_host"
        ) else self._settings.websocket_server.host
        port = self._ws_port.value() if hasattr(self, "_ws_port") else (
            self._settings.websocket_server.port
        )
        lan = self._ws_lan.isChecked() if hasattr(self, "_ws_lan") else (
            self._settings.websocket_server.lan_publish
        )
        adv = resolve_advertised_host(host, lan)
        return f"ws://{adv}:{port}/v1"

    def _refresh_ws_uri(self) -> None:
        self._ws_uri.setText(self._build_ws_uri())

    def _copy_ws_uri(self) -> None:
        self._ws_uri.selectAll()
        self._ws_uri.copy()

    # ---- 配信支援タブ ----
    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._theme_url = QLineEdit(self._settings.browser_source.theme_url or "")
        layout.addRow("テーマCSS URL:", self._theme_url)
        return w

    # ---- アップデートタブ ----
    def _build_update_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._auto_update = QCheckBox("自動アップデート")
        self._auto_update.setChecked(self._settings.update.auto_update)
        self._check_on_startup = QCheckBox("起動時にアップデート確認")
        self._check_on_startup.setChecked(self._settings.update.check_on_startup)
        layout.addRow("", self._auto_update)
        layout.addRow("", self._check_on_startup)
        return w

    # ---- マスタタブ ----
    def _build_master_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._master_url = QLineEdit(self._settings.master.endpoint_url)
        layout.addRow("配信元URL:", self._master_url)
        return w

    # ---- 楽曲認識タブ（FR-BAN-003〜009、v2.0） ----
    def _build_banner_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        info = QLabel(
            "バナー画像認識は、リザルト画面の楽曲名 OCR が困難な場合の補助です。\n"
            "「Wikiからのバナー画像取得」はユーザご自身の責任で、私的複製の範囲で\n"
            "お使いください。本アプリは KONAMI 公式とは無関係です。"
        )
        info.setStyleSheet("color: #555; padding: 4px;")
        info.setWordWrap(True)
        layout.addRow(info)

        self._banner_match_enabled = QCheckBox(
            "バナー特徴量マッチを使用する（楽曲認識の補助）"
        )
        self._banner_match_enabled.setChecked(self._settings.banner.match_enabled)
        layout.addRow("", self._banner_match_enabled)

        self._banner_auto_fetch = QCheckBox(
            "Wiki から自動でバナー画像を取得する（同意ダイアログを表示）"
        )
        self._banner_auto_fetch.setChecked(self._settings.banner.auto_fetch_enabled)
        layout.addRow("", self._banner_auto_fetch)

        self._banner_endpoint = QLineEdit(self._settings.banner.endpoint_url)
        self._banner_endpoint.setPlaceholderText(
            "（既定: 同梱の banner_features.json）"
        )
        layout.addRow("特徴量配信URL:", self._banner_endpoint)

        self._banner_cache_dir = QLineEdit(self._settings.banner.cache_dir or "")
        self._banner_cache_dir.setPlaceholderText(
            "（既定: livelyrec_data/banners_ref/）"
        )
        browse = QPushButton("参照…")
        browse.clicked.connect(
            lambda: self._browse_dir_into(self._banner_cache_dir)
        )
        cache_row = QHBoxLayout()
        cache_row.addWidget(self._banner_cache_dir, stretch=1)
        cache_row.addWidget(browse)
        layout.addRow("画像キャッシュ先:", cache_row)
        return w

    # ---- 開発者設定セクション（FR-DEV-001） ----
    def _build_developer_section(self) -> QWidget:
        """設定ダイアログ末尾に配置する折りたたみ風の開発者設定セクション。"""
        box = QGroupBox("開発者設定（実験的機能）", self)
        box.setCheckable(True)
        box.setChecked(False)  # 既定で折りたたみ（中身を非表示）
        inner = QWidget(box)
        layout = QFormLayout(inner)
        note = QLabel(
            "⚠ この機能は LivelyRec の認識精度向上のための実験的機能です。\n"
            "  データの保存先容量に注意してください。"
        )
        note.setStyleSheet("color: #884400;")
        note.setWordWrap(True)
        layout.addRow(note)

        self._dev_banner_enabled = QCheckBox(
            "リザルト画面のバナー画像を保存する（開発者向け）"
        )
        self._dev_banner_enabled.setChecked(
            self._settings.developer.banner_capture_enabled
        )
        self._dev_banner_dir = QLineEdit(self._settings.developer.banner_dir or "")
        self._dev_banner_dir.setPlaceholderText("（既定: livelyrec_data/banner/）")
        browse = QPushButton("参照…")
        browse.clicked.connect(
            lambda: self._browse_dir_into(self._dev_banner_dir)
        )
        dev_dir_row = QHBoxLayout()
        dev_dir_row.addWidget(self._dev_banner_dir, stretch=1)
        dev_dir_row.addWidget(browse)
        self._dev_banner_freespace = QLabel("")
        self._dev_banner_dir.textChanged.connect(
            lambda _t: self._refresh_freespace_label(
                self._dev_banner_dir, self._dev_banner_freespace
            )
        )
        self._refresh_freespace_label(
            self._dev_banner_dir, self._dev_banner_freespace
        )
        layout.addRow("", self._dev_banner_enabled)
        layout.addRow("保存先:", dev_dir_row)
        layout.addRow("", self._dev_banner_freespace)

        outer = QVBoxLayout(box)
        outer.addWidget(inner)
        # 折りたたみ: チェック状態に合わせて中身の可視性を切り替え
        inner.setVisible(box.isChecked())
        box.toggled.connect(inner.setVisible)
        return box

    # ---- 共通: ディレクトリ参照ボタン ----
    @staticmethod
    def _browse_dir_into(target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            None, "保存先フォルダを選択", target.text() or ""
        )
        if path:
            target.setText(path)

    # ---- 共通: 空き容量警告ラベル（NFR-OPS-006） ----
    @staticmethod
    def _refresh_freespace_label(target: QLineEdit, label: QLabel) -> None:
        """指定パスのドライブ空き容量を表示。500MB を下回ったら警告色。"""
        path = target.text().strip() or "."
        try:
            free_bytes = shutil.disk_usage(path).free
        except (FileNotFoundError, OSError):
            label.setText("空き容量: パスにアクセスできません")
            label.setStyleSheet("color: #aa6600;")
            return
        free_mb = free_bytes / (1024 * 1024)
        label.setText(f"空き容量: {free_mb:,.0f} MB")
        # 500MB 未満で警告色（NFR-OPS-006）
        label.setStyleSheet(
            "color: #cc0000;" if free_bytes < 500 * 1024 * 1024 else "color: #555;"
        )

    # ---- 結果取得 ----
    def to_settings(self) -> AppSettings:
        s = self._settings
        new = replace(
            s,
            obs=replace(
                s.obs,
                host=self._obs_host.text().strip() or "127.0.0.1",
                port=self._obs_port.value(),
                source_name=self._obs_source.currentText().strip(),
                password=self._obs_password.text(),
                password_persist=self._obs_password_persist.isChecked(),
            ),
            recording=replace(
                s.recording,
                fps=self._fps.value(),
                business_day_rollover_hour=self._rollover.value(),
                debug_capture=self._debug_capture.isChecked(),
            ),
            websocket_server=replace(
                s.websocket_server,
                host=self._ws_host.text().strip() or "127.0.0.1",
                port=self._ws_port.value(),
                lan_publish=self._ws_lan.isChecked(),
                # token は UI から除外（家庭内 LAN 想定。後方互換のため
                # settings.json 直編集で残せるよう既存値を維持する）。
                token=s.websocket_server.token,
            ),
            browser_source=replace(
                s.browser_source,
                theme_url=self._theme_url.text().strip() or None,
            ),
            update=replace(
                s.update,
                auto_update=self._auto_update.isChecked(),
                check_on_startup=self._check_on_startup.isChecked(),
            ),
            master=replace(
                s.master,
                endpoint_url=self._master_url.text().strip(),
            ),
            result_capture=replace(
                s.result_capture,
                enabled=self._result_capture_enabled.isChecked(),
                output_dir=(self._result_capture_dir.text().strip() or None),
            ),
            developer=replace(
                s.developer,
                banner_capture_enabled=self._dev_banner_enabled.isChecked(),
                banner_dir=(self._dev_banner_dir.text().strip() or None),
            ),
            banner=replace(
                s.banner,
                match_enabled=self._banner_match_enabled.isChecked(),
                auto_fetch_enabled=self._banner_auto_fetch.isChecked(),
                endpoint_url=self._banner_endpoint.text().strip(),
                cache_dir=(self._banner_cache_dir.text().strip() or None),
            ),
        )
        return new
