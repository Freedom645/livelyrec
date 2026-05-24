"""BAD ROI で数字上部が見切れる原因を視覚化する診断スクリプト。

ユーザ指摘の候補ファイル（templates/digits/.../<digit>/<stem>_bad_<idx>.png）について:
  パネル1: BAD ROI 周辺の生画像（ROI 矩形 = 赤）
  パネル2: ROI を上下に拡張した領域の色マスク（白）
           → どの範囲が「BAD色」と認識されているか可視化
  パネル3: 連結成分（ROI 内ベース）の bounding box（緑）と
           注目している idx 番目のボックス（黄）
           → 実際に抽出されるパッチがどの範囲か可視化

Usage:
    python scripts/diagnose_bad_clipping.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.ocr.digit_template import JUDGE_COLOR  # noqa: E402
from livelyrec.infrastructure.recognizer.normalize import crop, normalize_frame  # noqa: E402
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI  # noqa: E402

SAMPLE_DIR = Path("tests/fixtures/sample/リザルト画面")
OUT_DIR = Path("tests/fixtures/sample/_bad_clipping_diag")

TARGETS = [
    ("0", "Screenshot 2026-05-18 12-20-06_bad_1.png"),
    ("0", "Screenshot 2026-05-18 12-20-06_bad_2.png"),
    ("0", "Screenshot 2026-05-18 12-28-30_bad_0.png"),
    ("1", "Screenshot 2026-05-18 12-20-06_bad_0.png"),
    ("2", "Screenshot 2026-05-18 12-22-44_bad_0.png"),
    ("2", "Screenshot 2026-05-18 12-23-54_bad_1.png"),
    ("6", "Screenshot 2026-05-18 12-22-44_bad_1.png"),
    ("8", "Screenshot 2026-05-18 12-27-52_bad_0.png"),
]

CAND_RE = re.compile(r"^(?P<stem>.+)_(?P<judge>bad|cool|great|good)_(?P<idx>\d+)\.png$")

PAD_TOP = 40
PAD_BOTTOM = 30
PAD_X = 20
SCALE = 4


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


def _find_jp_font(size: int = 14) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def _color_mask_bare(roi_bgr: np.ndarray, color) -> np.ndarray:
    """指定色範囲のマスク（モルフォロジ無し / 抽出と完全に同一の HSV 条件）。"""
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    if color.h_lo <= color.h_hi:
        m = cv2.inRange(hsv, (color.h_lo, color.s_min, color.v_min), (color.h_hi, 255, 255))
    else:
        m1 = cv2.inRange(hsv, (0, color.s_min, color.v_min), (color.h_hi, 255, 255))
        m2 = cv2.inRange(hsv, (color.h_lo, color.s_min, color.v_min), (180, 255, 255))
        m = cv2.bitwise_or(m1, m2)
    return m


def _color_mask_morph(mask: np.ndarray) -> np.ndarray:
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)


def _extract_candidate_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    h_full = mask.shape[0]
    for i in range(1, n_labels):
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if h < max(12, int(h_full * 0.25)) or area < 30:
            continue
        if w / max(h, 1) > 2.0 or h / max(w, 1) > 6.0:
            continue
        boxes.append((x, y, w, h))
    return sorted(boxes, key=lambda b: b[0])


def _annotate(img: np.ndarray, lines: list[str]) -> np.ndarray:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)
    font = _find_jp_font(15)
    h = 22 * len(lines) + 8
    draw.rectangle([(0, pil.height - h), (pil.width, pil.height)], fill=(0, 0, 0))
    for i, line in enumerate(lines):
        draw.text((10, pil.height - h + 4 + i * 22), line, fill=(255, 220, 100), font=font)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _title_bar(img: np.ndarray, title: str) -> np.ndarray:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)
    font = _find_jp_font(18)
    draw.rectangle([(0, 0), (pil.width, 28)], fill=(0, 0, 0))
    draw.text((10, 4), title, fill=(255, 255, 255), font=font)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def diagnose(digit_label: str, cand_name: str) -> dict | None:
    m = CAND_RE.match(cand_name)
    if not m:
        print(f"  skip: {cand_name}")
        return None
    stem, judge, idx = m.group("stem"), m.group("judge"), int(m.group("idx"))

    sample = _imread_unicode(SAMPLE_DIR / f"{stem}.png")
    if sample is None:
        print(f"  sample not found: {stem}.png")
        return None
    norm = normalize_frame(sample)
    full = norm.image_bgr

    roi_x1, roi_y1, roi_x2, roi_y2 = RESULT_ROI[judge]
    roi_w, roi_h = roi_x2 - roi_x1, roi_y2 - roi_y1
    color = JUDGE_COLOR[judge]

    # === 拡張領域（ROI 上下に余白を取って参考表示） ===
    ex_x1 = max(0, roi_x1 - PAD_X)
    ex_y1 = max(0, roi_y1 - PAD_TOP)
    ex_x2 = min(full.shape[1], roi_x2 + PAD_X)
    ex_y2 = min(full.shape[0], roi_y2 + PAD_BOTTOM)
    ex_bgr = full[ex_y1:ex_y2, ex_x1:ex_x2].copy()
    ex_h, ex_w = ex_bgr.shape[:2]

    # 拡張領域の色マスク（モルフォロジ無し / morph 有り）
    mask_ex_raw = _color_mask_bare(ex_bgr, color)
    mask_ex_morph = _color_mask_morph(mask_ex_raw)

    # ROI 内のマスク（実際の抽出と同条件）
    roi_bgr = crop(full, RESULT_ROI[judge])
    mask_roi = _color_mask_morph(_color_mask_bare(roi_bgr, color))
    boxes_roi = _extract_candidate_boxes(mask_roi)

    # --- パネル1: BAD ROI 周辺の生画像 + ROI 矩形 ---
    p1 = ex_bgr.copy()
    p1 = cv2.resize(p1, (ex_w * SCALE, ex_h * SCALE), interpolation=cv2.INTER_NEAREST)
    cv2.rectangle(
        p1,
        ((roi_x1 - ex_x1) * SCALE, (roi_y1 - ex_y1) * SCALE),
        ((roi_x2 - ex_x1) * SCALE, (roi_y2 - ex_y1) * SCALE),
        (0, 0, 255), 2,
    )
    p1 = _title_bar(p1, "(1) 拡張領域の生画像 / 赤枠 = BAD ROI")

    # --- パネル2: 色マスク（白 = BAD色とみなされた範囲） ---
    p2_gray = mask_ex_morph
    p2_bgr = cv2.cvtColor(p2_gray, cv2.COLOR_GRAY2BGR)
    # ROI 範囲を赤線で重ねる
    cv2.rectangle(
        p2_bgr,
        (roi_x1 - ex_x1, roi_y1 - ex_y1),
        (roi_x2 - ex_x1, roi_y2 - ex_y1),
        (0, 0, 255), 1,
    )
    p2 = cv2.resize(p2_bgr, (ex_w * SCALE, ex_h * SCALE), interpolation=cv2.INTER_NEAREST)
    p2 = _title_bar(
        p2,
        f"(2) HSV カラーマスク (BAD色: H={color.h_lo}-{color.h_hi} S>={color.s_min} V>={color.v_min})",
    )

    # --- パネル3: ROI 内連結成分 ---
    p3 = ex_bgr.copy()
    p3 = cv2.resize(p3, (ex_w * SCALE, ex_h * SCALE), interpolation=cv2.INTER_NEAREST)
    # ROI 枠
    cv2.rectangle(
        p3,
        ((roi_x1 - ex_x1) * SCALE, (roi_y1 - ex_y1) * SCALE),
        ((roi_x2 - ex_x1) * SCALE, (roi_y2 - ex_y1) * SCALE),
        (0, 0, 255), 2,
    )
    # 連結成分の bbox（ROI ローカル → 拡張領域ローカルへ変換）
    yellow_box = None
    for i, (x, y, w, h) in enumerate(boxes_roi):
        gx1 = (roi_x1 + x - ex_x1) * SCALE
        gy1 = (roi_y1 + y - ex_y1) * SCALE
        gx2 = (roi_x1 + x + w - ex_x1) * SCALE
        gy2 = (roi_y1 + y + h - ex_y1) * SCALE
        col = (0, 255, 255) if i == idx else (0, 255, 0)
        thick = 3 if i == idx else 1
        cv2.rectangle(p3, (gx1, gy1), (gx2, gy2), col, thick)
        if i == idx:
            yellow_box = (x, y, w, h)
    p3 = _title_bar(
        p3,
        "(3) 連結成分 bbox (緑=全候補 / 黄=この candidate idx)",
    )

    # --- 各パネルを縦連結 + 情報帯 ---
    info_lines = [
        f"ROI bad = ({roi_x1},{roi_y1})-({roi_x2},{roi_y2})  size {roi_w}x{roi_h}px",
    ]
    if yellow_box:
        x, y, w, h = yellow_box
        info_lines.append(
            f"抽出 bbox (ROI内) = (x={x}, y={y}) {w}x{h}px  "
            f"(ROI 内で digit の bottom={y + h}/{roi_h}, top={y}/{roi_h})"
        )
        info_lines.append(
            "→ パッチは色マスクが取れた範囲の bounding box。"
            "色マスクが digit 上部を拾えていなければ、その分上部が切れる。"
        )

    # 高さを揃えてパネル化
    sep = np.full((6, p1.shape[1], 3), 80, dtype=np.uint8)
    stacked = np.vstack([p1, sep, p2, sep, p3])
    stacked = _annotate(stacked, info_lines)

    # ファイル先頭にタイトル
    rgb = cv2.cvtColor(stacked, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    font = _find_jp_font(22)
    title_h = 32
    top_band = Image.new("RGB", (pil.width, title_h), (0, 0, 0))
    draw_top = ImageDraw.Draw(top_band)
    draw_top.text((10, 4), f"{cand_name}  (digit label = {digit_label})", fill=(255, 255, 255), font=font)
    final_img = Image.new("RGB", (pil.width, pil.height + title_h))
    final_img.paste(top_band, (0, 0))
    final_img.paste(pil, (0, title_h))
    final = cv2.cvtColor(np.array(final_img), cv2.COLOR_RGB2BGR)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{digit_label}_{cand_name}"
    _imwrite_unicode(out_path, final)

    # ピクセル単位サマリ: ROI 内マスクで「y=0」（ROI 上端）に届く列があるか
    # 真因が「マスクが上部を取りこぼし」なら、ROI 中央 X 付近で mask の最上点 y が下がっている
    has_mask_at_top = int(np.any(mask_roi[0:1, :] > 0))
    if yellow_box:
        x, y, w, h = yellow_box
        col_slice = mask_roi[:, x:x + w]
        top_y_per_col = []
        for c in range(col_slice.shape[1]):
            ys = np.where(col_slice[:, c] > 0)[0]
            if len(ys):
                top_y_per_col.append(int(ys[0]))
        min_top_y = min(top_y_per_col) if top_y_per_col else None
    else:
        min_top_y = None

    print(
        f"{cand_name:55} label={digit_label} "
        f"bbox_top_y={yellow_box[1] if yellow_box else '?':>3} "
        f"mask_at_ROI_top={'YES' if has_mask_at_top else 'no '} "
        f"min_top_y_in_bbox_cols={min_top_y}"
    )

    return None


def main() -> int:
    print(f"\n{'file':55} {'label':>5} bbox_top  mask_at_ROI_top  min_top_y\n")
    for digit_label, cand_name in TARGETS:
        diagnose(digit_label, cand_name)
    print(f"\nwrote diagnostic images to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
