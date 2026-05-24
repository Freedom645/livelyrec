"""app.py の診断系（stdout/stderr リダイレクト、faulthandler、thread excepthook）のテスト。

PyInstaller --windowed ビルドでは sys.stderr が None になるため、PaddleOCR や
C 拡張からの abort メッセージが取り逃される。app.py がこれらを
livelyrec_data/logs/ 配下に保存し、記録中クラッシュの真因解析を可能にすることを検証する。
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from pathlib import Path

import pytest

from livelyrec import app as app_module


@pytest.fixture
def restore_streams():
    """テスト中に置き換えた sys.stdout / sys.stderr / threading.excepthook を元に戻す。"""
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    orig_thook = threading.excepthook
    try:
        yield
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr
        threading.excepthook = orig_thook


def test_bootstrap_std_streams_assigns_devnull_when_none(restore_streams) -> None:
    sys.stdout = None  # type: ignore[assignment]
    sys.stderr = None  # type: ignore[assignment]

    app_module._bootstrap_std_streams()

    assert sys.stdout is not None
    assert sys.stderr is not None
    assert getattr(sys.stdout, "name", "") == os.devnull
    assert getattr(sys.stderr, "name", "") == os.devnull


def test_bootstrap_std_streams_preserves_real_streams(restore_streams) -> None:
    # 元から有効なストリームがある場合は触らない（開発時の挙動を壊さない）
    original_stderr = sys.stderr
    app_module._bootstrap_std_streams()
    assert sys.stderr is original_stderr


def test_redirect_std_streams_replaces_devnull_with_files(
    restore_streams, tmp_path: Path
) -> None:
    sys.stdout = None  # type: ignore[assignment]
    sys.stderr = None  # type: ignore[assignment]
    app_module._bootstrap_std_streams()

    app_module._redirect_std_streams_to_file(tmp_path)

    assert (tmp_path / "stdout.log").exists()
    assert (tmp_path / "stderr.log").exists()
    print("hello stdout", file=sys.stdout)
    print("hello stderr", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    assert "hello stdout" in (tmp_path / "stdout.log").read_text(encoding="utf-8")
    assert "hello stderr" in (tmp_path / "stderr.log").read_text(encoding="utf-8")


def test_redirect_std_streams_does_not_touch_real_streams(
    restore_streams, tmp_path: Path
) -> None:
    # 通常の stderr（ファイルでも tty でも、devnull 以外）はそのまま維持する
    real = sys.stderr
    app_module._redirect_std_streams_to_file(tmp_path)
    assert sys.stderr is real


def test_install_faulthandler_enables_and_writes_to_logs_dir(
    tmp_path: Path,
) -> None:
    # 既に enable 済みかどうかの状態は副作用で残る。テスト後に状態復元する
    was_enabled = faulthandler.is_enabled()
    try:
        app_module._install_faulthandler(tmp_path)
        assert (tmp_path / "faulthandler.log").exists()
        assert faulthandler.is_enabled()
    finally:
        if not was_enabled:
            faulthandler.disable()


def test_install_thread_excepthook_logs_critical(
    restore_streams, caplog: pytest.LogCaptureFixture
) -> None:
    app_module._install_thread_excepthook()

    def _boom() -> None:
        raise RuntimeError("worker exploded")

    with caplog.at_level(logging.CRITICAL, logger="livelyrec"):
        t = threading.Thread(target=_boom, name="test-worker")
        t.start()
        t.join()

    messages = [r.getMessage() for r in caplog.records]
    assert any("test-worker" in m for m in messages)
    assert any("Uncaught exception" in m for m in messages)


def test_install_thread_excepthook_ignores_system_exit(
    restore_streams, caplog: pytest.LogCaptureFixture
) -> None:
    # SystemExit は通常終了系なのでログを汚さない
    app_module._install_thread_excepthook()

    def _exit() -> None:
        raise SystemExit(0)

    with caplog.at_level(logging.CRITICAL, logger="livelyrec"):
        t = threading.Thread(target=_exit, name="exit-worker")
        t.start()
        t.join()

    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]
