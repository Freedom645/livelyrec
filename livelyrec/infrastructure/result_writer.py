"""リザルト画面の自動スクリーンショット出力（FR-REC-046〜048）。

詳細: docs/design/05_基本設計書.md §9.7、docs/design/06_詳細設計_アーキテクチャ.md §3.6

リザルト画面でスコアが安定したタイミング（I-017 の `_ResultStabilizer` 確定時）に、
OBS から取得して正規化されたフレーム全体（ゲーム領域、1366×768 BGR）を PNG で保存する。

ファイル名規約: `YYYY-MM-DD_HH-mm-ss_<sanitized_title>_<score>.png`
ファイル名衝突時は末尾に `_2`, `_3` ... を付与（FR-REC-048）。
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

logger = logging.getLogger("livelyrec.result_writer")


class ResultWriter:
    """リザルト画面の自動スクリーンショット出力。"""

    def __init__(
        self,
        enabled: bool,
        output_dir: Path,
        sanitizer: FilenameSanitizer | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._enabled = enabled
        self._output_dir = output_dir
        self._sanitizer = sanitizer or FilenameSanitizer()
        self._clock = clock
        # 設定の即時反映（UI 設定ダイアログ→記録ループ）を考慮し、
        # ON/OFF と保存先パスはロック保護で読み書きする。
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
        score: int | None,
        ts: datetime | None = None,
    ) -> Path | None:
        """正規化済みフレームをスクショとして保存する。

        - enabled=False ならスキップして None を返す（ログも出さない）。
        - 書込失敗時は WARN ログを残し None を返す（記録機能は継続）。
        - 楽曲名未特定／スコア未取得時は 'unknown' を採用する（FR-REC-046）。
        """
        if not self.is_enabled():
            return None
        with self._lock:
            out_dir = self._output_dir
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("result output dir creation failed: %s", e)
            return None

        stamp = ts if ts is not None else self._clock()
        filename = self._sanitizer.compose_result_filename(stamp, song_title, score)
        path = self._sanitizer.resolve_unique(out_dir / filename)
        try:
            ok, buf = cv2.imencode(".png", frame_bgr)
            if not ok:
                logger.warning("PNG encode failed for result screenshot")
                return None
            path.write_bytes(buf.tobytes())
            logger.info("result screenshot saved: %s", path)
            return path
        except (OSError, cv2.error) as e:
            logger.warning("result screenshot write failed: %s", e)
            return None
