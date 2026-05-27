"""記録状態の ViewModel。

詳細: docs/design/09_詳細設計_UI設計.md §5

2026-05-20: 記録ワーカースレッドからのイベントを Qt メインスレッドへ
安全に渡すため、内部シグナル経由のディスパッチ（post_event）を追加（I-012）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


class RecordingViewModel(QObject):
    """RecordingService のイベントを UI 用にブリッジする。"""

    state_changed = Signal(str)
    screen_changed = Signal(str, float)
    play_started = Signal(dict)
    play_retry = Signal(dict)
    result_recorded = Signal(dict)
    judgements_tick = Signal(dict)
    business_day_rolled = Signal(dict)
    now_playing_changed = Signal(dict)
    error_occurred = Signal(dict)

    # スレッド跨ぎ用の内部シグナル。別スレッドから emit されると
    # QueuedConnection で必ずメインスレッドの on_event に届く。
    _incoming = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._incoming.connect(self.on_event)

    def post_event(self, event: dict[str, Any]) -> None:
        """任意のスレッドから安全にイベントを投入する。

        RecordingService の記録ワーカースレッドから呼ばれることを想定。
        QTimer.singleShot はスレッドを跨がないため使用しない（I-012）。
        """
        self._incoming.emit(event)

    @Slot(dict)
    def on_event(self, event: dict[str, Any]) -> None:
        et = event.get("type", "")
        payload = event.get("payload", {}) or {}
        if et == "state.changed":
            if "recording_state" in payload:
                self.state_changed.emit(str(payload["recording_state"]))
            if "screen" in payload:
                self.screen_changed.emit(
                    str(payload["screen"]),
                    float(payload.get("confidence", 0.0)),
                )
        elif et == "play.started":
            self.play_started.emit(payload)
        elif et == "play.retry":
            self.play_retry.emit(payload)
        elif et == "result.recorded":
            self.result_recorded.emit(payload)
        elif et == "judgements.tick":
            self.judgements_tick.emit(payload)
        elif et == "business_day.rolled":
            self.business_day_rolled.emit(payload)
        elif et == "now_playing.changed":
            self.now_playing_changed.emit(payload)
        elif et == "error":
            self.error_occurred.emit(payload)
