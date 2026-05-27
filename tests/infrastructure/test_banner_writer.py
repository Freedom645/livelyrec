"""BannerWriter のテスト（FR-DEV-002〜003）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from livelyrec.infrastructure.banner_writer import BannerWriter

# PO 指定の banner ROI（x=489,y=233,w=390,h=94 → (489,233,879,327)）
_BANNER_ROI = (489, 233, 879, 327)


def _frame_1366x768() -> np.ndarray:
    f = np.zeros((768, 1366, 3), dtype=np.uint8)
    f[:, :, 2] = 200  # 赤
    return f


def test_save_skipped_when_disabled(tmp_path: Path) -> None:
    w = BannerWriter(enabled=False, output_dir=tmp_path, banner_roi=_BANNER_ROI)
    assert w.save(_frame_1366x768(), "song") is None
    assert not list(tmp_path.iterdir())


def test_save_creates_cropped_png(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = BannerWriter(enabled=True, output_dir=tmp_path, banner_roi=_BANNER_ROI)
    path = w.save(_frame_1366x768(), "ぽぽぽかレトロード", ts=ts)
    assert path is not None
    assert path.name == "2026-05-28_19-30-45_ぽぽぽかレトロード_banner.png"
    assert path.exists()
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_save_unknown_when_no_title(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = BannerWriter(enabled=True, output_dir=tmp_path, banner_roi=_BANNER_ROI)
    path = w.save(_frame_1366x768(), None, ts=ts)
    assert path is not None
    assert path.name == "2026-05-28_19-30-45_unknown_banner.png"


def test_save_returns_none_when_roi_out_of_frame(tmp_path: Path) -> None:
    # フレームが小さすぎて ROI がはみ出るケース
    small = np.zeros((100, 100, 3), dtype=np.uint8)
    w = BannerWriter(enabled=True, output_dir=tmp_path, banner_roi=_BANNER_ROI)
    assert w.save(small, "song") is None


def test_save_collision_suffix(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 28, 19, 30, 45)
    w = BannerWriter(enabled=True, output_dir=tmp_path, banner_roi=_BANNER_ROI)
    p1 = w.save(_frame_1366x768(), "song", ts=ts)
    p2 = w.save(_frame_1366x768(), "song", ts=ts)
    assert p1 is not None and p2 is not None
    assert p2.name.endswith("_2.png")
