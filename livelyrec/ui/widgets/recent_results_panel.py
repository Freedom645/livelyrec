"""直近リザルトパネル。"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGroupBox, QListWidget, QVBoxLayout

from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel


class RecentResultsPanel(QGroupBox):
    def __init__(self, vm: RecordingViewModel, max_items: int = 10, parent=None) -> None:
        super().__init__("直近リザルト", parent)
        self._max = max_items
        self._items: deque[str] = deque(maxlen=max_items)
        self._list = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self._list)

        vm.result_recorded.connect(self._on_result)

    @Slot(dict)
    def _on_result(self, payload: dict) -> None:
        # 楽曲名検出失敗（FR-STR-008 / FR-REC-039）時は display_title="検出失敗"
        # が来る。後方互換で title フィールドのみ来た場合は title を採用、
        # それも無ければ「（検出失敗）」をフォールバック表示する。
        display = payload.get("display_title") or payload.get("title") or "（検出失敗）"
        text = (
            f"{display} / "
            f"Score {payload.get('score', '?')} "
            f"{payload.get('clear_type', '?')} "
            f"{payload.get('rank', '?')}"
        )
        self._items.appendleft(text)
        self._list.clear()
        for it in self._items:
            self._list.addItem(it)
