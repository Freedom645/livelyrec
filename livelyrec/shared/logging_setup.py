"""ロガー初期化とマスクフィルタ。

詳細: docs/design/06_詳細設計_アーキテクチャ.md §6
"""

from __future__ import annotations

import logging
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_MASK_PATTERNS = [
    re.compile(r'("(?:password|pwd|token|auth[a-z_]*)"\s*:\s*")[^"]*(")', re.IGNORECASE),
    re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(token\s*[=:]\s*)\S+", re.IGNORECASE),
]


class MaskingFilter(logging.Filter):
    """パスワード・トークン値をマスクするフィルタ。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        msg = record.getMessage()
        masked = msg
        for pat in _MASK_PATTERNS:
            masked = pat.sub(lambda m: m.group(1) + "***" + (m.group(2) if m.lastindex and m.lastindex >= 2 else ""), masked)
        if masked != msg:
            record.msg = masked
            record.args = ()
        return True


def setup_logging(logs_dir: Path, level: str = "INFO") -> logging.Logger:
    """ロガーを初期化して `livelyrec` ロガーを返す。"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    handler = TimedRotatingFileHandler(
        filename=str(logs_dir / "livelyrec.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.addFilter(MaskingFilter())

    root = logging.getLogger("livelyrec")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 既存ハンドラを除去してから付け直し（テスト等で複数回呼ばれた場合の安全策）
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    # PaddleOCR の冗長ログを抑制
    logging.getLogger("paddleocr").setLevel(logging.WARNING)
    logging.getLogger("ppocr").setLevel(logging.WARNING)

    return root
