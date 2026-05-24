"""画面右下領域 (1286, 672, 61, 82) を各画面サンプルから切り出して並べる診断スクリプト。

ユーザ提案: 画面右下が各画面でほぼ固定 → 画面判別のシグネチャに使えるかを検証する。

Usage:
    python scripts/diagnose_bottom_right.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.recognizer.normalize import normalize_frame  # noqa: E402

SAMPLE_ROOT = Path("tests/fixtures/sample")
OUT_PATH = Path("tests/fixtures/sample/_bottom_right_signature.png")

# (x, y, w, h) = (1286, 672, 61, 82)
BR = (1286, 672, 1286 + 61, 672 + 82)

CATEGORIES = [
    "選曲画面",
    "準備画面前ロード画面",
    "準備画面",
    "オプション画面",
    "プレイ画面前ロード画面",
    "プレイ画面",
    "リザルト画面",
]

CELL_SCALE = 4
GRID_GAP = 8
CELL_LABEL_H = 24


def _imread_unicode(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _imwrite_unicode(path: Path, img: np.ndarray) -> bool:
    ext = path.suffix.lower() or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    path.write_bytes(buf.tobytes())
    return True


def _find_jp_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for c in (
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
    ):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def crop_bottom_right(img_bgr: np.ndarray) -> np.ndarray:
    norm = normalize_frame(img_bgr)
    x1, y1, x2, y2 = BR
    return norm.image_bgr[y1:y2, x1:x2]


def compute_signature(crop_bgr: np.ndarray) -> dict:
    """切り出し領域から特徴量を計算する。"""
    h, w = crop_bgr.shape[:2]
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    mean_bgr = crop_bgr.mean(axis=(0, 1))
    return {
        "size": (w, h),
        "mean_b": float(mean_bgr[0]),
        "mean_g": float(mean_bgr[1]),
        "mean_r": float(mean_bgr[2]),
        "brightness": float(gray.mean()),
        "std_brightness": float(gray.std()),
        "mean_h": float(hsv[..., 0].mean()),
        "mean_s": float(hsv[..., 1].mean()),
        "mean_v": float(hsv[..., 2].mean()),
    }


def main() -> int:
    rows: list[tuple[str, str, np.ndarray, dict]] = []
    for cat in CATEGORIES:
        cat_dir = SAMPLE_ROOT / cat
        if not cat_dir.exists():
            continue
        for img_path in sorted(cat_dir.glob("*.png")):
            img = _imread_unicode(img_path)
            if img is None:
                continue
            crop = crop_bottom_right(img)
            sig = compute_signature(crop)
            rows.append((cat, img_path.stem, crop, sig))

    if not rows:
        print("no samples found")
        return 1

    # グリッド出力: カテゴリごとに行を作る
    cell_w = (BR[2] - BR[0]) * CELL_SCALE
    cell_h = (BR[3] - BR[1]) * CELL_SCALE
    cell_total_h = cell_h + CELL_LABEL_H

    # カテゴリごとにグループ化
    by_cat: dict[str, list[tuple[str, np.ndarray, dict]]] = {}
    for cat, stem, crop, sig in rows:
        by_cat.setdefault(cat, []).append((stem, crop, sig))

    max_per_row = max(len(v) for v in by_cat.values())
    grid_w = 200 + max_per_row * (cell_w + GRID_GAP) + GRID_GAP
    grid_h = len(by_cat) * (cell_total_h + GRID_GAP) + 64

    canvas = Image.new("RGB", (grid_w, grid_h), (28, 28, 28))
    draw = ImageDraw.Draw(canvas)
    font_title = _find_jp_font(20)
    font_label = _find_jp_font(13)
    font_cat = _find_jp_font(16)

    draw.rectangle([(0, 0), (grid_w, 40)], fill=(0, 0, 0))
    draw.text(
        (10, 8),
        f"右下シグネチャ (x={BR[0]}..{BR[2]-1}, y={BR[1]}..{BR[3]-1})",
        fill=(255, 255, 255),
        font=font_title,
    )

    y = 50
    for cat, entries in by_cat.items():
        draw.text((10, y + cell_h // 2 - 8), cat, fill=(255, 220, 100), font=font_cat)
        x = 200
        for stem, crop, sig in entries:
            resized = cv2.resize(crop, (cell_w, cell_h), interpolation=cv2.INTER_NEAREST)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            pil_cell = Image.fromarray(rgb)
            canvas.paste(pil_cell, (x, y))
            # ラベル: stem 末尾と特徴量
            short = stem.split()[-1] if " " in stem else stem
            line = f"{short}"
            line2 = f"B={sig['brightness']:.0f}±{sig['std_brightness']:.0f} HSV=({sig['mean_h']:.0f},{sig['mean_s']:.0f},{sig['mean_v']:.0f})"
            draw.text(
                (x, y + cell_h + 2),
                line,
                fill=(220, 220, 220),
                font=font_label,
            )
            draw.text(
                (x, y + cell_h + 14),
                line2,
                fill=(180, 180, 180),
                font=font_label,
            )
            x += cell_w + GRID_GAP
        y += cell_total_h + GRID_GAP

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT_PATH)

    # コンソール: カテゴリごとの代表特徴値
    print(f"\nwrote {OUT_PATH}\n")
    print(f"{'category':<28} {'samples':>7} {'B(avg±std)':<14} "
          f"{'HSV(mean H,S,V)':<22}")
    for cat, entries in by_cat.items():
        bvals = np.array([s["brightness"] for _, _, s in entries])
        hsvals = np.array([(s["mean_h"], s["mean_s"], s["mean_v"]) for _, _, s in entries])
        print(
            f"{cat:<28} {len(entries):>7d} "
            f"{bvals.mean():>5.1f}±{bvals.std():>4.1f}    "
            f"({hsvals[:,0].mean():>5.1f},{hsvals[:,1].mean():>5.1f},{hsvals[:,2].mean():>5.1f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
