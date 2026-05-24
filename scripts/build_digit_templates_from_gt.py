"""ground-truth CSV のリザルト正解値から digit テンプレートを再生成する。

詳細: docs/design/15_システムテスト計画書.md §8

`tests/fixtures/sample/_ground_truth.csv` の result 行について、score/combo/判定数の各 ROI から
数字を切り出し、正解値で各桁を特定して平均テンプレートを作る。

スコアと combo/判定数はグラデーション・表示色が異なり二値化後の字形に差が出るため、
**2系統のテンプレート集合**を生成する（工程8 #1）:
  - スコア用      : score フィールド   -> templates/digits/1366x768/score/0..9.png
  - combo/判定数用: combo/判定数        -> templates/digits/1366x768/0..9.png

使い方:
    .venv/Scripts/python.exe -m scripts.build_digit_templates_from_gt
"""

from __future__ import annotations

import csv
import shutil
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from livelyrec.infrastructure.ocr.digit_template import (
    JUDGE_COLOR,
    DigitTemplateRecognizer,
)
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI

GT = Path("tests/fixtures/sample/_ground_truth.csv")
TPL_DIR = Path("templates/digits/1366x768")
SCORE_DIR = TPL_DIR / "score"
TPL_W, TPL_H = 18, 23
# スコアは橙の濃いコア部のみ残るため、しきい値を高めにして細く保つ。
_SCORE_THRESHOLD = 130
_OTHER_THRESHOLD = 110
# CSV 列 -> 色キー
_SCORE_FIELDS = [("score", "score")]
_OTHER_FIELDS = [
    ("combo", "combo"),
    ("cool", "cool"),
    ("great", "great"),
    ("good", "good"),
    ("bad", "bad"),
]


def _imread_u(path: Path) -> np.ndarray | None:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def _collect(rows: list[dict], fields: list[tuple[str, str]]) -> dict[int, list]:
    """各 result 行の指定フィールドから、桁ごとの二値パッチを収集する。"""
    samples: dict[int, list[np.ndarray]] = defaultdict(list)
    for row in rows:
        img = _imread_u(Path(row["path"]))
        if img is None:
            continue
        for field, color_key in fields:
            val = (row.get(field) or "").strip()
            if not val:
                continue
            x1, y1, x2, y2 = RESULT_ROI[field]
            mask = DigitTemplateRecognizer._color_mask(
                img[y1:y2, x1:x2], JUDGE_COLOR[color_key]
            )
            boxes = sorted(
                DigitTemplateRecognizer._extract_digit_boxes(mask),
                key=lambda b: b[0],
            )
            if len(boxes) != len(val):
                print(
                    f"  skip {Path(row['path']).name} {field}={val}: "
                    f"{len(boxes)}箱 != {len(val)}桁"
                )
                continue
            for (bx, by, bw, bh), ch in zip(boxes, val, strict=True):
                samples[int(ch)].append(mask[by:by + bh, bx:bx + bw])
    return samples


def _build(samples: dict[int, list], out_dir: Path, threshold: int, label: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{label}] -> {out_dir}")
    for d in range(10):
        patches = samples.get(d, [])
        if not patches:
            print(f"  digit {d}: サンプル無し → 既存維持")
            continue
        resized = [
            cv2.resize(p, (TPL_W, TPL_H), interpolation=cv2.INTER_AREA)
            for p in patches
        ]
        avg = np.mean(resized, axis=0)
        _, tpl = cv2.threshold(avg.astype(np.uint8), threshold, 255, cv2.THRESH_BINARY)
        cv2.imencode(".png", tpl)[1].tofile(str(out_dir / f"{d}.png"))
        print(f"  digit {d}: {len(patches)} サンプルから生成")
    cells = []
    for d in range(10):
        p = out_dir / f"{d}.png"
        if not p.exists():
            continue
        t = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        cells.append(cv2.resize(t, (TPL_W * 5, TPL_H * 5), interpolation=cv2.INTER_NEAREST))
    if cells:
        cv2.imencode(".png", np.hstack(cells))[1].tofile(
            str(out_dir / "_templates_preview.png")
        )


def main() -> None:
    with GT.open(encoding="utf-8-sig") as fp:
        rows = [r for r in csv.DictReader(fp) if r.get("screen") == "result"]
    print(f"result 行: {len(rows)}")

    backup = TPL_DIR.parent / "_backup_before_gt_rebuild"
    backup.mkdir(parents=True, exist_ok=True)
    for d in range(10):
        src = TPL_DIR / f"{d}.png"
        if src.exists():
            shutil.copy2(src, backup / f"{d}.png")
    print(f"既存テンプレを {backup} へバックアップ")

    _build(_collect(rows, _SCORE_FIELDS), SCORE_DIR, _SCORE_THRESHOLD, "スコア用")
    _build(_collect(rows, _OTHER_FIELDS), TPL_DIR, _OTHER_THRESHOLD, "combo/判定数用")


if __name__ == "__main__":
    main()
