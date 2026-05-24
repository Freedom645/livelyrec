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

    @Slot(str, float)
    def _on_screen_changed(self, screen: str, confidence: float) -> None:
        self._screen.setText(_SCREEN_LABELS.get(screen, screen))

    @Slot(dict)
    def _on_play_started(self, payload: dict) -> None:
        self._song.setText(str(payload.get("title") or "—"))
        self._difficulty.setText(str(payload.get("difficulty") or "—"))

    @Slot(dict)
    def _on_result_recorded(self, payload: dict) -> None:
        self._score.setText(str(payload.get("score", "—")))
        self._combo.setText(str(payload.get("combo", "—")))
