"""SELECT 画面サンプルでバナー領域 ROI をグリッドスイープして探す。

詳細設計 11_詳細設計_バナー認識.md §13.2（未確定事項）の解決を目的とした
PoC スクリプト。

390×94 サイズの ROI を画面の x/y 方向にスライドし、各位置で
BannerMatchService に投じて Top-1 ハミング距離を測る。
- 距離が極端に小さい位置 = 登録済み楽曲のバナーが正しく載っている可能性
- どの位置でも距離が大きい = その楽曲が特徴量マスタに未登録
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from livelyrec.application.banner_match_service import BannerMatchService  # noqa: E402
from livelyrec.infrastructure.banner_features import (  # noqa: E402
    dhash64,
    hamming,
    phash64,
    prepare_gray,
)

REPO = Path(__file__).resolve().parents[2]


def imread_path(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def best_match(svc: BannerMatchService, frame, roi) -> tuple[int, str]:
    gray = prepare_gray(frame, roi, svc.target_size)
    if gray is None:
        return 999, ""
    qp, qd = phash64(gray), dhash64(gray)
    best_d, best_id = 999, ""
    for f in svc._features:  # type: ignore[attr-defined]
        d = hamming(qp, f.phash) + hamming(qd, f.dhash)
        if d < best_d:
            best_d, best_id = d, f.song_id
    return best_d, best_id


def sweep(
    svc: BannerMatchService,
    frame: np.ndarray,
    title_of: dict[str, str],
    *,
    w: int = 390,
    h: int = 94,
    x_step: int = 40,
    y_step: int = 30,
) -> list[tuple[int, tuple[int, int, int, int], str]]:
    H, W = frame.shape[:2]
    out: list[tuple[int, tuple[int, int, int, int], str]] = []
    for y in range(0, H - h, y_step):
        for x in range(0, W - w, x_step):
            roi = (x, y, x + w, y + h)
            d, sid = best_match(svc, frame, roi)
            out.append((d, roi, sid))
    out.sort(key=lambda t: t[0])
    return out


def main() -> int:
    svc = BannerMatchService.from_json(REPO / "data" / "banner_features.json")
    master = json.loads((REPO / "data" / "master.json").read_text(encoding="utf-8"))
    title_of = {s["song_id"]: s["title"] for s in master["songs"]}
    print(f"loaded {svc.feature_count} features\n")

    samples = sorted((REPO / "tests/fixtures/sample/選曲画面").glob("*.png"))[:6]
    for sample in samples:
        img = imread_path(sample)
        if img is None:
            continue
        h, w = img.shape[:2]
        if (w, h) != (1366, 768):
            continue
        print(f"=== {sample.name} ===")
        results = sweep(svc, img, title_of)
        # Top-10 候補
        print(
            f"  best Top-10 over {len(results)} ROI candidates "
            f"(distance / x,y,x2,y2 / song):"
        )
        for d, roi, sid in results[:10]:
            print(f"    d={d:>3}  ROI={roi}  {title_of.get(sid, '?')[:36]}")
        # 距離 ≤ 25 の数（accepted=True しきい値 + 余裕 5）
        good = [r for r in results if r[0] <= 25]
        print(f"  ROIs with distance ≤ 25: {len(good)}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
