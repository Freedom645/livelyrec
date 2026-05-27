"""SongIdentificationTracker のテスト（FR-REC-039 / §6.4）。"""

from __future__ import annotations

from livelyrec.application.analysis_service import SongIdentificationTracker
from livelyrec.domain.score import Chart, Difficulty


def _chart() -> Chart:
    return Chart(song_id="popn-1", title="t", difficulty=Difficulty.HYPER)


def test_initial_state_is_not_confirmed() -> None:
    t = SongIdentificationTracker(fail_after=3)
    assert not t.is_confirmed_failed()


def test_consecutive_failures_confirm() -> None:
    t = SongIdentificationTracker(fail_after=3)
    t.record_attempt(None)
    assert not t.is_confirmed_failed()
    t.record_attempt(None)
    assert not t.is_confirmed_failed()
    t.record_attempt(None)
    assert t.is_confirmed_failed()


def test_success_resets_streak() -> None:
    t = SongIdentificationTracker(fail_after=3)
    t.record_attempt(None)
    t.record_attempt(None)
    t.record_attempt(_chart())  # 成功 → ストリークリセット
    t.record_attempt(None)
    t.record_attempt(None)
    assert not t.is_confirmed_failed()
    t.record_attempt(None)
    assert t.is_confirmed_failed()


def test_after_confirmed_further_attempts_have_no_effect() -> None:
    t = SongIdentificationTracker(fail_after=2)
    t.record_attempt(None)
    t.record_attempt(None)
    assert t.is_confirmed_failed()
    # 確定後は record_attempt(chart) が来ても解除されない
    t.record_attempt(_chart())
    assert t.is_confirmed_failed()


def test_reset_clears_confirmation() -> None:
    t = SongIdentificationTracker(fail_after=2)
    t.record_attempt(None)
    t.record_attempt(None)
    assert t.is_confirmed_failed()
    t.reset()
    assert not t.is_confirmed_failed()
