"""RecordingViewModel（Service イベント → UI シグナルのブリッジ）のテスト。"""

from __future__ import annotations

import pytest

from livelyrec.ui.viewmodels.recording_vm import RecordingViewModel


@pytest.fixture
def vm(qapp) -> RecordingViewModel:  # noqa: ARG001  (qapp で QApplication を保証)
    return RecordingViewModel()


def test_state_changed_event_emits_recording_state(vm: RecordingViewModel) -> None:
    received: list[str] = []
    vm.state_changed.connect(received.append)
    vm.on_event({"type": "state.changed", "payload": {"recording_state": "recording"}})
    assert received == ["recording"]


def test_state_changed_event_emits_screen(vm: RecordingViewModel) -> None:
    received: list[tuple] = []
    vm.screen_changed.connect(lambda s, c: received.append((s, c)))
    vm.on_event({"type": "state.changed", "payload": {"screen": "play", "confidence": 0.9}})
    assert received == [("play", 0.9)]


def test_screen_event_without_confidence_defaults_zero(vm: RecordingViewModel) -> None:
    received: list[tuple] = []
    vm.screen_changed.connect(lambda s, c: received.append((s, c)))
    vm.on_event({"type": "state.changed", "payload": {"screen": "select"}})
    assert received == [("select", 0.0)]


def test_play_started_event(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.play_started.connect(received.append)
    vm.on_event({"type": "play.started", "payload": {"title": "テスト曲"}})
    assert received == [{"title": "テスト曲"}]


def test_play_retry_event(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.play_retry.connect(received.append)
    vm.on_event({"type": "play.retry", "payload": {"session_id": "s1"}})
    assert received == [{"session_id": "s1"}]


def test_result_recorded_event(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.result_recorded.connect(received.append)
    vm.on_event({"type": "result.recorded", "payload": {"score": 87268}})
    assert received == [{"score": 87268}]


def test_judgements_tick_event(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.judgements_tick.connect(received.append)
    vm.on_event({"type": "judgements.tick", "payload": {"daily_total": {}}})
    assert received == [{"daily_total": {}}]


def test_business_day_rolled_event(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.business_day_rolled.connect(received.append)
    vm.on_event({"type": "business_day.rolled", "payload": {"current_date": "2026-05-20"}})
    assert received == [{"current_date": "2026-05-20"}]


def test_unknown_event_type_is_ignored(vm: RecordingViewModel) -> None:
    received: list = []
    vm.state_changed.connect(received.append)
    vm.play_started.connect(received.append)
    vm.on_event({"type": "totally.unknown", "payload": {}})
    assert received == []


def test_event_without_payload_is_safe(vm: RecordingViewModel) -> None:
    received: list[dict] = []
    vm.play_started.connect(received.append)
    # payload キー欠落でも例外を出さず空 dict を emit
    vm.on_event({"type": "play.started"})
    assert received == [{}]
