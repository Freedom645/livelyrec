"""プレイ日打鍵カウンタパネル。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel

from livelyrec.shared.time_utils import business_date_of
from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel


class DailyCounterPanel(QGroupBox):
    def __init__(self, vm: RecordingViewModel, rollover_hour: int = 6, parent=None) -> None:
        super().__init__("プレイ日カウンタ", parent)
        self._rollover_hour = rollover_hour

        self._business_date_label = QLabel("—")
        self._rollover_label = QLabel(f"切替: 毎日 {rollover_hour:02d}:00")
        self._total = QLabel("0")
        self._cool = QLabel("0")
        self._great = QLabel("0")
        self._good = QLabel("0")
        self._bad = QLabel("0")

        layout = QFormLayout(self)
        layout.addRow("プレイ日:", self._business_date_label)
        layout.addRow("", self._rollover_label)
        layout.addRow("総打鍵数:", self._total)
        layout.addRow("  COOL:", self._cool)
        layout.addRow("  GREAT:", self._great)
        layout.addRow("  GOOD:", self._good)
        layout.addRow("  BAD:", self._bad)

        vm.judgements_tick.connect(self._on_tick)
        vm.business_day_rolled.connect(self._on_rolled)
        self._update_business_date()

    def _update_business_date(self) -> None:
        bd = business_date_of(datetime.now(), self._rollover_hour)
        self._business_date_label.setText(bd.isoformat())

    @Slot(dict)
    def _on_tick(self, payload: dict) -> None:
        d = payload.get("daily_total", {}) or {}
        self._cool.setText(f"{d.get('cool', 0):,}")
        self._great.setText(f"{d.get('great', 0):,}")
        self._good.setText(f"{d.get('good', 0):,}")
        self._bad.setText(f"{d.get('bad', 0):,}")
        total = d.get("total")
        if total is None:
            total = sum(d.get(k, 0) for k in ("cool", "great", "good", "bad"))
        self._total.setText(f"{total:,}")

    @Slot(dict)
    def _on_rolled(self, payload: dict) -> None:
        cur = payload.get("current_date") or ""
        self._business_date_label.setText(cur)
        for lbl in (self._cool, self._great, self._good, self._bad, self._total):
            lbl.setText("0")
