"""ファイル名サニタイザ（自動スクショ／バナー画像出力で利用）。

詳細: docs/design/05_基本設計書.md §9.9、docs/design/06_詳細設計_アーキテクチャ.md §3.8

楽曲名に含まれる OS のファイル名禁止文字を削除し、パス長制約を満たすファイル名を組み立てる。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


class FilenameSanitizer:
    """楽曲名のファイル名サニタイズと、result/banner のファイル名組み立て。"""

    FORBIDDEN = '<>:"/\\|?*'
    UNKNOWN_TITLE = "unknown"
    MAX_BYTES = 80  # サニタイズ後のタイトル UTF-8 バイト数上限（パス長対策）

    _CONTROL_RE = re.compile(r"[\x00-\x1f]")

    def sanitize_title(self, title: str | None) -> str:
        """禁止文字・制御文字を削除し、両端の空白／ドットも除去。
        空文字になったら 'unknown' を返し、UTF-8 80 バイトで切り詰める。
        """
        if not title:
            return self.UNKNOWN_TITLE
        s = title
        # 禁止文字を削除
        for ch in self.FORBIDDEN:
            s = s.replace(ch, "")
        # 制御文字（0x00-0x1F）を削除
        s = self._CONTROL_RE.sub("", s)
        # 両端の空白とドット（Windows のファイル名規約）
        s = s.strip(" \t.")
        if not s:
            return self.UNKNOWN_TITLE
        return self._truncate_utf8(s, self.MAX_BYTES)

    def compose_result_filename(
        self,
        ts: datetime,
        title: str | None,
        score: int | None,
    ) -> str:
        """`YYYY-MM-DD_HH-mm-ss_<sanitized>_<score>.png`"""
        stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
        sanitized = self.sanitize_title(title)
        score_str = str(score) if score is not None else "unknown"
        return f"{stamp}_{sanitized}_{score_str}.png"

    def compose_banner_filename(self, ts: datetime, title: str | None) -> str:
        """`YYYY-MM-DD_HH-mm-ss_<sanitized>_banner.png`"""
        stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
        sanitized = self.sanitize_title(title)
        return f"{stamp}_{sanitized}_banner.png"

    def resolve_unique(self, path: Path) -> Path:
        """既存ファイルと衝突したら拡張子手前に `_2`, `_3` ... を付与して一意化。"""
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        for i in range(2, 1000):
            candidate = parent / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                return candidate
        # 1000 連番でも空きが無いケースは想定しないが、最終フォールバック
        return parent / f"{stem}_{datetime.now().strftime('%f')}{suffix}"

    @staticmethod
    def _truncate_utf8(s: str, max_bytes: int) -> str:
        encoded = s.encode("utf-8")
        if len(encoded) <= max_bytes:
            return s
        # マルチバイト境界を壊さないよう少しずつ削る
        truncated = encoded[:max_bytes]
        while truncated:
            try:
                return truncated.decode("utf-8")
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""
