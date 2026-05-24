"""画面判別のための右下シグネチャと OPTION/RESULT 分離判定を検証。

シグネチャ ROI: 右下 (1286, 672)-(1347, 754)、61x82px
OPTION/RESULT 分離:
  - リザルト: テンキー最上段中央 "8" (1309, 674)-(1324, 689) が点灯
  - オプション: テンキー最下段左 "0" (1288, 736)-(1303, 751) が点灯

サンプル全件についてシグネチャと点灯判定を計算し、識別可能か確認する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.recognizer.normalize import crop, normalize_frame  # noqa: E402

SAMPLE_ROOT = Path("tests/fixtures/sample")

BR_SIG = (1286, 672, 1347, 754)
DOT8 = (1309, 674, 1324, 689)   # リザルトで点灯する "8"
DOT0 = (1288, 736, 1303, 751)   # オプションで点灯する "0"

CATEGORY_EXPECTED = {
    "選曲画面": "SELECT",
    "準備画面前ロード画面": "LOAD_TO_READY",
    "準備画面": "READY",
    "オプション画面": "OPTION",
    "プレイ画面前ロード画面": "LOAD_TO_PLAY",
    "プレイ画面": "PLAY",
    "リザルト画面": "RESULT",
}


def _imread_unicode(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def hsv_mean(roi_bgr: np.ndarray) -> tuple[float, float, float]:
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    return (
        float(hsv[..., 0].mean()),
        float(hsv[..., 1].mean()),
        float(hsv[..., 2].mean()),
    )


def main() -> int:
    rows: list[dict] = []
    for cat, _ in CATEGORY_EXPECTED.items():
        cat_dir = SAMPLE_ROOT / cat
        if not cat_dir.exists():
            continue
        for img_path in sorted(cat_dir.glob("*.png")):
            img = _imread_unicode(img_path)
            if img is None:
                continue
            norm = normalize_frame(img)
            sig = crop(norm.image_bgr, BR_SIG)
            d8 = crop(norm.image_bgr, DOT8)
            d0 = crop(norm.image_bgr, DOT0)
            rows.append({
                "category": cat,
                "expected": CATEGORY_EXPECTED[cat],
                "file": img_path.name,
                "sig_hsv": hsv_mean(sig),
                "dot8_v": hsv_mean(d8)[2],
                "dot0_v": hsv_mean(d0)[2],
                "dot8_s": hsv_mean(d8)[1],
                "dot0_s": hsv_mean(d0)[1],
            })

    if not rows:
        print("no samples found")
        return 1

    print(f"{'category':<26} {'file':<55} "
          f"{'sig HSV':<22}  {'dot8(V,S)':<15} {'dot0(V,S)':<15}")
    print("-" * 140)
    for r in rows:
        h, s, v = r["sig_hsv"]
        print(
            f"{r['category']:<26} {r['file']:<55} "
            f"H={h:>5.1f} S={s:>5.1f} V={v:>5.1f}    "
            f"V={r['dot8_v']:>5.1f}/S={r['dot8_s']:>5.1f}    "
            f"V={r['dot0_v']:>5.1f}/S={r['dot0_s']:>5.1f}"
        )

    print('\n=== OPTION vs RESULT 比較（"8"/"0" 点灯判定） ===')
    print(f"{'category':<26} {'file':<55} {'dot8_V > dot0_V?':<18}")
    for r in rows:
        if r["expected"] not in ("OPTION", "RESULT"):
            continue
        cmp = "True (→ RESULT)" if r["dot8_v"] > r["dot0_v"] else "False (→ OPTION)"
        print(f"{r['category']:<26} {r['file']:<55} {cmp:<18}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
