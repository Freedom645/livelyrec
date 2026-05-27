"""ResultWriter のテスト（FR-REC-046〜048）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from livelyrec.infrastructure.result_writer import ResultWriter


def _frame() -> np.ndarray:
    # 既定 1366x768 を模した小さな BGR フレーム
    f = np.zeros((100, 200, 3), dtype=np.uint8)
    f[:, :, 1] = 255  # 緑
    return f


def test_save_skipped_when_disabled(tmp_path: Path) -> None:
    w = ResultWriter(enabled=False, output_dir=tmp_path)
    assert w.save(_frame(), "song", 12345) is None
    assert not list(tmp_path.iterdir())


def test_save_creates_png_with_filename(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = ResultWriter(enabled=True, output_dir=tmp_path)
    path = w.save(_frame(), "song", 12345, ts=ts)
    assert path is not None
    assert path.name == "2026-05-28_19-30-45_song_12345.png"
    assert path.exists()
    # PNG 署名
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_save_unknown_when_title_and_score_missing(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = ResultWriter(enabled=True, output_dir=tmp_path)
    path = w.save(_frame(), None, None, ts=ts)
    assert path is not None
    assert path.name == "2026-05-28_19-30-45_unknown_unknown.png"


def test_save_collision_suffix(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = ResultWriter(enabled=True, output_dir=tmp_path)
    p1 = w.save(_frame(), "song", 100, ts=ts)
    p2 = w.save(_frame(), "song", 100, ts=ts)
    assert p1 is not None and p2 is not None
    assert p1 != p2
    assert p2.name.endswith("_2.png")


def test_set_enabled_runtime_toggle(tmp_path: Path) -> None:
    w = ResultWriter(enabled=False, output_dir=tmp_path)
    assert w.save(_frame(), "song", 100) is None
    w.set_enabled(True)
    assert w.save(_frame(), "song", 100) is not None
