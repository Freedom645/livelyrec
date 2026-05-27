"""開発者向けバナー画像出力（FR-DEV-002〜003）。

詳細: docs/design/05_基本設計書.md §9.8、docs/design/06_詳細設計_アーキテクチャ.md §3.7

リザルト画面のキャプチャから楽曲名バナー領域（RESULT_ROI["banner"]）を切り出して
PNG として保存する。開発者設定（`developer.banner_capture_enabled`）が ON のときのみ動作。

将来的に「バナー画像の特徴量と楽曲名の対応データ」を構築するための学習データ収集が目的。
プレイ毎に全保存（FR-DEV-003、特徴量の多様性確保）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .filename_sanitizer import FilenameSanitizer

logger = logging.getLogger("livelyrec.banner_writer")


class BannerWriter:
    """リザルト画面のバナー領域を切り出して PNG 保存する。"""

    def __init__(
        self,
        enabled: bool,
        output_dir: Path,
        banner_roi: tuple[int, int, int, int],
        sanitizer: FilenameSanitizer | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._enabled = enabled
        self._output_dir = output_dir
        self._banner_roi = banner_roi
        self._sanitizer = sanitizer or FilenameSanitizer()
        self._clock = clock
        self._lock = threading.Lock()

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled

    def set_output_dir(self, output_dir: Path) -> None:
        with self._lock:
            self._output_dir = output_dir

    @property
    def output_dir(self) -> Path:
        with self._lock:
            return self._output_dir

    def save(
        self,
        frame_bgr: np.ndarray,
        song_title: str | None,
        ts: datetime | None = None,
    ) -> Path | None:
        """正規化済みフレームからバナー領域を切り出して保存する。

        - enabled=False ならスキップして None を返す。
        - banner_roi がフレーム外（リサイズ不一致など）の場合は WARN ログ＋ None。
        - 書込失敗時も WARN ログ＋ None（記録機能は継続）。
        """
        if not self.is_enabled():
            return None
        with self._lock:
            out_dir = self._output_dir
            roi = self._banner_roi
        x1, y1, x2, y2 = roi
        h, w = frame_bgr.shape[:2]
        if x1 < 0 or y1 < 0 or x2 > w or y2 > h or x1 >= x2 or y1 >= y2:
            logger.warning(
                "banner ROI out of frame: roi=%s frame=%sx%s", roi, w, h
            )
            return None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("banner output dir creation failed: %s", e)
            return None

        crop = frame_bgr[y1:y2, x1:x2]
        stamp = ts if ts is not None else self._clock()
        filename = self._sanitizer.compose_banner_filename(stamp, song_title)
        path = self._sanitizer.resolve_unique(out_dir / filename)
        try:
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                logger.warning("PNG encode failed for banner image")
                return None
            path.write_bytes(buf.tobytes())
            logger.info("banner image saved: %s", path)
            return path
        except (OSError, cv2.error) as e:
            logger.warning("banner image write failed: %s", e)
            return None
