"""PoC #04: バナー画像特徴量計算とマッチング試作

詳細: docs/design/poc/04_banner_recognition.md §4.2 / §4.3

入力:
- 参照バナー画像ディレクトリ（`banner_collect.py` の出力）
- master.json
- リザルト画面キャプチャ（テスト用、tests/fixtures/sample/リザルト画面/）

処理:
1. ファイル名 → master.json タイトルの rapidfuzz マッチ（タイトルマッチング精度）
2. 参照バナーの pHash / dHash を計算 → 特徴量 JSON 出力
3. リザルト画面キャプチャから RESULT_ROI["banner"] (489,233,879,327) を切り出し、参照集合との
   ハミング距離 Top-K を表示（認識精度）

設計方針:
- リファレンスバナーは「livelyのバナー規格 390×94」へリサイズ正規化してから特徴量計算
- pHash は OpenCV の `img_hash.PHash` ではなく自前実装（DCT 8x8）
  → 環境依存（contrib モジュール）を避ける
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

try:
    from rapidfuzz import process as rf_process
    from rapidfuzz import fuzz as rf_fuzz
except ImportError:  # pragma: no cover
    rf_process = None
    rf_fuzz = None

logger = logging.getLogger("banner_match")

# RESULT_ROI["banner"] from livelyrec/infrastructure/recognizer/roi_defs.py
RESULT_BANNER_ROI = (489, 233, 879, 327)
TARGET_SIZE = (390, 94)  # lively bannerの規格 (W, H)


def normalize_title_from_filename(fname: str) -> str:
    """`1_DISCO_KING.png` → 'DISCO KING'（先頭シリーズ番号を落とす）"""
    stem = Path(fname).stem
    # 先頭の数字+アンダースコア（シリーズ番号）を削る: '10_HEAVEN' → 'HEAVEN'
    parts = stem.split("_")
    if parts and parts[0].isdigit():
        parts = parts[1:]
    # 末尾の CS6 / pnm6 / old 等のサフィックスも候補削除
    suffix_skip = {"CS6", "CS7", "CS8", "CS9", "CS10", "CS11", "CS12", "CS13",
                   "CS14", "CS15", "CS16", "pnm6", "pnm7", "pnm8", "old"}
    if parts and parts[-1] in suffix_skip:
        parts = parts[:-1]
    return " ".join(parts)


def fuzzy_match_master(
    query: str, master: list[dict], score_cutoff: int = 60
) -> tuple[str | None, int]:
    """master.json の楽曲タイトルに対するファジーマッチ。Top-1 を返す。"""
    if rf_process is None:
        return None, 0
    titles = [m["title"] for m in master]
    result = rf_process.extractOne(
        query, titles, scorer=rf_fuzz.WRatio, score_cutoff=score_cutoff
    )
    if result is None:
        return None, 0
    matched, score, _idx = result
    return matched, int(score)


def phash64(img_gray: np.ndarray) -> int:
    """DCT ベースの 64bit Perceptual Hash"""
    # 32x32 に縮小 → DCT → 左上 8x8 → 中央値で 0/1
    small = cv2.resize(img_gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(small))
    block = dct[:8, :8]
    # DC 成分を除いた中央値
    flat = block.flatten()
    median = np.median(flat[1:])
    bits = (flat > median).astype(np.uint8)
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return h


def dhash64(img_gray: np.ndarray) -> int:
    """Difference Hash 64bit"""
    small = cv2.resize(img_gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    h = 0
    for b in diff.flatten():
        h = (h << 1) | int(b)
    return h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def load_and_prep(path: Path) -> np.ndarray | None:
    """画像読み込み → ターゲットサイズへリサイズ → グレースケール化"""
    # cv2.imread は日本語パスに弱いため bytes 経由
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except OSError:
        return None
    if img is None:
        return None
    resized = cv2.resize(img, TARGET_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)


def build_features(ref_dir: Path) -> list[dict]:
    feats = []
    for p in sorted(ref_dir.glob("*.png")):
        gray = load_and_prep(p)
        if gray is None:
            logger.warning("skip unreadable: %s", p)
            continue
        feats.append(
            {
                "file": p.name,
                "phash": phash64(gray),
                "dhash": dhash64(gray),
            }
        )
    return feats


def cmd_titlematch(args: argparse.Namespace) -> int:
    ref_dir = Path(args.ref_dir)
    with open(args.master_json, encoding="utf-8") as f:
        master_doc = json.load(f)
    master = master_doc["songs"]
    files = sorted(ref_dir.glob("*.png"))
    logger.info("master songs=%d, ref files=%d", len(master), len(files))

    hits = 0
    for p in files:
        q = normalize_title_from_filename(p.name)
        matched, score = fuzzy_match_master(q, master, score_cutoff=args.score_cutoff)
        flag = "OK" if matched else "--"
        if matched:
            hits += 1
        print(f"  [{flag}] {p.name:32s} → '{q}' → '{matched}' ({score})")
    print(f"\nfuzzy match: {hits}/{len(files)} = {100 * hits / max(1, len(files)):.1f}%")
    return 0


def cmd_features(args: argparse.Namespace) -> int:
    ref_dir = Path(args.ref_dir)
    feats = build_features(ref_dir)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_doc = {
        "ref_dir": str(ref_dir),
        "target_size": list(TARGET_SIZE),
        "count": len(feats),
        "items": feats,
    }
    out_path.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("wrote %d features to %s", len(feats), out_path)
    # ベンチ
    if feats:
        gray = load_and_prep(ref_dir / feats[0]["file"])
        n = 200
        t0 = time.perf_counter()
        for _ in range(n):
            phash64(gray)
        t_p = (time.perf_counter() - t0) / n * 1000
        t0 = time.perf_counter()
        for _ in range(n):
            dhash64(gray)
        t_d = (time.perf_counter() - t0) / n * 1000
        # Top-K (1347 件想定で Hamming sort)
        ref = feats[0]["phash"]
        targets = [f["phash"] for f in feats] * (1347 // max(1, len(feats)) + 1)
        targets = targets[:1347]
        t0 = time.perf_counter()
        for _ in range(20):
            _ = sorted([(hamming(ref, t), t) for t in targets])[:5]
        t_topk = (time.perf_counter() - t0) / 20 * 1000
        print(f"\nbench (avg of n=200):")
        print(f"  phash64: {t_p:.3f} ms")
        print(f"  dhash64: {t_d:.3f} ms")
        print(f"  top-5 over 1347 entries (phash): {t_topk:.3f} ms")
    return 0


def cmd_recognize(args: argparse.Namespace) -> int:
    """既存リザルトサンプル画像から RESULT_ROI["banner"] を切り出し、参照集合と照合"""
    ref_dir = Path(args.ref_dir)
    feats = build_features(ref_dir)
    logger.info("loaded %d reference features", len(feats))

    sample_dir = Path(args.sample_dir)
    samples = sorted(sample_dir.glob("*.png"))
    if not samples:
        print(f"no samples found in {sample_dir}")
        return 1

    x1, y1, x2, y2 = RESULT_BANNER_ROI
    for sp in samples:
        data = np.fromfile(str(sp), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            print(f"  [SKIP] {sp.name}: unreadable")
            continue
        h, w = img.shape[:2]
        # 1366×768 想定。それ以外は ROI が範囲外になる可能性あるのでスキップ
        if (w, h) != (1366, 768):
            print(f"  [SKIP] {sp.name}: shape={w}x{h} (require 1366x768)")
            continue
        crop = img[y1:y2, x1:x2]
        crop_resized = cv2.resize(crop, TARGET_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2GRAY)
        q_phash = phash64(gray)
        q_dhash = dhash64(gray)
        scored = [
            (hamming(q_phash, f["phash"]), hamming(q_dhash, f["dhash"]), f["file"])
            for f in feats
        ]
        scored.sort(key=lambda x: x[0] + x[1])
        print(f"\n{sp.name}: ROI crop {x2-x1}x{y2-y1} → resized {TARGET_SIZE}")
        for d_p, d_d, name in scored[:5]:
            print(f"  ph={d_p:2d} dh={d_d:2d}  {name}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("titlematch", help="ファイル名 ↔ master.json タイトルマッチ評価")
    pt.add_argument("--ref-dir", required=True)
    pt.add_argument(
        "--master-json", default=str(Path(__file__).parents[2] / "data" / "master.json")
    )
    pt.add_argument("--score-cutoff", type=int, default=60)
    pt.set_defaults(func=cmd_titlematch)

    pf = sub.add_parser("features", help="特徴量計算 + ベンチ")
    pf.add_argument("--ref-dir", required=True)
    pf.add_argument("--out", default="./poc_out/banner_features.json")
    pf.set_defaults(func=cmd_features)

    pr = sub.add_parser(
        "recognize", help="リザルト画面サンプルに対する Top-K マッチ"
    )
    pr.add_argument("--ref-dir", required=True)
    pr.add_argument(
        "--sample-dir",
        default=str(
            Path(__file__).parents[2]
            / "tests"
            / "fixtures"
            / "sample"
            / "リザルト画面"
        ),
    )
    pr.set_defaults(func=cmd_recognize)

    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
