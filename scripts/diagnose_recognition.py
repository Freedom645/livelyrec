"""tests/fixtures/sample の実画像に認識パイプラインを通し、結果を表示する診断スクリプト。

使い方:
    .venv/Scripts/python.exe scripts/diagnose_recognition.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from livelyrec.infrastructure.ocr.digit_template import DigitTemplateRecognizer
from livelyrec.infrastructure.ocr.paddle import PaddleOcrEngine
from livelyrec.infrastructure.recognizer.pipeline import RecognitionPipeline

SAMPLE = Path("tests/fixtures/sample")
TEMPLATES = Path("templates/digits/1366x768")
SCREENS = ["選曲画面", "プレイ画面", "リザルト画面", "準備画面", "オプション画面"]


def imread_u(path: Path) -> np.ndarray | None:
    """日本語パス対応の画像読み込み。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main() -> None:
    ocr = PaddleOcrEngine()
    ocr.warm_up()
    digit = DigitTemplateRecognizer.load_from_dir(TEMPLATES)
    print(f"digit templates loaded: {digit.loaded()}")
    pipeline = RecognitionPipeline(ocr, digit)

    for screen_dir in SCREENS:
        d = SAMPLE / screen_dir
        if not d.exists():
            continue
        files = sorted(d.glob("*.png"))[:3]
        print(f"\n===== {screen_dir} ({len(files)} 件) =====")
        for f in files:
            img = imread_u(f)
            if img is None:
                print(f"  {f.name}: 読み込み失敗")
                continue
            analysis = pipeline.analyze(img)
            det = analysis.detection
            print(f"  {f.name}  shape={img.shape}")
            print(f"    判別画面 = {det.screen.value} (conf {det.confidence:.2f})")
            if analysis.play_metrics is not None:
                pm = analysis.play_metrics
                print(
                    f"    play: song='{pm.raw_song_text}' "
                    f"conf={pm.song_confidence:.2f} score={pm.score} combo={pm.combo}"
                )
            if analysis.result_metrics is not None:
                rm = analysis.result_metrics
                print(
                    f"    result: clear={rm.clear_type} score={rm.score} "
                    f"judge={rm.judgements} combo={rm.combo}"
                )


if __name__ == "__main__":
    main()
