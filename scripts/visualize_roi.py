"""ROI を視覚化するスクリプト。

各サンプル画面に対し、ROI 矩形をオーバーレイ表示した PNG を出力する。
これにより画像認識が参照する領域が適切かどうか目視確認できる。

Usage:
    python scripts/visualize_roi.py
    python scripts/visualize_roi.py --out-dir tests/fixtures/sample/_roi_overlay
    python scripts/visualize_roi.py --all   # 各カテゴリの全サンプルに描画

詳細: docs/design/10_詳細設計_画像認識.md §4, livelyrec/infrastructure/recognizer/roi_defs.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.recognizer.normalize import normalize_frame  # noqa: E402
from livelyrec.infrastructure.recognizer.roi_defs import (  # noqa: E402
    OPTION_ROI,
    PLAY_ROI,
    PRELOAD_ROI,
    PREPARE_ROI,
    RESULT_ROI,
    SCREEN_DETECT_REGIONS,
    SCREEN_OPTION_DOT0_ROI,
    SCREEN_RESULT_DOT8_ROI,
    SCREEN_SIGNATURE_ROI,
    SELECT_ROI,
)

# 右下シグネチャ系 ROI を dict 化（描画用）
SCREEN_SIGNATURE_REGIONS: dict[str, tuple[int, int, int, int]] = {
    "signature_br":  SCREEN_SIGNATURE_ROI,
    "result_dot_8":  SCREEN_RESULT_DOT8_ROI,
    "option_dot_0":  SCREEN_OPTION_DOT0_ROI,
}

# 各 ROI に色（BGR）を割り当て
COLORS_PLAY: dict[str, tuple[int, int, int]] = {
    "song_name":  (0, 255, 255),
    "difficulty": (255, 0, 255),
    "score":      (0, 200, 0),
    "combo":      (255, 0, 0),
    "speed":      (0, 128, 255),
}

COLORS_RESULT: dict[str, tuple[int, int, int]] = {
    "clear_label": (0, 255, 255),
    "score":       (0, 200, 0),
    "cool":        (255, 0, 255),  # マゼンタ
    "great":       (0, 255, 255),  # 黄
    "good":        (0, 0, 255),    # 赤
    "bad":         (255, 255, 0),  # シアン
    "combo":       (255, 128, 0),
    "best_score":  (128, 255, 0),
    "best_diff":   (200, 200, 200),
}

COLORS_SELECT: dict[str, tuple[int, int, int]] = {
    "logo":       (0, 255, 255),
    "difficulty": (255, 0, 255),
    "level":      (0, 200, 0),
    "artist":     (255, 200, 0),
}

COLORS_OPTION: dict[str, tuple[int, int, int]] = {
    "logo":  (0, 255, 255),
    "level": (0, 200, 0),
}

COLORS_PREPARE: dict[str, tuple[int, int, int]] = {
    "logo":       (0, 255, 255),
    "difficulty": (255, 0, 255),
    "level":      (0, 200, 0),
    "artist":     (255, 200, 0),
    "speed":      (0, 128, 255),
}

COLORS_PRELOAD: dict[str, tuple[int, int, int]] = {
    "red_region":    (0, 0, 255),     # 実色（赤）
    "orange_region": (0, 165, 255),   # 実色（橙）
}

COLORS_DETECT: dict[str, tuple[int, int, int]] = {
    "music_select_logo":         (0, 200, 255),
    "play_top_bar":              (0, 255, 0),
    "result_score_label_block":  (255, 0, 255),
    "option_select_label":       (255, 200, 0),
    "let_enjoy_music_area":      (200, 200, 200),
    "preload_red":               (0, 0, 255),
    "preload_orange":            (0, 165, 255),
}

COLORS_SIGNATURE: dict[str, tuple[int, int, int]] = {
    "signature_br":  (0, 255, 255),   # 黄
    "result_dot_8":  (0, 0, 255),     # 赤（リザルト点灯位置）
    "option_dot_0":  (255, 0, 0),     # 青（オプション点灯位置）
}


def _imread_unicode(path: Path) -> np.ndarray | None:
    """日本語パスでも安全に画像を読む。"""
    try:
        with Image.open(path) as im:
            return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception as exc:
        print(f"  read failed: {path} ({exc})")
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


def _find_jp_font(size: int = 14) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Windows 標準の日本語フォントを優先的に探す。"""
    candidates = [
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\YuGothR.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_rois(
    image_bgr: np.ndarray,
    rois: dict[str, tuple[int, int, int, int]],
    colors: dict[str, tuple[int, int, int]],
    title: str,
) -> np.ndarray:
    """画像に ROI 矩形・ラベルを描画する。"""
    overlay = image_bgr.copy()
    for name, box in rois.items():
        color = colors.get(name, (255, 255, 255))
        x1, y1, x2, y2 = box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
    # 半透明オーバーレイ
    filled = image_bgr.copy()
    for name, box in rois.items():
        color = colors.get(name, (255, 255, 255))
        x1, y1, x2, y2 = box
        cv2.rectangle(filled, (x1, y1), (x2, y2), color, -1)
    blended = cv2.addWeighted(overlay, 0.85, filled, 0.15, 0)

    # PIL でテキスト描画
    rgb = cv2.cvtColor(blended, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_img)
    font = _find_jp_font(14)
    title_font = _find_jp_font(22)

    # タイトルバー
    draw.rectangle([(0, 0), (pil_img.width, 32)], fill=(0, 0, 0))
    draw.text((10, 5), title, fill=(255, 255, 255), font=title_font)

    # 各 ROI のラベル
    for name, box in rois.items():
        color_bgr = colors.get(name, (255, 255, 255))
        color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        label = f"{name} ({x1},{y1}) {w}x{h}"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0] + 6
        th = bbox[3] - bbox[1] + 4
        # ラベルの配置: 上に余白があれば上、無ければ下
        text_y = y1 - th - 1 if y1 >= 32 + th else y2 + 2
        draw.rectangle([(x1, text_y), (x1 + tw, text_y + th)], fill=(0, 0, 0))
        draw.rectangle([(x1, text_y), (x1 + tw, text_y + th)], outline=color_rgb)
        draw.text((x1 + 3, text_y + 1), label, fill=color_rgb, font=font)

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def make_legend(
    rois: dict[str, tuple[int, int, int, int]],
    colors: dict[str, tuple[int, int, int]],
    title: str,
    width: int = 360,
) -> np.ndarray:
    """凡例画像を作成して返す。"""
    font = _find_jp_font(14)
    title_font = _find_jp_font(18)
    row_h = 22
    height = 40 + len(rois) * row_h + 10
    img = Image.new("RGB", (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.text((10, 8), title, fill=(255, 255, 255), font=title_font)
    y = 40
    for name, box in rois.items():
        color_bgr = colors.get(name, (255, 255, 255))
        color_rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
        draw.rectangle([(10, y + 2), (30, y + row_h - 2)], fill=color_rgb)
        x1, y1, x2, y2 = box
        text = f"{name}  {x2-x1}x{y2-y1}px @({x1},{y1})"
        draw.text((38, y + 3), text, fill=(230, 230, 230), font=font)
        y += row_h
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def render_with_legend(
    image_bgr: np.ndarray,
    rois: dict[str, tuple[int, int, int, int]],
    colors: dict[str, tuple[int, int, int]],
    title: str,
) -> np.ndarray:
    """ROI オーバーレイと凡例を横に並べた画像を返す。"""
    overlay = draw_rois(image_bgr, rois, colors, title)
    legend = make_legend(rois, colors, "凡例")
    h1, h2 = overlay.shape[0], legend.shape[0]
    if h2 < h1:
        pad = np.full((h1 - h2, legend.shape[1], 3), 30, dtype=np.uint8)
        legend = np.vstack([legend, pad])
    else:
        legend = legend[:h1]
    return np.hstack([overlay, legend])


def main() -> int:
    parser = argparse.ArgumentParser(description="ROI を視覚化する")
    parser.add_argument(
        "--sample-root",
        type=Path,
        default=Path("tests/fixtures/sample"),
        help="サンプル画像ルート",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tests/fixtures/sample/_roi_overlay"),
        help="オーバーレイ画像の出力先",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="各カテゴリで先頭1枚ではなく全サンプルに描画",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    cat_play = sorted((args.sample_root / "プレイ画面").glob("*.png"))
    cat_result = sorted((args.sample_root / "リザルト画面").glob("*.png"))
    cat_select = sorted((args.sample_root / "選曲画面").glob("*.png"))
    cat_option = sorted((args.sample_root / "オプション画面").glob("*.png"))
    cat_prepare = sorted((args.sample_root / "準備画面").glob("*.png"))
    cat_preload = sorted((args.sample_root / "プレイ画面前ロード画面").glob("*.png"))

    targets: list[tuple[str, dict, dict, Path]] = []

    def add(label: str, rois: dict, colors: dict, paths: list[Path]) -> None:
        if not paths:
            print(f"  (no sample): {label}")
            return
        chosen = paths if args.all else paths[:1]
        for p in chosen:
            targets.append((label, rois, colors, p))

    # 各画面の抽出 ROI
    add("プレイ画面 PLAY_ROI", PLAY_ROI, COLORS_PLAY, cat_play)
    add("リザルト画面 RESULT_ROI", RESULT_ROI, COLORS_RESULT, cat_result)
    add("選曲画面 SELECT_ROI", SELECT_ROI, COLORS_SELECT, cat_select)
    add("オプション画面 OPTION_ROI", OPTION_ROI, COLORS_OPTION, cat_option)
    add("準備画面 PREPARE_ROI", PREPARE_ROI, COLORS_PREPARE, cat_prepare)
    add("プレイ画面前ロード PRELOAD_ROI", PRELOAD_ROI, COLORS_PRELOAD, cat_preload)

    # 画面判別領域（粗い領域・旧 OCR 用）
    add("選曲画面 + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_select)
    add("オプション画面 + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_option)
    add("準備画面 + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_prepare)
    add("プレイ画面前ロード + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_preload)
    add("プレイ画面 + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_play)
    add("リザルト画面 + SCREEN_DETECT_REGIONS", SCREEN_DETECT_REGIONS, COLORS_DETECT, cat_result)

    # 右下シグネチャ（新方式）の検証用オーバーレイ
    add("選曲画面 + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_select)
    add("オプション画面 + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_option)
    add("準備画面 + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_prepare)
    add("プレイ画面 + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_play)
    add("リザルト画面 + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_result)
    add("準備画面前ロード + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, sorted((args.sample_root / "準備画面前ロード画面").glob("*.png")))
    add("プレイ画面前ロード + SCREEN_SIGNATURE", SCREEN_SIGNATURE_REGIONS, COLORS_SIGNATURE, cat_preload)

    written: list[Path] = []
    for i, (label, rois, colors, path) in enumerate(targets):
        img = _imread_unicode(path)
        if img is None:
            continue
        norm = normalize_frame(img)
        out = render_with_legend(norm.image_bgr, rois, colors, f"{label} - {path.name}")
        safe = label.replace(" ", "_").replace("+", "and").replace("/", "-")
        out_path = args.out_dir / f"{i:02d}_{safe}_{path.stem}.png"
        if _imwrite_unicode(out_path, out):
            written.append(out_path)
            print(f"wrote {out_path}")

    if written:
        index_md = args.out_dir / "README.md"
        lines = [
            "# ROI 視覚化結果",
            "",
            "`scripts/visualize_roi.py` で生成。"
            "サンプル画像を 1366x768 に正規化したうえで、`roi_defs.py` の ROI を矩形描画したもの。",
            "",
            "## 一覧",
            "",
        ]
        for p in written:
            lines.append(f"- `{p.name}`")
        index_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {index_md}")

    print(f"done. {len(written)} overlays written to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
