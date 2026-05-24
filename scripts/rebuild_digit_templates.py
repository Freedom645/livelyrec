"""判定数テンプレ画像を新 ROI で再生成するスクリプト（ワンショット）。

過去ラベル付け済みの templates/digits/1366x768/{0..9}/ ディレクトリの
ファイル名から ground truth（サンプル × 判定 × 左→右順 → 数字）を読み取り、
新 ROI で再抽出した候補に同じラベルを機械的に当てはめてテンプレを再生成する。

Usage:
    python scripts/rebuild_digit_templates.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.ocr.digit_template import JUDGE_COLOR, ColorRange  # noqa: E402
from livelyrec.infrastructure.recognizer.normalize import crop, normalize_frame  # noqa: E402
from livelyrec.infrastructure.recognizer.roi_defs import RESULT_ROI  # noqa: E402

TEMPLATE_DIR = Path("templates/digits/1366x768")
SAMPLE_DIR = Path("tests/fixtures/sample/リザルト画面")

CANDIDATE_NAME_RE = re.compile(r"^(?P<stem>.+)_(?P<judge>cool|great|good|bad)_(?P<idx>\d+)\.png$")


def _imread_unicode(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as im:
            return cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _imwrite_unicode(path: Path, img: np.ndarray) -> bool:
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
        if h < max(12, int(h_full * 0.25)) or area < 30:
            continue
        if w / max(h, 1) > 2.0 or h / max(w, 1) > 6.0:
            continue
        candidates.append((x, y, w, h))
    return sorted(candidates, key=lambda b: b[0])


def collect_ground_truth() -> dict[tuple[str, str, int], int]:
    """既存の {0..9}/ フォルダのファイル名から (stem, judge, idx) -> digit を作成。"""
    gt: dict[tuple[str, str, int], int] = {}
    for d in range(10):
        folder = TEMPLATE_DIR / str(d)
        if not folder.is_dir():
            continue
        for f in folder.glob("*.png"):
            m = CANDIDATE_NAME_RE.match(f.name)
            if not m:
                continue
            key = (m.group("stem"), m.group("judge"), int(m.group("idx")))
            gt[key] = d
    return gt


def main() -> int:
    gt = collect_ground_truth()
    if not gt:
        print("ground truth が見つかりません。templates/digits/1366x768/{0..9}/ にファイルが必要。")
        return 1
    print(f"ground truth: {len(gt)} 件")

    # 既存の数字フォルダと _candidates を退避してクリーンに作り直す
    backup = TEMPLATE_DIR.parent / "_backup_before_rebuild"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    for d in range(10):
        folder = TEMPLATE_DIR / str(d)
        if folder.exists():
            shutil.move(str(folder), str(backup / str(d)))
    cand_dir = TEMPLATE_DIR / "_candidates"
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir(parents=True, exist_ok=True)
    for d in range(10):
        (TEMPLATE_DIR / str(d)).mkdir(parents=True, exist_ok=True)

    # 各サンプルから新 ROI で抽出し、ground truth に従い振り分け
    assigned = 0
    skipped_gt_missing: list[str] = []
    extra_candidates: list[str] = []
    for img_path in sorted(SAMPLE_DIR.glob("*.png")):
        img = _imread_unicode(img_path)
        if img is None:
            continue
        norm = normalize_frame(img)
        for judge in ("cool", "great", "good", "bad"):
            roi = crop(norm.image_bgr, RESULT_ROI[judge])
            mask = _color_mask(roi, JUDGE_COLOR[judge])
            boxes = _extract_candidates(mask)
            for idx, (x, y, w, h) in enumerate(boxes):
                patch = mask[y:y + h, x:x + w]
                name = f"{img_path.stem}_{judge}_{idx}.png"
                _imwrite_unicode(cand_dir / name, patch)

                key = (img_path.stem, judge, idx)
                digit = gt.get(key)
                if digit is None:
                    extra_candidates.append(name)
                    continue
                _imwrite_unicode(TEMPLATE_DIR / str(digit) / name, patch)
                assigned += 1
            # ground truth にあるが抽出されなかった候補（個数減）
            for j in range(len(boxes), 10):
                if (img_path.stem, judge, j) in gt:
                    skipped_gt_missing.append(f"{img_path.stem}_{judge}_{j}")

    print(f"  candidates assigned: {assigned}")
    if extra_candidates:
        print(f"  extra (new ROI で増えた候補): {len(extra_candidates)} 件 → _candidates のみに保存")
        for n in extra_candidates[:10]:
            print(f"    - {n}")
    if skipped_gt_missing:
        print(f"  missing (新 ROI で取れなくなった候補): {len(skipped_gt_missing)} 件")
        for n in skipped_gt_missing[:10]:
            print(f"    - {n}")

    # 平均化して X.png を生成
    n_written = 0
    target_size: tuple[int, int] | None = None
    counts: dict[int, int] = {}
    for d in range(10):
        folder = TEMPLATE_DIR / str(d)
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
        counts[d] = len(images)
        if not images:
            # 既存テンプレ削除（古い見切れ版が残らないように）
            old = TEMPLATE_DIR / f"{d}.png"
            if old.exists():
                old.unlink()
            print(f"  digit {d}: 0 images (skip)")
            continue
        stacked = np.stack(images, axis=0).astype(np.float32)
        mean = stacked.mean(axis=0)
        _, template = cv2.threshold(mean.astype(np.uint8), 127, 255, cv2.THRESH_BINARY)
        out_path = TEMPLATE_DIR / f"{d}.png"
        _imwrite_unicode(out_path, template)
        n_written += 1
        print(f"  digit {d}: wrote (averaged {len(images)} images)")

    # プレビュー画像を作成
    cell_w, cell_h = (target_size if target_size else (40, 80))
    cols = 10
    margin = 4
    label_h = 20
    prev = np.full(
        ((cell_h + label_h + margin) + margin, cols * (cell_w + margin) + margin, 3),
        40, dtype=np.uint8,
    )
    for d in range(10):
        tpl_path = TEMPLATE_DIR / f"{d}.png"
        if tpl_path.exists():
            tpl = _imread_unicode(tpl_path)
            tpl_resized = cv2.resize(tpl, (cell_w, cell_h), interpolation=cv2.INTER_NEAREST)
        else:
            tpl_resized = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
        x0 = margin + d * (cell_w + margin)
        y0 = margin
        prev[y0:y0 + cell_h, x0:x0 + cell_w] = tpl_resized
        cv2.putText(
            prev, f"{d} (n={counts[d]})", (x0, y0 + cell_h + 14),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA,
        )
    _imwrite_unicode(TEMPLATE_DIR / "_templates_preview.png", prev)

    print(f"\ndone. {n_written}/10 digit templates written.")
    print(f"backup of previous folders: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
