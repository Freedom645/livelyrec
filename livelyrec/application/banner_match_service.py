"""バナー画像特徴量によるマッチング・楽曲特定サービス（FR-BAN-001〜004, v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §5

`data/banner_features.json` を起動時にメモリへロードし、フレーム入力に対して
pHash+dHash 合算ハミング距離で Top-K マッチを行う 2 次認識器を提供する。

- :class:`BannerFeature`: 1 楽曲の特徴量エントリ
- :class:`BannerMatchResult`: 識別結果
- :class:`BannerMatchService`: メイン。`from_json` でロード、`identify` でマッチ
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from livelyrec.infrastructure.banner_features import (
    DEFAULT_TARGET_SIZE,
    dhash64,
    hamming,
    hash_from_hex,
    phash64,
    prepare_gray,
)

logger = logging.getLogger("livelyrec.banner_match")

# しきい値の規定値（pHash 距離 + dHash 距離、0〜128）。
# PoC #04 §7.6 / 詳細設計 §5.3 を参照。
DEFAULT_ACCEPT_THRESHOLD = 20
DEFAULT_CANDIDATE_THRESHOLD = 40

# 起動時に許容される schema_version の上限。スキーマ拡張時にここを引き上げる。
SUPPORTED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BannerFeature:
    """1 楽曲のバナー特徴量エントリ。"""

    song_id: str
    phash: int  # 64bit
    dhash: int  # 64bit
    src: tuple[str, ...]


@dataclass(frozen=True)
class BannerMatchResult:
    """バナー識別結果。"""

    song_id: str
    distance: int  # pHash 距離 + dHash 距離（0〜128）
    confidence: float  # 0.0〜1.0、distance から算出
    accepted: bool


class BannerMatchService:
    """バナー特徴量によるマッチングサービス（2 次認識器）。"""

    def __init__(
        self,
        features: list[BannerFeature],
        accept_threshold: int = DEFAULT_ACCEPT_THRESHOLD,
        candidate_threshold: int = DEFAULT_CANDIDATE_THRESHOLD,
        target_size: tuple[int, int] = DEFAULT_TARGET_SIZE,
    ) -> None:
        if accept_threshold < 0 or accept_threshold > 128:
            raise ValueError(f"accept_threshold out of range: {accept_threshold}")
        if candidate_threshold < accept_threshold or candidate_threshold > 128:
            raise ValueError(
                f"candidate_threshold must be in [{accept_threshold}, 128]: "
                f"{candidate_threshold}"
            )
        self._features = list(features)
        self._accept_threshold = accept_threshold
        self._candidate_threshold = candidate_threshold
        self._target_size = target_size

    @classmethod
    def from_json(
        cls,
        path: Path,
        accept_threshold: int = DEFAULT_ACCEPT_THRESHOLD,
        candidate_threshold: int = DEFAULT_CANDIDATE_THRESHOLD,
    ) -> BannerMatchService:
        """`data/banner_features.json` を読み込みインスタンス化する。"""
        features, target_size = _load_features(path)
        logger.info(
            "loaded %d banner features from %s (target_size=%s)",
            len(features),
            path,
            target_size,
        )
        return cls(
            features=features,
            accept_threshold=accept_threshold,
            candidate_threshold=candidate_threshold,
            target_size=target_size,
        )

    @property
    def feature_count(self) -> int:
        return len(self._features)

    @property
    def target_size(self) -> tuple[int, int]:
        return self._target_size

    def reload(self, path: Path) -> int:
        """JSON を再読込し、特徴量集合を入れ替える。返り値はロード件数。"""
        features, target_size = _load_features(path)
        self._features = features
        self._target_size = target_size
        logger.info("reloaded %d banner features from %s", len(features), path)
        return len(features)

    def identify(
        self,
        frame_bgr: np.ndarray,
        roi: tuple[int, int, int, int],
        primary_candidates: list[str] | None = None,
    ) -> BannerMatchResult | None:
        """フレームから ROI を切り出し、特徴量マッチを行う。

        - 特徴量集合が空 → None
        - ROI 範囲外 → None（WARN ログ）
        - distance ≤ accept_threshold → accepted=True
        - accept_threshold < distance ≤ candidate_threshold:
            primary_candidates に Top-1 が含まれていれば accepted=True
        - それ以外 → accepted=False（一応 Top-1 を返す、呼び出し側で破棄可）
        """
        if not self._features:
            return None
        gray = prepare_gray(frame_bgr, roi, self._target_size)
        if gray is None:
            logger.warning(
                "banner ROI out of frame: roi=%s frame=%sx%s",
                roi,
                frame_bgr.shape[1],
                frame_bgr.shape[0],
            )
            return None
        q_phash = phash64(gray)
        q_dhash = dhash64(gray)
        best = self._best_match(q_phash, q_dhash)
        if best is None:
            return None
        feat, distance = best
        confidence = _distance_to_confidence(distance)
        accepted = distance <= self._accept_threshold
        if (
            not accepted
            and distance <= self._candidate_threshold
            and primary_candidates is not None
            and feat.song_id in primary_candidates
        ):
            accepted = True
        return BannerMatchResult(
            song_id=feat.song_id,
            distance=distance,
            confidence=confidence,
            accepted=accepted,
        )

    def _best_match(
        self,
        q_phash: int,
        q_dhash: int,
    ) -> tuple[BannerFeature, int] | None:
        best: tuple[BannerFeature, int] | None = None
        for feat in self._features:
            d = hamming(q_phash, feat.phash) + hamming(q_dhash, feat.dhash)
            if best is None or d < best[1]:
                best = (feat, d)
        return best


def _distance_to_confidence(distance: int) -> float:
    """ハミング距離（0〜128）を 0.0〜1.0 の信頼度にマップする。

    distance=0 → 1.0、distance=128 → 0.0 の単純な線形写像。
    """
    if distance < 0:
        return 1.0
    if distance >= 128:
        return 0.0
    return 1.0 - distance / 128.0


def _load_features(path: Path) -> tuple[list[BannerFeature], tuple[int, int]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BannerFeaturesLoadError(f"failed to read {path}: {e}") from e
    schema_version = int(data.get("schema_version", 1))
    if schema_version > SUPPORTED_SCHEMA_VERSION:
        raise BannerFeaturesLoadError(
            f"unsupported schema_version={schema_version} (supported<={SUPPORTED_SCHEMA_VERSION})"
        )
    target_raw = data.get("target_size") or list(DEFAULT_TARGET_SIZE)
    if len(target_raw) != 2:
        raise BannerFeaturesLoadError(f"invalid target_size: {target_raw}")
    target_size = (int(target_raw[0]), int(target_raw[1]))
    features: list[BannerFeature] = []
    for i, entry in enumerate(data.get("songs", []) or []):
        try:
            song_id = entry["song_id"]
            phash = hash_from_hex(entry["phash"])
            dhash = hash_from_hex(entry["dhash"])
        except (KeyError, ValueError) as e:
            logger.warning("skip malformed banner entry #%d: %s", i, e)
            continue
        src_raw = entry.get("src")
        if isinstance(src_raw, str):
            src = (src_raw,)
        elif isinstance(src_raw, list):
            src = tuple(str(x) for x in src_raw)
        else:
            src = ()
        features.append(
            BannerFeature(song_id=song_id, phash=phash, dhash=dhash, src=src)
        )
    return features, target_size


class BannerFeaturesLoadError(Exception):
    """banner_features.json のロード失敗。"""
