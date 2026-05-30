"""画面別メトリクス抽出。

詳細: docs/design/10_詳細設計_画像認識.md §5
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import cv2
import numpy as np

from livelyrec.domain.score import ClearType, Difficulty, Judgements

from .normalize import crop
from .roi_defs import PLAY_DIFFICULTY_ROI, PLAY_JUDGE_ROI, PLAY_ROI, RESULT_ROI

# プレイ画面 難易度バッジのテーマ色（BGR）。pop'n music lively の難易度テーマ色。
_DIFFICULTY_THEME_BGR: dict[Difficulty, tuple[int, int, int]] = {
    Difficulty.EASY:   (255, 198, 46),   # 水色 #2EC6FF
    Difficulty.NORMAL: (47, 217, 59),    # 緑色 #3BD92F
    Difficulty.HYPER:  (0, 120, 255),    # 橙色 #FF7800
    Difficulty.EX:     (137, 81, 255),   # 桃色 #FF5189
}
# テーマ色からの距離がこの値を超えたら難易度不明とする（4色は最近接でも約142離れている）。
_DIFFICULTY_MATCH_THRESHOLD = 90.0

_FULLWIDTH_DIGIT_TRANS = str.maketrans({
    "Ｓ": "5", "ｓ": "5", "Ｏ": "0", "ｏ": "0", "Ｂ": "8",
})

_AGGRESSIVE_DIGIT_TRANS = str.maketrans({
    "O": "0", "I": "1", "l": "1", "B": "8", "S": "5",
})


def digits_only(text: str) -> str:
    """OCR 出力から数字のみを抽出（全角→半角および全角の装飾誤読補正のみ）。

    一般のテキスト中の半角英字（B/O/S 等）は数字に変換しない。
    判定数 ROI のように「英字に見えるのは全部数字」と分かっている場合は
    ``digits_only_aggressive`` を使うこと。
    """
    if not text:
        return ""
    # 全角の装飾誤読補正は NFKC より前に行う（NFKC が全角→半角にしてしまうため）
    norm = text.translate(_FULLWIDTH_DIGIT_TRANS)
    norm = unicodedata.normalize("NFKC", norm)
    return "".join(c for c in norm if c.isdigit())


def digits_only_aggressive(text: str) -> str:
    """半角英字の誤読も数字に補正してから抽出する（数字限定 ROI 向け）。"""
    if not text:
        return ""
    norm = text.translate(_FULLWIDTH_DIGIT_TRANS)
    norm = unicodedata.normalize("NFKC", norm).translate(_AGGRESSIVE_DIGIT_TRANS)
    return "".join(c for c in norm if c.isdigit())


def parse_int_or(text: str, default: int | None = None) -> int | None:
    digits = digits_only(text)
    if not digits:
        return default
    try:
        return int(digits)
    except ValueError:
        return default


@dataclass(frozen=True)
class PlayMetrics:
    """プレイ画面から抽出した1フレームのメトリクス。"""

    raw_song_text: str
    song_confidence: float
    score: int | None
    combo: int | None
    # プレイ画面下部の判定数累計（GROOVE GAUGE 下の BAD/GOOD/GREAT/COOL）
    judgements: Judgements = field(default_factory=Judgements)
    # 難易度バッジのテーマ色から判定した難易度
    difficulty: Difficulty | None = None


@dataclass(frozen=True)
class ResultMetrics:
    """リザルト画面から抽出した1フレームのメトリクス。"""

    clear_type: ClearType | None
    score: int | None
    judgements: Judgements
    combo: int | None
    best_score_diff: int | None


def _mask_white_text(roi_bgr: np.ndarray) -> np.ndarray:
    """黒背景に白文字の領域に対し、白文字のみを残す。"""
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 180), (180, 60, 255))
    return cv2.bitwise_and(roi_bgr, roi_bgr, mask=mask)


def extract_play_judgements(frame_bgr: np.ndarray, digit_recognizer) -> Judgements:
    """プレイ画面下部の判定数累計（BAD/GOOD/GREAT/COOL）を抽出する。

    各判定は「ラベル＋4桁数字」が固有色で並ぶ。色マスクで判定ごとに分離し、
    右端の数字部のみを digit テンプレートマッチングで読む。

    プレイ画面の判定数フォントはラベル文字と数字が色マスク上で連結しやすく
    切り出しが安定しないため、**4桁ちょうど読めた場合のみ採用**し、それ以外
    （切り出し失敗・部分読み）は 0 とする。日次カウンタの確定値はリザルト
    画面の判定数（高精度）で更新されるため、ここは保守的に倒してよい。
    digit_recognizer 未指定時は全 0 を返す。
    """
    if digit_recognizer is None:
        return Judgements()
    judge_roi = crop(frame_bgr, PLAY_JUDGE_ROI)
    counts: dict[str, int] = {}
    for key in ("cool", "great", "good", "bad"):
        text, _ = digit_recognizer.recognize_rightmost(judge_roi, key, 4)
        counts[key] = int(text) if len(text) == 4 and text.isdigit() else 0
    return Judgements(
        cool=counts["cool"],
        great=counts["great"],
        good=counts["good"],
        bad=counts["bad"],
    )


def extract_play_difficulty(frame_bgr: np.ndarray) -> Difficulty | None:
    """プレイ画面の難易度バッジのテーマ色から難易度を判定する。

    バッジ円内のテーマ色サンプル領域の平均色を、4 難易度のテーマ色に
    最近傍照合する。全色から離れている（バッジが無い等）場合は None。
    """
    roi = crop(frame_bgr, PLAY_DIFFICULTY_ROI)
    if roi.size == 0:
        return None
    mean = roi.reshape(-1, 3).astype(np.float64).mean(axis=0)
    best: Difficulty | None = None
    best_dist = _DIFFICULTY_MATCH_THRESHOLD
    for diff, bgr in _DIFFICULTY_THEME_BGR.items():
        dist = float(np.linalg.norm(mean - np.array(bgr, dtype=np.float64)))
        if dist < best_dist:
            best_dist, best = dist, diff
    return best


def extract_play_metrics(
    frame_bgr: np.ndarray,
    ocr,
    digit_recognizer=None,
    *,
    skip_song_ocr: bool = False,
) -> PlayMetrics:
    """プレイ画面のメトリクスを抽出する。

    プレイ中の連続的な OCR 呼び出しは PaddleOCR ネイティブ層で稀に
    access violation を起こしてプロセスを強制終了させる（I-027）。
    取得頻度と発火点を絞るため:
    - 楽曲が既に特定済みのときは `skip_song_ocr=True` を渡すことで楽曲名
      OCR の発火を抑止する。呼び出し側（`analysis_service`）が制御する。
    - プレイ画面のスコア／コンボの OCR 呼び出しは廃止（リトライ検出は
      判定数で十分機能する）。スコアアニメーション中の値読みでの誤検出
      リスクも同時に排除される。
    """
    if skip_song_ocr:
        raw_song_text = ""
        song_conf = 0.0
    else:
        song_roi = crop(frame_bgr, PLAY_ROI["song_name"])
        masked = _mask_white_text(song_roi)
        song_items = ocr.recognize(masked)
        raw_song_text = "".join(item.text for item in song_items)
        song_conf = (
            sum(i.confidence for i in song_items) / len(song_items)
            if song_items
            else 0.0
        )

    return PlayMetrics(
        raw_song_text=raw_song_text,
        song_confidence=song_conf,
        score=None,
        combo=None,
        judgements=extract_play_judgements(frame_bgr, digit_recognizer),
        difficulty=extract_play_difficulty(frame_bgr),
    )


def _detect_clear_type(
    roi_bgr: np.ndarray,
    ocr,
    clear_type_templates: dict | None = None,
) -> ClearType | None:
    """クリアタイプを判定する。

    優先: テンプレートマッチング（装飾フォント対応、推奨）。
    フォールバック: OCR 文字列マッチ（既存ロジック、テンプレ未配備時の互換）。
    """
    if clear_type_templates:
        from .clear_type_recognizer import detect_clear_type
        ct = detect_clear_type(roi_bgr, clear_type_templates)
        if ct is not None:
            return ct
        # テンプレマッチ失敗時は OCR フォールバックも試す（保険）
    text = ocr.recognize_text(roi_bgr).upper()
    if "PERFECT" in text:
        return ClearType.PERFECT
    if "FULL" in text and "COMBO" in text:
        return ClearType.FULL_COMBO
    if "FAIL" in text:
        return ClearType.FAILED
    if "STAGE" in text or "CLEAR" in text:
        return ClearType.CLEAR
    return None


def _recognize_digits(roi_bgr: np.ndarray, digit_recognizer, color_key: str, ocr) -> int | None:
    """装飾数字をテンプレートマッチングで読み取り int を返す。失敗時は None。

    リザルトの score/combo/判定数は装飾グラデーションフォントで OCR が困難なため、
    digit テンプレートマッチングを一次手段とし、空振り時のみ OCR にフォールバックする。
    """
    digit_text, _ = digit_recognizer.recognize(roi_bgr, color_key)
    if not digit_text and ocr is not None:
        # フォールバック: OCR（数字限定 ROI のため英字誤読も数字とみなす）
        digit_text = digits_only_aggressive(ocr.recognize_text(roi_bgr))
    if not digit_text:
        return None
    try:
        return int(digit_text)
    except ValueError:
        return None


def extract_result_metrics(
    frame_bgr: np.ndarray,
    ocr,
    digit_recognizer,
    clear_type_templates: dict | None = None,
) -> ResultMetrics:
    """リザルト画面のメトリクスを抽出する。

    score/combo/判定数は装飾フォントのため digit テンプレートマッチングで取得する（I-016）。
    clear_type はテンプレートマッチング（`clear_type_templates`）で取得する。
    テンプレ未配備時は OCR フォールバック（旧挙動）。
    """
    clear_type = _detect_clear_type(
        crop(frame_bgr, RESULT_ROI["clear_label"]), ocr,
        clear_type_templates=clear_type_templates,
    )

    score = _recognize_digits(
        crop(frame_bgr, RESULT_ROI["score"]), digit_recognizer, "score", ocr
    )
    combo = _recognize_digits(
        crop(frame_bgr, RESULT_ROI["combo"]), digit_recognizer, "combo", ocr
    )

    judges: dict[str, int] = {}
    for key in ("cool", "great", "good", "bad"):
        judges[key] = (
            _recognize_digits(crop(frame_bgr, RESULT_ROI[key]), digit_recognizer, key, ocr)
            or 0
        )

    best_diff = _parse_signed_int(ocr.recognize_text(crop(frame_bgr, RESULT_ROI["best_diff"])))

    return ResultMetrics(
        clear_type=clear_type,
        score=score,
        judgements=Judgements(
            cool=judges["cool"],
            great=judges["great"],
            good=judges["good"],
            bad=judges["bad"],
        ),
        combo=combo,
        best_score_diff=best_diff,
    )


def _parse_signed_int(text: str) -> int | None:
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)
    sign = 1
    if "-" in norm or "−" in norm:
        sign = -1
    digits = digits_only(text)
    if not digits:
        return None
    try:
        return sign * int(digits)
    except ValueError:
        return None
