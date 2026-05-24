"""システムテスト 区分A: 録画リプレイによる認識正答率測定。

詳細: docs/design/15_システムテスト計画書.md §4

使い方:
    .venv/Scripts/python.exe -m scripts.system_test_replay

- 画面判別: `tests/fixtures/sample/<画面名フォルダ>/` のフォルダ名を正解として正答率を測定する。
- メトリクス: `tests/fixtures/sample/_ground_truth.csv`（あれば）の正解値と認識結果を突合する。
  CSV 列: path,screen,song_id,score,cool,great,good,bad,combo
  （path はリポジトリルートからの相対パス。空セルは未ラベル＝対象外）
"""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import numpy as np

from livelyrec.domain.state import ScreenType
from livelyrec.infrastructure.recognizer.normalize import normalize_frame
from livelyrec.infrastructure.recognizer.screen_detector import ScreenDetector

SAMPLE_ROOT = Path("tests/fixtures/sample")
GROUND_TRUTH_CSV = SAMPLE_ROOT / "_ground_truth.csv"

# tests/fixtures/sample のフォルダ名 → 期待画面種別
_FOLDER_TO_SCREEN: dict[str, ScreenType] = {
    "選曲画面": ScreenType.SELECT,
    "プレイ画面": ScreenType.PLAY,
    "リザルト画面": ScreenType.RESULT,
    "準備画面": ScreenType.READY,
    "オプション画面": ScreenType.OPTION,
    "プレイ画面前ロード画面": ScreenType.LOAD_TO_PLAY,
    "準備画面前ロード画面": ScreenType.LOAD_TO_READY,
}


def _imread_u(path: Path) -> np.ndarray | None:
    """日本語パス対応の画像読み込み。"""
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def measure_screen_detection() -> tuple[int, int, list[tuple[str, str, str, str]]]:
    """tests/fixtures/sample のフォルダ名を正解に画面判別正答率を測定する。"""
    detector = ScreenDetector()
    total = 0
    ok = 0
    mistakes: list[tuple[str, str, str, str]] = []
    for folder, expected in _FOLDER_TO_SCREEN.items():
        d = SAMPLE_ROOT / folder
        if not d.exists():
            continue
        for f in sorted(d.glob("*.png")):
            img = _imread_u(f)
            if img is None:
                continue
            norm = normalize_frame(img)
            result = detector.detect(norm.image_bgr)
            total += 1
            if result.screen == expected:
                ok += 1
            else:
                mistakes.append((folder, f.name, expected.value, result.screen.value))
    return ok, total, mistakes


def measure_metrics() -> None:
    """正解 CSV があればメトリクス正答率を測定する（無ければスキップ）。"""
    if not GROUND_TRUTH_CSV.exists():
        print(
            "\n（メトリクス測定はスキップ: 正解データ "
            f"{GROUND_TRUTH_CSV} が未整備）"
        )
        return
    # 正解 CSV が用意され次第、ここでパイプライン全体を通して項目別正答率を算出する。
    from livelyrec.infrastructure.ocr.digit_template import DigitTemplateRecognizer
    from livelyrec.infrastructure.ocr.paddle import PaddleOcrEngine
    from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline

    ocr = PaddleOcrEngine()
    ocr.warm_up()
    digit = DigitTemplateRecognizer.load_from_dir(Path("templates/digits/1366x768"))
    pipeline = RecognitionPipeline(ocr, digit)

    counters: dict[str, list[int]] = {}  # 項目 -> [正解数, 件数]
    with GROUND_TRUTH_CSV.open(encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            # path はリポジトリルートからの相対パス
            img = _imread_u(Path(row["path"]))
            if img is None:
                print(f"  （読み込み失敗: {row['path']}）")
                continue
            analysis = pipeline.analyze(img)
            _compare_row(analysis, row, counters)

    print("\n=== メトリクス正答率 ===")
    for item, (hit, n) in sorted(counters.items()):
        rate = 100.0 * hit / n if n else 0.0
        print(f"  {item}: {hit}/{n} ({rate:.1f}%)")


def _compare_row(analysis, row: dict, counters: dict[str, list[int]]) -> None:
    """1 フレームの認識結果と正解行を項目別に突合する。"""
    def _check(item: str, expected: str | None, actual) -> None:
        if not expected:
            return
        c = counters.setdefault(item, [0, 0])
        c[1] += 1
        if str(actual) == str(expected).strip():
            c[0] += 1

    _check("screen", row.get("screen"), analysis.detection.screen.value)
    pm = analysis.play_metrics
    if pm is not None:
        _check("play_score", row.get("score"), pm.score)
    rm = analysis.result_metrics
    if rm is not None:
        _check("result_score", row.get("score"), rm.score)
        _check("result_combo", row.get("combo"), rm.combo)
        _check("cool", row.get("cool"), rm.judgements.cool)
        _check("great", row.get("great"), rm.judgements.great)
        _check("good", row.get("good"), rm.judgements.good)
        _check("bad", row.get("bad"), rm.judgements.bad)


def main() -> None:
    print("=== システムテスト 区分A: 録画リプレイ ===\n")
    ok, total, mistakes = measure_screen_detection()
    rate = 100.0 * ok / total if total else 0.0
    print(f"画面判別正答率: {ok}/{total}  ({rate:.1f}%)")
    for folder, name, exp, act in mistakes:
        print(f"  NG: {folder}/{name}  expected={exp} actual={act}")
    measure_metrics()


if __name__ == "__main__":
    main()
