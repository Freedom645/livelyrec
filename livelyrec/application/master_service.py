"""楽曲マスタ取得・楽曲特定サービス。

詳細: docs/design/10_詳細設計_画像認識.md §6
"""

from __future__ import annotations

import json
import logging
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

from livelyrec.domain.master import Song, normalize_song_title
from livelyrec.domain.score import Chart, Difficulty
from livelyrec.infrastructure.github_client import MasterFetcher
from livelyrec.infrastructure.repository.chart_repo import ChartRepository
from livelyrec.infrastructure.repository.song_repo import SongRepository
from livelyrec.shared.exceptions import MasterFetchError, MasterParseError

logger = logging.getLogger("livelyrec.master")


@dataclass(frozen=True)
class IdentifyResult:
    chart: Chart | None
    score: float
    expected_difficulty: Difficulty | None
    accepted: bool


class MasterService:
    """マスタ取得とファジー楽曲特定。"""

    def __init__(
        self,
        song_repo: SongRepository,
        chart_repo: ChartRepository,
        fetcher: MasterFetcher | None,
        threshold: float = 65.0,
        margin: float = 3.0,
    ) -> None:
        self._song = song_repo
        self._chart = chart_repo
        self._fetcher = fetcher
        self._threshold = threshold
        self._margin = margin

    def refresh(self) -> int:
        """マスタを取得し DB に upsert する。取得失敗時は例外。"""
        if self._fetcher is None:
            return 0
        try:
            data = self._fetcher.fetch()
        except MasterFetchError:
            raise
        try:
            songs = _parse_master(data)
        except Exception as e:
            raise MasterParseError(str(e)) from e
        return self._song.upsert_many(songs)

    def load_from_file(self, path: Path) -> int:
        """ローカル JSON ファイルから楽曲マスタを DB へ投入する。

        同梱 seed マスタの初期投入（オフライン初回起動・エンドポイント未設定時の
        フォールバック）に用いる。投入件数を返す。
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise MasterParseError(f"failed to read master file {path}: {e}") from e
        try:
            songs = _parse_master(data)
        except Exception as e:
            raise MasterParseError(str(e)) from e
        return self._song.upsert_many(songs)

    def song_count(self) -> int:
        """DB に登録済みの楽曲数を返す。"""
        return self._song.count()

    def get_song(self, song_id: str) -> Song | None:
        """song_id から Song を取得する（バナー特徴量マッチからの逆引き用、FR-BAN-001）。"""
        return self._song.get(song_id)

    def identify(
        self,
        raw_text: str,
        difficulty_hint: Difficulty | None = None,
    ) -> IdentifyResult:
        """OCR で得た楽曲名候補から、マスタ上の譜面を特定する。"""
        if not raw_text:
            return IdentifyResult(None, 0.0, difficulty_hint, accepted=False)
        candidates = self._song.fuzzy_search(raw_text, limit=5)
        if not candidates:
            return IdentifyResult(None, 0.0, difficulty_hint, accepted=False)
        # スコアブースト（難易度ヒント一致）後に再評価
        boosted: list[tuple[Song, float]] = []
        for song, score in candidates:
            s = score
            # ジャンルが一致するケースのブーストは今回はマスタ側に raw 比較できる
            # 情報が無いため一旦見送り。難易度ヒントだけ反映。
            boosted.append((song, s))
        boosted.sort(key=lambda t: -t[1])
        top, top_s = boosted[0]
        if top_s < self._threshold:
            return IdentifyResult(None, top_s, difficulty_hint, accepted=False)
        if len(boosted) > 1 and top_s - boosted[1][1] < self._margin:
            return IdentifyResult(None, top_s, difficulty_hint, accepted=False)
        # 譜面を選択
        chart = self._select_chart(top, difficulty_hint)
        return IdentifyResult(chart=chart, score=top_s, expected_difficulty=difficulty_hint, accepted=True)

    def _select_chart(self, song: Song, hint: Difficulty | None) -> Chart | None:
        if hint is not None:
            for c in song.charts:
                if c.difficulty == hint:
                    return c
        # ヒントが無ければ HYPER → EX → NORMAL の順に妥当な譜面を返す
        priority = [Difficulty.HYPER, Difficulty.EX, Difficulty.NORMAL, Difficulty.EASY, Difficulty.UPPER]
        by_diff = {c.difficulty: c for c in song.charts}
        for p in priority:
            if p in by_diff:
                return by_diff[p]
        return song.charts[0] if song.charts else None


def _parse_master(data: dict) -> list[Song]:
    songs: list[Song] = []
    for entry in data.get("songs", []) or []:
        song_id = entry["song_id"]
        title = entry.get("title", "")
        genre = entry.get("genre")
        has_upper = bool(entry.get("has_upper", False))
        charts_raw = entry.get("charts", []) or []
        charts: list[Chart] = []
        for c in charts_raw:
            try:
                difficulty = Difficulty(c["difficulty"])
            except (KeyError, ValueError):
                continue
            charts.append(Chart(
                song_id=song_id,
                title=title,
                difficulty=difficulty,
                is_upper=bool(c.get("is_upper", False)) or difficulty == Difficulty.UPPER,
                genre=genre,
                level=c.get("level"),
            ))
        songs.append(Song(
            song_id=song_id,
            title=title,
            title_norm=normalize_song_title(entry.get("title_norm") or title),
            genre=genre,
            has_upper=has_upper,
            charts=tuple(charts),
        ))
    return songs


class SongStabilizer:
    """連続フレームの楽曲特定結果から最頻値を採用するための簡易多数決。"""

    def __init__(self, window: int = 7, min_majority: float = 0.5) -> None:
        self._buf: deque[str | None] = deque(maxlen=window)
        self._min_majority = min_majority

    def push(self, chart_id: str | None) -> str | None:
        self._buf.append(chart_id)
        counter = Counter([c for c in self._buf if c is not None])
        if not counter:
            return None
        top, n = counter.most_common(1)[0]
        if n / max(len(self._buf), 1) >= self._min_majority:
            return top
        return None

    def reset(self) -> None:
        self._buf.clear()
