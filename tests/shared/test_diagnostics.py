"""diagnostics（メモリスナップショット・定期モニタ）のテスト。"""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from livelyrec.shared import diagnostics


def test_get_memory_snapshot_returns_none_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert diagnostics.get_memory_snapshot() is None


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_get_memory_snapshot_returns_plausible_values_on_windows() -> None:
    snap = diagnostics.get_memory_snapshot()
    assert snap is not None
    # 取得値は最低でも数 MB と数十 MB（実際のテストプロセス）
    assert snap["rss_mb"] > 0
    assert snap["sys_total_mb"] > snap["sys_avail_mb"] > 0
    assert 0 <= snap["sys_memory_load_pct"] <= 100


def test_log_memory_once_writes_to_logger(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 取得値を固定してログ出力を検証
    fake_snap = {
        "rss_mb": 150.0,
        "private_mb": 200.0,
        "peak_rss_mb": 180.0,
        "sys_memory_load_pct": 55,
        "sys_avail_mb": 5000.0,
        "sys_total_mb": 16000.0,
    }
    monkeypatch.setattr(diagnostics, "get_memory_snapshot", lambda: fake_snap)
    with caplog.at_level(logging.INFO, logger="livelyrec.diag"):
        diagnostics.log_memory_once()
    messages = [r.getMessage() for r in caplog.records]
    assert any("rss=150.0MB" in m for m in messages)
    assert any("sys_load=55%" in m for m in messages)


def test_log_memory_once_skips_when_snapshot_unavailable(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "get_memory_snapshot", lambda: None)
    with caplog.at_level(logging.INFO, logger="livelyrec.diag"):
        diagnostics.log_memory_once()
    assert not caplog.records


def test_memory_monitor_start_stop_is_idempotent_and_quick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # start → stop が短時間で確実に終わる（join タイムアウトに余裕がある）
    monkeypatch.setattr(diagnostics, "get_memory_snapshot", lambda: None)
    mon = diagnostics.MemoryMonitor(interval_sec=0.05)
    mon.start()
    # 2 回目 start は何もしない
    mon.start()
    mon.stop(timeout=2.0)
    # 2 回目 stop も例外なし
    mon.stop(timeout=2.0)


def test_memory_monitor_emits_initial_log_then_periodic(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_snap = {
        "rss_mb": 10.0, "private_mb": 12.0, "peak_rss_mb": 11.0,
        "sys_memory_load_pct": 30, "sys_avail_mb": 1000.0, "sys_total_mb": 2000.0,
    }
    monkeypatch.setattr(diagnostics, "get_memory_snapshot", lambda: fake_snap)
    mon = diagnostics.MemoryMonitor(interval_sec=0.05)
    with caplog.at_level(logging.INFO, logger="livelyrec.diag"):
        mon.start()
        # 数周期回す
        threading.Event().wait(0.18)
        mon.stop(timeout=2.0)
    # 起動直後 1 件 + 周期分（>=1 件）で合計 2 件以上
    assert sum(1 for r in caplog.records if "rss=10.0MB" in r.getMessage()) >= 2
