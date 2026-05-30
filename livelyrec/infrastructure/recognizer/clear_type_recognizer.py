"""リザルト画面のクリアタイプ（Failed/Clear/FullCombo/Perfect）認識。

詳細: 詳細設計 §4.4

KONAMI の lively のクリアラベルはユニークな装飾フォント（一種の模様）で、
OCR では文字認識が困難なため（旧ロジックは OCR ベースで失敗多発）、
テンプレートマッチング方式に移行する。

- :func:`load_clear_type_templates`: `templates/result/clear_type/` 配下の
  ``failed.png`` / ``clear.png`` / ``full_combo.png`` / ``perfect.png`` を
  読み込み、辞書として返す。一部欠落でも残りで動作する。
- :func:`detect_clear_type`: 与えられた `RESULT_ROI["clear_label"]` 領域に
  対し各テンプレと :func:`cv2.matchTemplate` で相関を取り、最高スコアの
  ものを採用する。しきい値未満は ``None`` を返す。
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from livelyrec.domain.score import ClearType

logger = logging.getLogger("livelyrec.recognizer.clear_type")


DEFAULT_CLEAR_TYPE_MATCH_THRESHOLD = 0.5

# templates/result/clear_type/<name>.png → ClearType の対応
_TEMPLATE_FILE_MAP: dict[str, ClearType] = {
    "failed": ClearType.FAILED,
    "clear": ClearType.CLEAR,
    "full_combo": ClearType.FULL_COMBO,
    "perfect": ClearType.PERFECT,
}


def load_clear_type_templates(
    template_dir: Path,
) -> dict[ClearType, np.ndarray]:
    """`templates/result/clear_type/*.png` を読み込み、ClearType 別の辞書を返す。

    存在しないファイルは静かにスキップする（FULL_COMBO 等のサンプル未整備時を
    考慮）。読み込み失敗時は WARN ログを出す。
    """
    result: dict[ClearType, np.ndarray] = {}
    for stem, ct in _TEMPLATE_FILE_MAP.items():
        path = template_dir / f"{stem}.png"
        if not path.exists():
            continue
        try:
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        except OSError as e:
            logger.warning("clear_type template read failed: %s — %s", path, e)
            continue
        if img is None:
            logger.warning("clear_type template decode failed: %s", path)
            continue
        result[ct] = img
    return result


def detect_clear_type(
    roi_bgr: np.ndarray,
    templates: dict[ClearType, np.ndarray],
    threshold: float = DEFAULT_CLEAR_TYPE_MATCH_THRESHOLD,
) -> ClearType | None:
    """RESULT 画面の clear_label ROI からクリアタイプを推定する。

    各テンプレに対し ``cv2.TM_CCOEFF_NORMED`` でスコアを取り、最大スコアの
    テンプレを採用する。スコアが ``threshold`` 未満の場合は ``None`` を返し、
    呼び出し側で「未検出」として扱う（既存挙動の互換）。

    入力 ROI とテンプレが同サイズでないとマッチ失敗するため、テンプレ側に
    合わせて ROI をリサイズする。
    """
    if not templates:
        return None
    best_score = -1.0
    best_type: ClearType | None = None
    for ct, tpl in templates.items():
        if tpl.shape != roi_bgr.shape:
            try:
                resized = cv2.resize(
                    roi_bgr, (tpl.shape[1], tpl.shape[0]),
                    interpolation=cv2.INTER_AREA,
                )
            except cv2.error:
                continue
        else:
            resized = roi_bgr
        try:
            res = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)
        except cv2.error as e:
            logger.warning("matchTemplate failed for %s: %s", ct, e)
            continue
        _, score, _, _ = cv2.minMaxLoc(res)
        if score > best_score:
            best_score = float(score)
            best_type = ct
    if best_score < threshold:
        return None
    return best_type
