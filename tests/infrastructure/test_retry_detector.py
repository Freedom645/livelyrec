"""リトライ検出のテスト。"""

from __future__ import annotations

from livelyrec.infrastructure.recognizer.retry_detector import (
    PlayFrameSnapshot,
    RetryDetector,
)


def _snap(s=None, cool=None, great=None, good=None, bad=None, combo=None) -> PlayFrameSnapshot:
    return PlayFrameSnapshot(score=s, cool=cool, great=great, good=good, bad=bad, combo=combo)


def test_initial_push_no_retry() -> None:
    d = RetryDetector()
    assert d.push(_snap(s=0, cool=0, great=0, good=0, bad=0, combo=0)) is False


def test_value_to_zero_triggers_retry() -> None:
    d = RetryDetector()
    d.push(_snap(s=30000, cool=100, great=20, good=2, bad=1, combo=80))
    triggered = d.push(_snap(s=0, cool=0, great=0, good=0, bad=0, combo=0))
    assert triggered is True


def test_intermediate_zero_does_not_trigger_repeatedly() -> None:
    d = RetryDetector()
    d.push(_snap(s=30000, cool=100, great=20, good=2, bad=1, combo=80))
    d.push(_snap(s=0, cool=0, great=0, good=0, bad=0, combo=0))  # retry
    # 直後も全部 0 だが、前 snapshot がもう「有意」ではないため再度は trigger しない
    assert d.push(_snap(s=0, cool=0, great=0, good=0, bad=0, combo=0)) is False


def test_increasing_no_retry() -> None:
    d = RetryDetector()
    d.push(_snap(s=10000, cool=30, great=2, good=0, bad=0, combo=20))
    assert d.push(_snap(s=15000, cool=45, great=3, good=0, bad=0, combo=30)) is False


def test_combo_partial_reset_not_retry() -> None:
    # combo だけ 0 になっても全判定が 0 でないと retry ではない
    d = RetryDetector()
    d.push(_snap(s=10000, cool=30, great=2, good=0, bad=0, combo=20))
    assert d.push(_snap(s=10000, cool=30, great=2, good=0, bad=0, combo=0)) is False
