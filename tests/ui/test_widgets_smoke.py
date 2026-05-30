"""UI ウィジェット・ダイアログ・メインウィンドウの構築スモークテスト。

単体テスト工程では UI は「例外なく構築でき、VM イベントでスロットが
走っても落ちない」ことのみを確認する。実描画・操作の検証はシステムテストへ。
"""

from __future__ import annotations

from pathlib import Path

from livelyrec.application.export_service import ExportService
from livelyrec.application.update_service import UpdateService
from livelyrec.infrastructure.config_store import AppSettings, ConfigStore
from livelyrec.ui.main_window import MainWindow
from livelyrec.ui.settings_dialog import SettingsDialog
from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel
from livelyrec.ui.widgets.broadcast_url_panel import BroadcastUrlPanel
from livelyrec.ui.widgets.connection_panel import ConnectionPanel
from livelyrec.ui.widgets.daily_counter_panel import DailyCounterPanel
from livelyrec.ui.widgets.recent_results_panel import RecentResultsPanel
from livelyrec.ui.widgets.record_status_panel import RecordStatusPanel


class FakeRecording:
    """MainWindow が必要とする最小限のインターフェイスを持つフェイク。"""

    def add_listener(self, listener) -> None:  # noqa: ARG002
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def test_connection_panel_smoke(qtbot) -> None:
    vm = RecordingViewModel()
    panel = ConnectionPanel(vm, lambda: None, lambda: None, lambda: None)
    qtbot.addWidget(panel)
    # 状態変化イベントでスロットが走っても落ちない
    vm.on_event({"type": "state.changed", "payload": {"recording_state": "recording"}})
    vm.on_event({"type": "state.changed", "payload": {"recording_state": "stopped"}})


def test_record_status_panel_smoke(qtbot) -> None:
    vm = RecordingViewModel()
    panel = RecordStatusPanel(vm)
    qtbot.addWidget(panel)
    vm.on_event({"type": "state.changed", "payload": {"screen": "play", "confidence": 0.8}})
    vm.on_event({"type": "play.started", "payload": {"title": "テスト曲"}})
    vm.on_event({"type": "result.recorded", "payload": {"score": 87268, "combo": 329}})


def test_daily_counter_panel_smoke(qtbot) -> None:
    vm = RecordingViewModel()
    panel = DailyCounterPanel(vm, rollover_hour=6)
    qtbot.addWidget(panel)
    vm.on_event({
        "type": "judgements.tick",
        "payload": {"daily_total": {"cool": 100, "great": 5, "good": 2, "bad": 1}},
    })
    vm.on_event({"type": "business_day.rolled", "payload": {"current_date": "2026-05-20"}})


def test_recent_results_panel_smoke(qtbot) -> None:
    vm = RecordingViewModel()
    panel = RecentResultsPanel(vm)
    qtbot.addWidget(panel)
    vm.on_event({
        "type": "result.recorded",
        "payload": {"score": 90000, "clear_type": "CLEAR", "rank": "AAA"},
    })


def test_broadcast_url_panel_smoke(qtbot) -> None:
    urls = {
        "打鍵数カウンタ": "http://127.0.0.1:14514/browser/keycount/",
        "現在のプレイ楽曲": "http://127.0.0.1:14514/browser/now-playing/",
        "選曲中の楽曲のスコア履歴": "http://127.0.0.1:14514/browser/now-playing-history/",
        "直近 10 件のプレイ履歴": "http://127.0.0.1:14514/browser/recent/",
    }
    panel = BroadcastUrlPanel(urls)
    qtbot.addWidget(panel)


def test_settings_dialog_smoke(qtbot) -> None:
    dlg = SettingsDialog(AppSettings())
    qtbot.addWidget(dlg)
    # 設定の取り出しが例外なく動作する
    out = dlg.to_settings()
    assert out.obs.host
    # 外部連携 URI（読み取り専用）が WebSocket タブに表示される
    assert dlg._ws_uri.text().startswith("ws://")
    assert dlg._ws_uri.text().endswith("/v1")
    # トークンは UI から触れず、既存 settings 値が維持される（家庭内 LAN 想定）
    assert out.websocket_server.token == dlg._settings.websocket_server.token


def test_main_window_smoke(qtbot, tmp_path: Path) -> None:
    window = MainWindow(
        recording=FakeRecording(),
        config_store=ConfigStore(tmp_path / "settings.json"),
        settings=AppSettings(),
        export_service=ExportService(object()),
        update_service=UpdateService(object(), "1.0.0"),
        logs_dir=tmp_path,
    )
    qtbot.addWidget(window)
    assert window.windowTitle() == "LivelyRec"
    # メインウィンドウが各パネルを保持している
    assert window.centralWidget() is not None


# --- v2.0 バナー画像認識関連 UI（FR-BAN-003〜009、Phase D） ---


def test_settings_dialog_has_banner_tab(qtbot) -> None:
    """設定ダイアログに「楽曲認識」タブが存在し、banner 設定を読み書きできる。

    v0.8 でアプリは画像本体を扱わない方針に変更されたため、設定項目は
    match_enabled / endpoint_url の 2 つのみ。
    """
    s = AppSettings()
    s.banner.match_enabled = True
    s.banner.endpoint_url = "https://example.invalid/banner_features.json"
    dlg = SettingsDialog(s)
    qtbot.addWidget(dlg)
    assert dlg._banner_match_enabled.isChecked() is True
    assert dlg._banner_endpoint.text() == "https://example.invalid/banner_features.json"

    # UI 変更が to_settings() に反映される
    dlg._banner_match_enabled.setChecked(False)
    out = dlg.to_settings()
    assert out.banner.match_enabled is False
    assert out.banner.endpoint_url == "https://example.invalid/banner_features.json"


def test_about_dialog_contains_konami_disclaimer(qtbot) -> None:
    """About ダイアログに KONAMI 公式非関連の免責が含まれる（v0.9: 出典表示は撤去）。"""
    from livelyrec.ui.about_dialog import ABOUT_BODY, AboutDialog
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert "コナミデジタル" in ABOUT_BODY
    assert "無関係" in ABOUT_BODY
    # 出典表示は撤去済み
    assert "remywiki" not in ABOUT_BODY
    assert "fandom" not in ABOUT_BODY
