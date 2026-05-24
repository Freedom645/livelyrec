"""
LivelyRec OCR PoC #02 - 領域限定OCR
画像サイズ 1366x768 を基準に、プレイ画面・リザルト画面の主要ROIを切り出し、
PaddleOCR を当てて速度・精度を測定する。

PoC #01 (`run_paddleocr.py`) の全画像OCRに対し、ROI クロップで処理時間が
基本設計の合格基準 (≤200ms/枚) に届くかを評価することが主目的。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml
from PIL import Image
from paddleocr import PaddleOCR
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "docs" / "sample"
RESULTS_DIR = ROOT / "poc" / "results"
ROI_DIR = RESULTS_DIR / "roi_crops"
GROUND_TRUTH = ROOT / "poc" / "ground_truth.yaml"

BASE_W, BASE_H = 1366, 768


# (左, 上, 右, 下) を 1366x768 座標系で定義
ROI_PLAY: dict[str, tuple[int, int, int, int]] = {
    "song_name": (350, 0, 980, 65),     # 上部黒帯の楽曲名
    "score":     (110, 590, 410, 665),  # 左下スコア
}

ROI_RESULT: dict[str, tuple[int, int, int, int]] = {
    "score":      (680, 415, 880, 470),
    "cool":       (740, 472, 880, 510),
    "great":      (740, 500, 880, 538),
    "good":       (740, 528, 880, 565),
    "bad":        (740, 558, 880, 595),
    "combo":      (740, 600, 880, 640),
    "best_score": (740, 640, 880, 680),
    "best_diff":  (740, 670, 880, 705),
}


@dataclass
class RoiResult:
    name: str
    elapsed_sec: float
    text: str
    confidence: float | None
    items: list[dict]


def crop(img: Image.Image, roi: tuple[int, int, int, int]) -> Image.Image:
    # 入力解像度が異なる場合に備えて座標を比率スケールする
    w, h = img.size
    sx = w / BASE_W
    sy = h / BASE_H
    box = (
        int(roi[0] * sx),
        int(roi[1] * sy),
        int(roi[2] * sx),
        int(roi[3] * sy),
    )
    return img.crop(box)


def ocr_image(ocr: PaddleOCR, pil_img: Image.Image) -> list[dict]:
    import numpy as np
    arr = np.array(pil_img.convert("RGB"))[:, :, ::-1]  # PaddleOCR expects BGR
    raw = ocr.ocr(arr, cls=False)
    items: list[dict] = []
    if not raw or not raw[0]:
        return items
    for line in raw[0]:
        try:
            box = line[0]
            text, score = line[1]
            items.append({
                "text": text,
                "score": float(score),
                "poly": [[float(p[0]), float(p[1])] for p in box],
            })
        except Exception:
            items.append({"text": str(line), "score": None, "poly": None})
    return items


def join_text(items: list[dict]) -> tuple[str, float | None]:
    """ROI内のテキストを連結。複数行ある場合はスコア重み付け平均。"""
    if not items:
        return "", None
    # 信頼度の高いものから連結
    sorted_items = sorted(items, key=lambda x: x.get("score") or 0.0, reverse=True)
    text = "".join(it["text"] for it in sorted_items)
    scores = [it["score"] for it in items if it.get("score") is not None]
    conf = sum(scores) / len(scores) if scores else None
    return text, conf


_ZENKAKU_DIGITS = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "Ｓ": "5",  # 全角S を 5 と読む誤読の補正
    "ｓ": "5",
    "Ｏ": "0",
    "ｏ": "0",
    "Ｂ": "8",  # 装飾Bを8と誤認するパターン
})


def digits_only(text: str) -> str:
    """全角数字や類似誤認識を補正してから数字のみ抽出。"""
    normalized = text.translate(_ZENKAKU_DIGITS)
    return "".join(c for c in normalized if c.isdigit())


def load_ground_truth() -> dict:
    with GROUND_TRUTH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ROI_DIR.mkdir(parents=True, exist_ok=True)

    print("[poc] Initializing PaddleOCR (lang='japan')...", flush=True)
    init_start = time.perf_counter()
    ocr = PaddleOCR(lang="japan", use_angle_cls=False, show_log=False)
    init_elapsed = time.perf_counter() - init_start
    print(f"[poc] Initialized in {init_elapsed:.2f}s", flush=True)

    gt = load_ground_truth()
    play_gt = {e["file"]: e for e in (gt.get("play_screen") or [])}
    result_gt = {e["file"]: e for e in (gt.get("result_screen") or [])}

    # Master fuzzy matching dictionary (PoC scope: 既知の2楽曲)
    master_songs = [
        "ぽぽぽかレトロード",
        "漆黒のスペシャルプリンセスサンデー",
    ]
    fuzzy_threshold = 65

    per_image: list[dict] = []

    # ---- Play screen evaluation ----
    play_dir = SAMPLE_DIR / "プレイ画面"
    for path in sorted(play_dir.glob("*.png")):
        fname = path.name
        gt_entry = play_gt.get(fname, {})
        expected_song = gt_entry.get("song_name")
        sub_state = gt_entry.get("sub_state")

        img = Image.open(path)
        per_roi: dict[str, dict] = {}
        total_elapsed = 0.0

        for roi_name, roi in ROI_PLAY.items():
            crop_img = crop(img, roi)
            # クロップ画像を保存（人間レビュー用）
            crop_path = ROI_DIR / f"play_{fname}_{roi_name}.png"
            try:
                crop_img.save(crop_path)
            except Exception:
                pass

            t0 = time.perf_counter()
            items = ocr_image(ocr, crop_img)
            elapsed = time.perf_counter() - t0
            total_elapsed += elapsed
            text, conf = join_text(items)
            per_roi[roi_name] = {
                "elapsed_sec": round(elapsed, 4),
                "text_raw": text,
                "confidence": conf,
                "n_items": len(items),
            }

        # 楽曲特定（ROI=song_name の結果をマスタファジーマッチ）
        ocr_song = per_roi.get("song_name", {}).get("text_raw", "")
        match_song = None
        match_score = None
        if ocr_song:
            res = process.extractOne(ocr_song, master_songs, scorer=fuzz.WRatio)
            if res:
                match_song, match_score, _ = res
        identified = (
            match_song
            if (match_score is not None and match_score >= fuzzy_threshold)
            else None
        )
        song_correct = (expected_song is not None and identified == expected_song)

        # スコア（数字のみ抽出）
        ocr_score_raw = per_roi.get("score", {}).get("text_raw", "")
        score_digits = digits_only(ocr_score_raw)

        per_image.append({
            "screen": "play",
            "file": fname,
            "sub_state": sub_state,
            "total_elapsed_sec": round(total_elapsed, 4),
            "per_roi": per_roi,
            "song": {
                "expected": expected_song,
                "ocr_raw": ocr_song,
                "matched": match_song,
                "match_score": match_score,
                "identified": identified,
                "correct": song_correct,
            },
            "score_text": ocr_score_raw,
            "score_digits": score_digits,
        })
        flag = "OK" if song_correct else (
            f"ID:{identified or '未特定'}/EXP:{expected_song}"
        )
        print(
            f"[poc] play/{fname}: total={total_elapsed*1000:5.0f}ms "
            f"song={flag} score='{score_digits}'",
            flush=True,
        )

    # ---- Result screen evaluation ----
    result_dir = SAMPLE_DIR / "リザルト画面"
    for path in sorted(result_dir.glob("*.png")):
        fname = path.name
        gt_entry = result_gt.get(fname, {})

        img = Image.open(path)
        per_roi: dict[str, dict] = {}
        total_elapsed = 0.0

        for roi_name, roi in ROI_RESULT.items():
            crop_img = crop(img, roi)
            crop_path = ROI_DIR / f"result_{fname}_{roi_name}.png"
            try:
                crop_img.save(crop_path)
            except Exception:
                pass

            t0 = time.perf_counter()
            items = ocr_image(ocr, crop_img)
            elapsed = time.perf_counter() - t0
            total_elapsed += elapsed
            text, conf = join_text(items)
            per_roi[roi_name] = {
                "elapsed_sec": round(elapsed, 4),
                "text_raw": text,
                "confidence": conf,
                "n_items": len(items),
                "digits": digits_only(text),
            }

        per_image.append({
            "screen": "result",
            "file": fname,
            "clear_type_gt": gt_entry.get("clear_type"),
            "total_elapsed_sec": round(total_elapsed, 4),
            "per_roi": per_roi,
        })
        score = per_roi.get("score", {}).get("digits", "")
        cool = per_roi.get("cool", {}).get("digits", "")
        great = per_roi.get("great", {}).get("digits", "")
        good = per_roi.get("good", {}).get("digits", "")
        bad = per_roi.get("bad", {}).get("digits", "")
        combo = per_roi.get("combo", {}).get("digits", "")
        print(
            f"[poc] result/{fname}: total={total_elapsed*1000:5.0f}ms "
            f"S={score} CL={cool} GR={great} GD={good} BD={bad} CB={combo}",
            flush=True,
        )

    # ---- 集計 ----
    play_records = [r for r in per_image if r["screen"] == "play"]
    result_records = [r for r in per_image if r["screen"] == "result"]

    play_elapsed = [r["total_elapsed_sec"] for r in play_records]
    result_elapsed = [r["total_elapsed_sec"] for r in result_records]

    # 楽曲名特定精度
    play_song_eval = [r for r in play_records if r["song"]["expected"] is not None]
    n_play_song_total = len(play_song_eval)
    n_play_song_correct = sum(1 for r in play_song_eval if r["song"]["correct"])
    accuracy = (
        n_play_song_correct / n_play_song_total if n_play_song_total else None
    )

    summary = {
        "engine": "PaddleOCR",
        "version": "2.7.3",
        "mode": "ROI cropped",
        "init_elapsed_sec": round(init_elapsed, 3),
        "play": {
            "n": len(play_records),
            "avg_total_elapsed_sec": (
                round(sum(play_elapsed) / len(play_elapsed), 4) if play_elapsed else None
            ),
            "min_total_elapsed_sec": round(min(play_elapsed), 4) if play_elapsed else None,
            "max_total_elapsed_sec": round(max(play_elapsed), 4) if play_elapsed else None,
            "song_id_accuracy": accuracy,
            "song_id_correct": n_play_song_correct,
            "song_id_total": n_play_song_total,
        },
        "result": {
            "n": len(result_records),
            "avg_total_elapsed_sec": (
                round(sum(result_elapsed) / len(result_elapsed), 4) if result_elapsed else None
            ),
            "min_total_elapsed_sec": round(min(result_elapsed), 4) if result_elapsed else None,
            "max_total_elapsed_sec": round(max(result_elapsed), 4) if result_elapsed else None,
        },
        "per_image": per_image,
    }

    out_path = RESULTS_DIR / "summary_roi.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[poc] Wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
