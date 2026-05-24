"""
LivelyRec OCR Engine Selection PoC - PaddleOCR (2.7.x)
docs/sample/ 配下の全画像に対して PaddleOCR を実行し、
認識結果と処理時間を results/ に書き出す。

Usage:
    python poc/run_paddleocr.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml
from paddleocr import PaddleOCR
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "docs" / "sample"
RESULTS_DIR = ROOT / "poc" / "results"
RAW_DIR = RESULTS_DIR / "raw"
GROUND_TRUTH = ROOT / "poc" / "ground_truth.yaml"


def serialize_result(raw_result) -> list[dict]:
    """PaddleOCR 2.7 の ocr() 戻り値（list[list[[box, (text, score)]]] or [None]）を変換。"""
    items: list[dict] = []
    if not raw_result:
        return items
    # raw_result は ページ単位の list。今回は単一画像なので [0] を使用。
    page = raw_result[0]
    if not page:
        return items
    for line in page:
        try:
            box = line[0]
            text, score = line[1]
            poly = [[float(p[0]), float(p[1])] for p in box]
            items.append({"text": text, "score": float(score), "poly": poly})
        except Exception:
            items.append({"text": str(line), "score": None, "poly": None})
    return items


def load_ground_truth() -> dict:
    with GROUND_TRUTH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_image_files() -> list[Path]:
    return sorted(SAMPLE_DIR.glob("*/*.png"))


def screen_kind_of(path: Path) -> str:
    return path.parent.name


def evaluate_song_name(items: list[dict], expected: str | None) -> dict:
    if not expected:
        return {"expected": None, "best_match": None, "exact": None, "fuzzy": None}
    best_text = ""
    best_ratio = 0.0
    for it in items:
        ratio = fuzz.partial_ratio(expected, it["text"])
        if ratio > best_ratio:
            best_ratio = ratio
            best_text = it["text"]
    exact = any(expected == it["text"] for it in items)
    return {
        "expected": expected,
        "best_match": best_text,
        "exact": exact,
        "fuzzy": best_ratio,
    }


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("[poc] Initializing PaddleOCR (lang='japan')...", flush=True)
    init_start = time.perf_counter()
    ocr = PaddleOCR(lang="japan", use_angle_cls=False, show_log=False)
    init_elapsed = time.perf_counter() - init_start
    print(f"[poc] Initialized in {init_elapsed:.2f}s", flush=True)

    gt = load_ground_truth()
    expected_map: dict[tuple[str, str], dict] = {}
    for entry in gt.get("play_screen", []) or []:
        expected_map[("プレイ画面", entry["file"])] = entry
    for entry in gt.get("result_screen", []) or []:
        expected_map[("リザルト画面", entry["file"])] = entry

    images = find_image_files()
    print(f"[poc] Found {len(images)} sample images", flush=True)

    per_image_results: list[dict] = []

    for path in images:
        rel = path.relative_to(SAMPLE_DIR)
        kind = screen_kind_of(path)
        fname = path.name
        print(f"[poc] OCR: {kind}/{fname} ...", flush=True)

        start = time.perf_counter()
        try:
            raw = ocr.ocr(str(path), cls=False)
        except Exception as e:
            elapsed = time.perf_counter() - start
            print(f"[poc]   ERROR: {e}", flush=True)
            per_image_results.append({
                "file": str(rel),
                "screen": kind,
                "elapsed_sec": elapsed,
                "error": str(e),
                "items": [],
                "n_items": 0,
                "song_eval": {"expected": None, "best_match": None, "exact": None, "fuzzy": None},
            })
            continue
        elapsed = time.perf_counter() - start

        items = serialize_result(raw)

        entry = expected_map.get((kind, fname), {})
        expected_song = entry.get("song_name") if entry else None
        song_eval = evaluate_song_name(items, expected_song)

        record = {
            "file": str(rel),
            "screen": kind,
            "elapsed_sec": round(elapsed, 3),
            "n_items": len(items),
            "song_eval": song_eval,
            "items": items,
        }
        per_image_results.append(record)

        out_name = str(rel).replace("\\", "/").replace("/", "__")
        (RAW_DIR / f"{out_name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        flag = "OK" if song_eval["exact"] else (
            f"fuzzy={song_eval['fuzzy']:.0f}" if song_eval["fuzzy"] is not None else "-"
        )
        print(
            f"[poc]   {elapsed*1000:6.0f}ms, items={len(items):3d}, "
            f"song={flag}, expected='{expected_song or ''}', "
            f"best='{song_eval['best_match'] or ''}'",
            flush=True,
        )

    elapsed_all = [r["elapsed_sec"] for r in per_image_results if "elapsed_sec" in r and "error" not in r]
    by_screen: dict[str, dict] = {}
    for r in per_image_results:
        s = by_screen.setdefault(r["screen"], {
            "n": 0, "n_eval_target": 0,
            "song_exact": 0, "song_fuzzy_ge_90": 0,
            "elapsed_sec_sum": 0.0, "errors": 0,
        })
        s["n"] += 1
        if "error" in r:
            s["errors"] += 1
        ev = r.get("song_eval") or {}
        if ev.get("expected") is not None:
            s["n_eval_target"] += 1
            if ev.get("exact"):
                s["song_exact"] += 1
            if ev.get("fuzzy") is not None and ev["fuzzy"] >= 90:
                s["song_fuzzy_ge_90"] += 1
        s["elapsed_sec_sum"] += r.get("elapsed_sec", 0.0)

    summary = {
        "engine": "PaddleOCR",
        "version": "2.7.3",
        "paddlepaddle": "2.6.2",
        "lang": "japan",
        "init_elapsed_sec": round(init_elapsed, 3),
        "n_images": len(per_image_results),
        "n_errors": sum(1 for r in per_image_results if "error" in r),
        "total_elapsed_sec": round(sum(elapsed_all), 3) if elapsed_all else 0,
        "avg_elapsed_sec": round(sum(elapsed_all) / len(elapsed_all), 3) if elapsed_all else None,
        "max_elapsed_sec": round(max(elapsed_all), 3) if elapsed_all else None,
        "min_elapsed_sec": round(min(elapsed_all), 3) if elapsed_all else None,
        "by_screen": by_screen,
        "per_image": [
            {k: v for k, v in r.items() if k != "items"} for r in per_image_results
        ],
    }

    (RESULTS_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[poc] Wrote summary to {RESULTS_DIR / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
