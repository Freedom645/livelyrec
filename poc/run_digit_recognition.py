"""
LivelyRec PoC #03 - 判定数（色付き太字数字）の認識方式比較

リザルト画面の COOL/GREAT/GOOD/BAD 数字を題材に、
方式 A: 色マスク前処理 + PaddleOCR
方式 B: テンプレートマッチング（サンプルから数字を切り出してテンプレ化）
を比較する。

数字テンプレートはまずサンプルから自動切り出しを試み、目視確認用に保存する。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import cv2
from PIL import Image
from paddleocr import PaddleOCR

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "docs" / "sample"
RESULTS_DIR = ROOT / "poc" / "results"
DIGIT_DIR = RESULTS_DIR / "digit_recognition"
TEMPLATE_DIR = ROOT / "poc" / "templates"

BASE_W, BASE_H = 1366, 768

# リザルト画面の判定数 ROI と HSV 色相
# 色相: COOL=赤紫(マゼンタ290-330), GREAT=黄(40-70), GOOD=赤(0-15/350-360), BAD=水色(170-200)
JUDGE_ROIS: dict[str, tuple[tuple[int, int, int, int], tuple[int, int]]] = {
    # name: (ROI, HSV range tuple of (h_lo, h_hi))
    "cool":  ((740, 472, 880, 510), (140, 165)),  # マゼンタ（OpenCV HSV: 0-180）
    "great": ((740, 500, 880, 538), (20, 35)),    # 黄
    "good":  ((740, 528, 880, 565), (0, 10)),     # 赤
    "bad":   ((740, 558, 880, 595), (85, 105)),   # 水色（シアン）
}

# Ground Truth: PoC #01 の raw OCR 結果のうち信頼度 ≥0.95 の値、または
# 前処理後画像レビューで確実に読み取れる値のみ採用。それ以外は None。
# PoC#03の目的は「前処理で改善するか」の傾向確認なので、Ground Truth は確実なものだけで評価する。
GROUND_TRUTH: dict[str, dict[str, str | None]] = {
    "Screenshot 2026-05-18 12-20-06.png": {
        "cool": None,        # PoC#01で読めず（要レビュー）
        "great": "218",      # PoC#01 confidence 0.99
        "good": None,        # 不確定（「6Ｔ」など）
        "bad": "100",        # PoC#01 confidence 1.00
    },
    "Screenshot 2026-05-18 12-22-44.png": {
        "cool": None,
        "great": None,       # 「24Ｕ」→ 246 と推定だが確実でない
        "good": None,
        "bad": None,
    },
    "Screenshot 2026-05-18 12-23-54.png": {  # 部分ロード
        "cool": None, "great": None, "good": None, "bad": None,
    },
    "Screenshot 2026-05-18 12-27-48.png": {  # 通信中
        "cool": None, "great": None, "good": None, "bad": None,
    },
    "Screenshot 2026-05-18 12-27-52.png": {  # CLEAR エフェクト被り
        "cool": None, "great": None, "good": None, "bad": None,
    },
    "Screenshot 2026-05-18 12-28-30.png": {  # 部分ロード
        "cool": None, "great": None, "good": None, "bad": None,
    },
}


def crop(img_np: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    h, w = img_np.shape[:2]
    sx, sy = w / BASE_W, h / BASE_H
    x1, y1, x2, y2 = roi
    return img_np[int(y1 * sy):int(y2 * sy), int(x1 * sx):int(x2 * sx)]


def preprocess_for_ocr(bgr: np.ndarray, h_lo: int, h_hi: int) -> np.ndarray:
    """色相マスクで該当色のみ抽出 → グレースケール化 → 拡大 → コントラスト強調。"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # 色相がラップする赤系の場合は両端マスク
    if h_lo <= h_hi:
        mask = cv2.inRange(hsv, (h_lo, 80, 80), (h_hi, 255, 255))
    else:
        m1 = cv2.inRange(hsv, (0, 80, 80), (h_hi, 255, 255))
        m2 = cv2.inRange(hsv, (h_lo, 80, 80), (180, 255, 255))
        mask = cv2.bitwise_or(m1, m2)
    # マスク領域だけ白、それ以外黒
    out = np.zeros_like(mask)
    out[mask > 0] = 255
    # 3倍拡大
    out = cv2.resize(out, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    # 軽くガウシアンぼかしでアンチエイリアス
    out = cv2.GaussianBlur(out, (3, 3), 0)
    # 二値化（既に二値化されているが念のため）
    _, out = cv2.threshold(out, 127, 255, cv2.THRESH_BINARY)
    # 黒背景・白文字 → OCR には黒文字・白背景の方が良いケースが多い。反転して提供。
    out = 255 - out
    return out


def ocr_image(ocr: PaddleOCR, img_gray: np.ndarray) -> str:
    """グレースケール画像を3チャンネル化してPaddleOCRに渡し、認識文字列を返す。"""
    if img_gray.ndim == 2:
        img3 = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)
    else:
        img3 = img_gray
    raw = ocr.ocr(img3, cls=False)
    if not raw or not raw[0]:
        return ""
    texts = []
    for line in raw[0]:
        try:
            texts.append(line[1][0])
        except Exception:
            pass
    return "".join(texts)


_DIGIT_TRANS = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "Ｓ": "5", "ｓ": "5", "Ｏ": "0", "ｏ": "0", "Ｂ": "8",
    "O": "0", "I": "1", "l": "1", "B": "8", "S": "5",
})


def digits_only(text: str) -> str:
    return "".join(c for c in text.translate(_DIGIT_TRANS) if c.isdigit())


# ---------- Template matching prototype ----------

def build_templates_from_truth(ocr: PaddleOCR) -> dict[str, dict[str, np.ndarray]]:
    """
    自動テンプレ生成は本PoCでは非対象（手作業で切り出すのが本筋）。
    本関数はプレースホルダのみ。
    """
    return {}


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DIGIT_DIR.mkdir(parents=True, exist_ok=True)

    print("[poc] Initializing PaddleOCR (lang='japan')...", flush=True)
    ocr = PaddleOCR(lang="japan", use_angle_cls=False, show_log=False)
    # ウォームアップ（初回オーバーヘッド除外）
    dummy = np.full((40, 80, 3), 255, dtype=np.uint8)
    cv2.putText(dummy, "1", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    _ = ocr.ocr(dummy, cls=False)

    result_dir = SAMPLE_DIR / "リザルト画面"
    rows: list[dict] = []

    for path in sorted(result_dir.glob("*.png")):
        fname = path.name
        gt = GROUND_TRUTH.get(fname, {})
        img_pil = Image.open(path)
        img_np = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        for judge, (roi, hsv) in JUDGE_ROIS.items():
            crop_bgr = crop(img_np, roi)
            preprocessed = preprocess_for_ocr(crop_bgr, hsv[0], hsv[1])

            # 保存（人間レビュー用）
            cv2.imwrite(str(DIGIT_DIR / f"{fname}_{judge}_raw.png"), crop_bgr)
            cv2.imwrite(str(DIGIT_DIR / f"{fname}_{judge}_pre.png"), preprocessed)

            t0 = time.perf_counter()
            ocr_raw = ocr_image(ocr, preprocessed)
            elapsed = time.perf_counter() - t0
            ocr_digits = digits_only(ocr_raw)

            expected = gt.get(judge)
            correct = (expected is not None and ocr_digits == expected)
            comparable = expected is not None

            rows.append({
                "file": fname,
                "judge": judge,
                "expected": expected,
                "ocr_raw": ocr_raw,
                "ocr_digits": ocr_digits,
                "elapsed_sec": round(elapsed, 4),
                "correct": correct,
                "comparable": comparable,
            })
            mark = "OK" if correct else ("--" if not comparable else "NG")
            print(
                f"[poc] {fname[-30:]:30s} {judge:5s} "
                f"GT={expected!s:5s} OCR={ocr_digits!s:8s} {mark} "
                f"raw='{ocr_raw}' {elapsed*1000:.0f}ms",
                flush=True,
            )

    # 集計
    eval_rows = [r for r in rows if r["comparable"]]
    n_total = len(eval_rows)
    n_correct = sum(1 for r in eval_rows if r["correct"])
    accuracy = n_correct / n_total if n_total else None

    avg_elapsed = sum(r["elapsed_sec"] for r in rows) / len(rows) if rows else None

    summary = {
        "approach": "color_mask_preprocessing + PaddleOCR",
        "n_judgments_total": len(rows),
        "n_evaluable": n_total,
        "n_correct": n_correct,
        "accuracy": accuracy,
        "avg_elapsed_per_judge_sec": avg_elapsed,
        "rows": rows,
    }
    (RESULTS_DIR / "summary_digit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[poc] accuracy={accuracy} ({n_correct}/{n_total}) avg={avg_elapsed*1000 if avg_elapsed else None:.0f}ms", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
