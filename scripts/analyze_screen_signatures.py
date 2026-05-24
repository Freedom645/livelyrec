"""画面判別のシグネチャ分析（工程8 ②）。

debug フレームにユーザ指摘を反映した真ラベルを付与し、低解像度サムネイル
指紋による最近傍分類の正答率（Leave-One-Out）を評価する。

使い方:
    .venv/Scripts/python.exe -m scripts.analyze_screen_signatures
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

DEBUG = Path("livelyrec_data/debug")
FP_W, FP_H = 32, 18  # 指紋サムネイルのサイズ


def true_label(fname: str) -> str:
    """ファイル名から真ラベルを返す（ユーザ指摘の誤判定箇所を補正）。"""
    ts = int(fname[:6])
    if 183206 <= ts <= 183333:
        return "title"
    if 183716 <= ts <= 183719:
        return "load"
    if ts == 183729:
        return "load"
    if 183740 <= ts <= 183814:
        return "quest"
    if ts in (183924, 183929, 184152):
        return "unknown"
    if 184148 <= ts <= 184150:
        return "load"
    if 184158 <= ts <= 184200:
        return "load"
    # 未指摘フレームはファイル名の判定を真ラベルとみなす
    # ファイル名は HHMMSS_mmm_screen.png（screen にアンダースコアを含みうる）
    scr = fname.split("_", 2)[2].rsplit(".", 1)[0]
    if scr == "load_to_ready":
        return "load"
    return scr


def _imread_u(path: Path) -> np.ndarray | None:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


# 試行する特徴領域（画面ごとに安定な UI を探す）
_REGIONS: dict[str, tuple[int, int, int, int] | None] = {
    "全画面": None,
    "右下パネル(1120-1366,590-768)": (1120, 590, 1366, 768),
    "下帯(0-1366,660-768)": (0, 660, 1366, 768),
    "右下小(1150-600-1366-768)": (1150, 600, 1366, 768),
    "右半分下(700-1366,500-768)": (700, 500, 1366, 768),
}


def fingerprint(img: np.ndarray, region: tuple[int, int, int, int] | None) -> np.ndarray:
    crop = img if region is None else img[region[1]:region[3], region[0]:region[2]]
    return (
        cv2.resize(crop, (FP_W, FP_H), interpolation=cv2.INTER_AREA)
        .astype(np.float32)
        .flatten()
    )


def _evaluate(frames: list[tuple[str, str, np.ndarray]]) -> tuple[int, dict]:
    """1-NN（個別フレーム最近傍, Leave-One-Out）の正答率を返す。"""
    labels = [lab for _, lab, _ in frames]
    mat = np.stack([fp for _, _, fp in frames])  # (N, D)
    sq = np.sum(mat * mat, axis=1)
    d2 = sq[:, None] + sq[None, :] - 2.0 * (mat @ mat.T)
    np.fill_diagonal(d2, 1e18)
    nn = np.argmin(d2, axis=1)
    correct = 0
    mistakes: dict[tuple[str, str], int] = defaultdict(int)
    for i, lab in enumerate(labels):
        pred = labels[nn[i]]
        if pred == lab:
            correct += 1
        else:
            mistakes[(lab, pred)] += 1
    return correct, mistakes


def main() -> None:
    imgs: list[tuple[str, str, np.ndarray]] = []
    for f in sorted(DEBUG.glob("*.png")):
        img = _imread_u(f)
        if img is not None:
            imgs.append((f.name, true_label(f.name), img))

    counts: dict[str, int] = defaultdict(int)
    for _, lab, _ in imgs:
        counts[lab] += 1
    print("クラス別件数:", {k: counts[k] for k in sorted(counts)})

    best_region = None
    best_acc = -1.0
    for rname, region in _REGIONS.items():
        frames = [(n, lab, fingerprint(img, region)) for n, lab, img in imgs]
        correct, mistakes = _evaluate(frames)
        acc = 100 * correct / len(frames)
        print(f"\n[{rname}] LOO 正答率: {correct}/{len(frames)} ({acc:.1f}%)")
        for (t, p), c in sorted(mistakes.items(), key=lambda x: -x[1])[:6]:
            print(f"    真 {t} -> 予測 {p}: {c}件")
        if acc > best_acc:
            best_acc, best_region = acc, rname
    print(f"\n最良領域: {best_region} ({best_acc:.1f}%)")


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
