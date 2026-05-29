"""data/banner_features.json を実サンプルにかけて Top-K を表示する検証スクリプト。

PoC #04 §7.6 のリプレイ版。本実装で生成した特徴量マスタが、tests/fixtures/sample/
リザルト画面・選曲画面に対して妥当な楽曲を返すかを確認する。

選曲画面の ROI は v2.0 スコープ外（詳細設計 §13.2）のため、
複数の候補 ROI を試して挙動を観察する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows ターミナルの cp932 を回避して UTF-8 出力を強制（日本語タイトル表示用）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from livelyrec.application.banner_match_service import BannerMatchService  # noqa: E402
from livelyrec.infrastructure.banner_features import (  # noqa: E402
    DEFAULT_TARGET_SIZE,
    dhash64,
    hamming,
    phash64,
    prepare_gray,
)
from livelyrec.infrastructure.recognizer.roi_defs import (  # noqa: E402
    PREPARE_ROI,
    RESULT_ROI,
)

REPO = Path(__file__).resolve().parents[2]


def load_master_index(master_path: Path) -> dict[str, str]:
    """song_id → title の辞書を返す。"""
    data = json.loads(master_path.read_text(encoding="utf-8"))
    return {s["song_id"]: s["title"] for s in data["songs"]}


def topk_for_frame(
    svc: BannerMatchService,
    frame_bgr: np.ndarray,
    roi: tuple[int, int, int, int],
    k: int = 3,
) -> list[tuple[str, int]]:
    """SAvc 内部の特徴量集合を上から走査し Top-K (song_id, distance) を返す。"""
    gray = prepare_gray(frame_bgr, roi, svc.target_size)
    if gray is None:
        return []
    q_p = phash64(gray)
    q_d = dhash64(gray)
    scored: list[tuple[int, str]] = []
    for feat in svc._features:  # type: ignore[attr-defined]  # PoC スクリプト故に privé 参照
        d = hamming(q_p, feat.phash) + hamming(q_d, feat.dhash)
        scored.append((d, feat.song_id))
    scored.sort()
    return [(sid, d) for d, sid in scored[:k]]


def imread_path(path: Path) -> np.ndarray | None:
    """日本語パス対応の cv2.imread。"""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def run_set(
    name: str,
    samples: list[Path],
    rois: list[tuple[str, tuple[int, int, int, int]]],
    svc: BannerMatchService,
    title_of: dict[str, str],
) -> None:
    print(f"\n========== {name} ==========")
    for sample in samples:
        img = imread_path(sample)
        if img is None:
            print(f"  [skip] {sample.name}: cannot decode")
            continue
        h, w = img.shape[:2]
        if (w, h) != (1366, 768):
            print(f"  [skip] {sample.name}: shape={w}x{h} (need 1366x768)")
            continue
        print(f"\n  {sample.name}")
        for roi_name, roi in rois:
            top3 = topk_for_frame(svc, img, roi, k=3)
            ph_d = top3[0][1] if top3 else 999
            print(f"    ROI={roi_name:<14} {roi}")
            for rank, (sid, d) in enumerate(top3, start=1):
                title = title_of.get(sid, "(unknown)")
                marker = " <- accepted" if rank == 1 and d <= 20 else ""
                print(f"      {rank}. d={d:>3}  {title[:40]:40s}  ({sid}){marker}")
            if not top3:
                print("      (no candidates)")


def main() -> int:
    features_path = REPO / "data" / "banner_features.json"
    master_path = REPO / "data" / "master.json"
    svc = BannerMatchService.from_json(features_path)
    title_of = load_master_index(master_path)
    print(
        f"loaded {svc.feature_count} banner features, "
        f"target_size={svc.target_size}"
    )

    # --- リザルト画面: 公式仕様の banner ROI ---
    result_samples = sorted((REPO / "tests/fixtures/sample/リザルト画面").glob("*.png"))
    run_set(
        "RESULT 画面（RESULT_ROI['banner']）",
        result_samples,
        [("RESULT.banner", RESULT_ROI["banner"])],
        svc,
        title_of,
    )

    # --- 選曲画面: v2.0 スコープ外。試しに複数の候補 ROI で挙動を観察 ---
    select_samples = sorted((REPO / "tests/fixtures/sample/選曲画面").glob("*.png"))
    rois = [
        ("PREPARE.song_banner", PREPARE_ROI["logo"]),  # 準備画面の楽曲ロゴ枠
        ("RESULT.banner@center", RESULT_ROI["banner"]),  # 参考：センター位置試行
    ]
    run_set(
        "SELECT 画面（v2.0 スコープ外、候補 ROI を試行）",
        select_samples[:10],  # 多すぎるので先頭 10
        rois,
        svc,
        title_of,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
