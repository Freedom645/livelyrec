"""現在状態パネル。"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel

from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel

_SCREEN_LABELS = {
    "unknown": "未確定",
    "title": "タイトル画面",
    "select": "選曲画面",
    "ready": "準備画面",
    "option": "オプション画面",
    "quest": "クエスト画面",
    "play": "プレイ画面",
    "play_ready": "プレイ画面（Are you ready?）",
    "result": "リザルト画面",
    "load_to_play": "プレイ前ロード",
    "load_to_ready": "ロード画面",
}


class RecordStatusPanel(QGroupBox):
    def __init__(self, vm: RecordingViewModel, parent=None) -> None:
        super().__init__("現在状態", parent)
        self._screen = QLabel("—")
        self._song = QLabel("—")
        self._difficulty = QLabel("—")
        self._score = QLabel("—")
        self._combo = QLabel("—")

        layout = QFormLayout(self)
        layout.addRow("画面:", self._screen)
        layout.addRow("楽曲:", self._song)
        layout.addRow("難易度:", self._difficulty)
        layout.addRow("スコア:", self._score)
        layout.addRow("コンボ:", self._combo)

        vm.screen_changed.connect(self._on_screen_changed)
        vm.play_started.connect(self._on_play_started)
        vm.result_recorded.connect(self._on_result_recorded)
        vm.now_playing_changed.connect(self._on_now_playing_changed)

    @Slot(str, float)
    def _on_screen_changed(self, screen: str, confidence: float) -> None:
        self._screen.setText(_SCREEN_LABELS.get(screen, screen))

    @Slot(dict)
    def _on_play_started(self, payload: dict) -> None:
        # title が空・None・"検出失敗" のいずれでもそのまま表示する
        title = payload.get("title")
        self._song.setText(title if title else "—")
        diff = payload.get("difficulty")
        self._difficulty.setText(diff if diff else "—")

    @Slot(dict)
    def _on_now_playing_changed(self, payload: dict) -> None:
        # 楽曲名検出失敗（FR-STR-008）のときも UI 上「検出失敗」表示を反映する
        display = payload.get("display_title") or "—"
        self._song.setText(display)
        chart = payload.get("chart") or {}
        diff = chart.get("difficulty") or "—"
        level = chart.get("level")
        if level is not None and diff != "—":
            diff = f"{diff} Lv.{level}"
        self._difficulty.setText(diff)

    @Slot(dict)
    def _on_result_recorded(self, payload: dict) -> None:
        self._score.setText(str(payload.get("score", "—")))
        self._combo.setText(str(payload.get("combo", "—")))
