"""判定数テンプレ画像の半自動生成スクリプト。

リザルト画面サンプルから色マスクで数字候補を切り出し、
templates/digits/<解像度>/_candidates/ に保存する。
ユーザはこれを目視確認して 0/, 1/, ..., 9/ サブフォルダに振り分け、
最終的に同フォルダ内画像を平均化して 0.png〜9.png を作成する。

Usage:
    python scripts/build_digit_templates.py extract \\
        --sample-dir tests/fixtures/sample/リザルト画面 \\
        --out-dir templates/digits/1366x768

    # 候補を 0/, 1/, ..., 9/ に振り分けたあと:
    python scripts/build_digit_templates.py average \\
        --out-dir templates/digits/1366x768

詳細: docs/design/10_詳細設計_画像認識.md §5.2.4
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from livelyrec.infrastructure.ocr.digit_template import JUDGE_COLOR, ColorRange
from livelyrec.infrastructure.recognizer.normalize import crop, normalize_frame
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI


def _imread_unicode(path: Path) -> np.ndarray | None:
    """日本語パスでも安全に画像を読む（cv2.imread の代替）。"""
    try:
        with Image.open(path) as im:
            return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _imwrite_unicode(path: Path, img: np.ndarray) -> bool:
    """日本語パスでも安全に画像を保存する。"""
    try:
        ext = path.suffix.lower() or ".png"
        ok, buf = cv2.imencode(ext, img)
        if not ok:
            return False
        path.write_bytes(buf.tobytes())
        return True
    except Exception:
        return False


def _color_mask(roi_bgr: np.ndarray, color: ColorRange) -> np.ndarray:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    if color.h_lo <= color.h_hi:
        m = cv2.inRange(hsv, (color.h_lo, color.s_min, color.v_min), (color.h_hi, 255, 255))
    else:
        m1 = cv2.inRange(hsv, (0, color.s_min, color.v_min), (color.h_hi, 255, 255))
        m2 = cv2.inRange(hsv, (color.h_lo, color.s_min, color.v_min), (180, 255, 255))
        m = cv2.bitwise_or(m1, m2)
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel)


def _extract_candidates(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates: list[tuple[int, int, int, int]] = []
    h_full = mask.shape[0]
    for i in range(1, n_labels):
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        # 高さ閾値: 絶対値 12px もしくは ROI 高さの 25% のうち大きい方
        if h < max(12, int(h_full * 0.25)) or area < 30:
            continue
        if w / max(h, 1) > 2.0 or h / max(w, 1) > 6.0:
            continue
        candidates.append((x, y, w, h))
    return candidates


def cmd_extract(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    cand_dir = out_dir / "_candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    n_total = 0
    for img_path in sorted(args.sample_dir.glob("*.png")):
        img = _imread_unicode(img_path)
        if img is None:
            print(f"skip (read failed): {img_path}")
            continue
        norm = normalize_frame(img)
        for judge in ("cool", "great", "good", "bad"):
            roi = crop(norm.image_bgr, RESULT_ROI[judge])
            color = JUDGE_COLOR[judge]
            mask = _color_mask(roi, color)
            boxes = _extract_candidates(mask)
            # 数字の自然順に並べる（左→右）。これで _0, _1, _2 が左端から順に対応する
            boxes_sorted = sorted(boxes, key=lambda b: b[0])
            for idx, (x, y, w, h) in enumerate(boxes_sorted):
                patch = mask[y:y + h, x:x + w]
                name = f"{img_path.stem}_{judge}_{idx}.png"
                _imwrite_unicode(cand_dir / name, patch)
                n_total += 1

    print(f"saved {n_total} candidate patches to {cand_dir}")
    print("次の手順:")
    print(f"  1. {out_dir} 配下に 0/, 1/, ..., 9/ サブフォルダを作る")
    print(f"  2. {cand_dir} の画像を該当数字フォルダへ振り分ける")
    print(f"  3. python scripts/build_digit_templates.py average --out-dir {out_dir}")
    return 0


def cmd_average(args: argparse.Namespace) -> int:
    """振り分け済み 0/..9/ 配下の画像を平均化して 0.png..9.png を生成する。"""
    out_dir: Path = args.out_dir
    target_size = (args.size, args.size * 2) if args.size else None  # (w, h) 統一サイズ。Heightが2倍は数字の縦長想定。
    n_written = 0
    for d in range(10):
        folder = out_dir / str(d)
        if not folder.is_dir():
            print(f"skip digit {d} (no folder)")
            continue
        images: list[np.ndarray] = []
        for f in sorted(folder.glob("*.png")):
            img = _imread_unicode(f)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, bw = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            if target_size is None:
                target_size = (bw.shape[1], bw.shape[0])
            resized = cv2.resize(bw, target_size, interpolation=cv2.INTER_NEAREST)
            images.append(resized)
        if not images:
            print(f"skip digit {d} (no images)")
            continue
        stacked = np.stack(images, axis=0).astype(np.float32)
        mean = stacked.mean(axis=0)
        _, template = cv2.threshold(mean.astype(np.uint8), 127, 255, cv2.THRESH_BINARY)
        out_path = out_dir / f"{d}.png"
        _imwrite_unicode(out_path, template)
        n_written += 1
        print(f"wrote {out_path} (averaged {len(images)} images)")
    print(f"done. {n_written}/10 digit templates written.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="判定数テンプレ画像の半自動生成")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    p_ext = subparsers.add_parser("extract", help="サンプルから候補画像を切り出す")
    p_ext.add_argument("--sample-dir", required=True, type=Path)
    p_ext.add_argument("--out-dir", required=True, type=Path)
    p_ext.add_argument("--clean", action="store_true", help="出力先を消してから生成")
    p_ext.set_defaults(func=cmd_extract)

    p_avg = subparsers.add_parser("average", help="振り分け済みフォルダから平均テンプレを生成")
    p_avg.add_argument("--out-dir", required=True, type=Path)
    p_avg.add_argument("--size", type=int, default=None,
                       help="統一する幅(px)。指定時、高さは自動的に2倍。未指定なら最初の画像サイズに合わせる")
    p_avg.set_defaults(func=cmd_average)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
