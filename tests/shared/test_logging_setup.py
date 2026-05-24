"""ロガー初期化とマスクフィルタのテスト。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from livelyrec.shared.logging_setup import MaskingFilter, setup_logging


@pytest.fixture(autouse=True)
def _restore_livelyrec_logger():
    """テストが `livelyrec` ロガーのグローバル状態を汚さないよう保存・復元する。"""
    logger = logging.getLogger("livelyrec")
    saved = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    yield
    for h in logger.handlers:
        h.close()
    logger.handlers.clear()
    logger.handlers.extend(saved)
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("livelyrec.test", logging.INFO, "p", 1, msg, None, None)


# ---- MaskingFilter ----

def test_masking_filter_masks_json_password() -> None:
    rec = _record('connecting with {"password": "secret123"}')
    assert MaskingFilter().filter(rec) is True
    masked = rec.getMessage()
    assert "secret123" not in masked
    assert "***" in masked


def test_masking_filter_masks_token_assignment() -> None:
    rec = _record("auth token=abcdef0123")
    MaskingFilter().filter(rec)
    assert "abcdef0123" not in rec.getMessage()


def test_masking_filter_masks_password_assignment() -> None:
    rec = _record("password = hunter2")
    MaskingFilter().filter(rec)
    assert "hunter2" not in rec.getMessage()


def test_masking_filter_passes_clean_message() -> None:
    rec = _record("just a normal log line")
    assert MaskingFilter().filter(rec) is True
    assert rec.getMessage() == "just a normal log line"


# ---- setup_logging ----

def test_setup_logging_creates_dir_and_logger(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logger = setup_logging(logs, level="DEBUG")
    assert logs.exists()
    assert logger.name == "livelyrec"
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert logger.propagate is False


def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    setup_logging(logs)
    logger = setup_logging(logs)  # 2回目もハンドラは重複しない
    assert len(logger.handlers) == 1


def test_setup_logging_invalid_level_defaults_to_info(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path / "logs", level="NOT_A_LEVEL")
    assert logger.level == logging.INFO


def test_setup_logging_handler_masks_secrets(tmp_path: Path) -> None:
    logger = setup_logging(tmp_path / "logs")
    handler = logger.handlers[0]
    # ハンドラに MaskingFilter が付与されている
    assert any(isinstance(f, MaskingFilter) for f in handler.filters)
