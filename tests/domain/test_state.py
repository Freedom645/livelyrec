"""状態マシンのテスト。"""

from __future__ import annotations

from livelyrec.domain.state import ScreenType, StateMachine


def test_initial_state_is_unknown() -> None:
    sm = StateMachine()
    assert sm.current == ScreenType.UNKNOWN


def test_any_transition_allowed_from_unknown() -> None:
    sm = StateMachine()
    assert sm.transition(ScreenType.PLAY) is True
    assert sm.current == ScreenType.PLAY


def test_valid_transition_accepted() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.SELECT)
    assert sm.transition(ScreenType.READY) is True
    assert sm.current == ScreenType.READY


def test_invalid_transition_rejected_first_time() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.SELECT)
    # SELECT -> PLAY は不正
    assert sm.transition(ScreenType.PLAY) is False
    assert sm.current == ScreenType.SELECT


def test_consecutive_invalid_eventually_accepted() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.SELECT)
    # SELECT -> PLAY は不正だが、3回連続観測で受容
    for _ in range(StateMachine.CONSECUTIVE_REQUIRED_INVALID - 1):
        assert sm.transition(ScreenType.PLAY) is False
    assert sm.transition(ScreenType.PLAY) is True
    assert sm.current == ScreenType.PLAY


def test_different_invalid_resets_counter() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.SELECT)
    assert sm.transition(ScreenType.PLAY) is False  # 1回目（PLAY狙い）
    assert sm.transition(ScreenType.RESULT) is False  # 別の不正、カウンタリセット
    assert sm.transition(ScreenType.PLAY) is False  # PLAY 狙いを再開、まだ1回目
    # よって PLAY が受容されるには更に2回観測が必要
    assert sm.transition(ScreenType.PLAY) is False
    assert sm.transition(ScreenType.PLAY) is True


def test_play_self_transition_allowed_for_retry() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.PLAY)
    assert sm.transition(ScreenType.PLAY) is True
    assert sm.current == ScreenType.PLAY


def test_reset_returns_to_unknown() -> None:
    sm = StateMachine()
    sm.transition(ScreenType.PLAY)
    sm.reset()
    assert sm.current == ScreenType.UNKNOWN
