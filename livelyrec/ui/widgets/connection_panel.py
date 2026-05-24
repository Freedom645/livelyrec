"""接続パネル。"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel


class ConnectionPanel(QGroupBox):
    def __init__(
        self,
        vm: RecordingViewModel,
        on_start,
        on_stop,
        on_settings,
        parent=None,
    ) -> None:
        super().__init__("接続", parent)
        self._vm = vm
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_settings = on_settings

        self._state_label = QLabel("状態: 未接続")
        self._url_label = QLabel("ws://127.0.0.1:14514/v1")
        self._url_label.setStyleSheet("color: #888;")

        self._start_btn = QPushButton("記録開始(&S)")
        self._stop_btn = QPushButton("記録停止(&P)")
        self._settings_btn = QPushButton("設定(&O)…")
        self._stop_btn.setEnabled(False)

        self._start_btn.clicked.connect(self._handle_start)
        self._stop_btn.clicked.connect(self._handle_stop)
        self._settings_btn.clicked.connect(lambda: self._on_settings())

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._settings_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._state_label)
        layout.addWidget(self._url_label)
        layout.addLayout(btn_row)
        layout.addStretch(1)

        vm.state_changed.connect(self._on_state_changed)

    @Slot(str)
    def _on_state_changed(self, state: str) -> None:
        labels = {
            "initial": "状態: 未接続",
            "connecting": "状態: 接続中…",
            "recording_unknown": "状態: 記録中（画面確定待ち）",
            "recording": "状態: 記録中",
            "stopped": "状態: 停止",
        }
        self._state_label.setText(labels.get(state, f"状態: {state}"))
        is_recording = state in ("connecting", "recording_unknown", "recording")
        self._start_btn.setEnabled(not is_recording)
        self._stop_btn.setEnabled(is_recording)

    def _handle_start(self) -> None:
        self._on_start()

    def _handle_stop(self) -> None:
        self._on_stop()
