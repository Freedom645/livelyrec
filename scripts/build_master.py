"""楽曲マスタ JSON 生成スクリプト。

詳細: docs/design/05_基本設計書.md §6.3、docs/design/10_詳細設計_画像認識.md §6

公式「収録楽曲一覧」 https://p.eagate.573.jp/game/eacpopn/lively/info/music.html
からタイトル・アーティスト情報をスクレイピングしてマスタJSONを生成する。

難易度別レベルは現在のところ未取得（上級攻略Wikiとの突合は次バージョンで実装）。
当面は EASY/NORMAL/HYPER/EX の4譜面が存在すると仮定し level=None で出力する。

Usage:
    python scripts/build_master.py --out master.json
    python scripts/build_master.py --out master.json --offline   # ネットアクセスなし(雛形)

詳細: docs/design/05_基本設計書.md §6.3、リスク R-009/R-011 参照
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# 親ディレクトリを sys.path に入れて livelyrec を import 可能にする
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.domain.master import normalize_song_title  # noqa: E402

OFFICIAL_URL = "https://p.eagate.573.jp/game/eacpopn/lively/info/music.html"
USER_AGENT = "LivelyRec/0.1 (+https://github.com/Freedom645/livelyrec)"

DEFAULT_DIFFICULTIES = ("EASY", "NORMAL", "HYPER", "EX")


def _slug_song_id(title: str) -> str:
    """安定 ID を採番する。タイトルから決定的に生成し、順序変化に強い。"""
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    return f"popn-{digest}"


def fetch_official(url: str = OFFICIAL_URL, timeout: float = 30.0) -> list[tuple[str, str]]:
    """公式サイトから (title, artist) のリストを取得する。"""
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    seen: set[str] = set()
    songs: list[tuple[str, str]] = []
    header_label_title = ("タイトル", "曲名", "Title")

    for t in tables:
        rows = t.find_all("tr")
        if not rows:
            continue
        header_cells = [_cell_text(c) for c in rows[0].find_all(["th", "td"])]
        is_song_table = (
            len(header_cells) >= 2
            and (
                header_cells[0] in header_label_title
                or "title" in header_cells[0].lower()
            )
        )
        data_rows = rows[1:] if is_song_table else rows
        for r in data_rows:
            cells = [_cell_text(c) for c in r.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            title, artist = cells[0], cells[1]
            if not title or title in header_label_title:
                continue
            if title in seen:
                continue
            seen.add(title)
            songs.append((title, artist))
    return songs


def _cell_text(cell) -> str:
    """テーブルセルからテキストを抽出する。脚注用 `<sup>` 要素は除外し、
    `<span>` 内に直書きされた末尾注釈もパターンで除去する。

    公式サイトの楽曲一覧では脚注が複数形式で表示される:
      - `<sup>*初移植曲</sup>` 形式 → decompose で除去（v2.0 修正）
      - `<span style="...">title  *特別ボーナス曲</span>` 形式 → 末尾注釈の
        テキスト除去で対応（2026-05-31 追加）
    """
    # 構造的脚注（<sup>）はそのまま decompose
    for sup in cell.find_all("sup"):
        sup.decompose()
    text = cell.get_text(strip=True)
    # 末尾注釈テキスト除去（既知パターン）
    return _strip_title_annotations(text)


# 公式サイトで楽曲名末尾に付与される注釈テキストの既知パターン
_TITLE_ANNOTATION_RE = re.compile(
    r"\s*\*(?:特別ボーナス曲|初移植曲)\s*$"
)

# 末尾の "(UPPER)" は譜面区別の表記であり楽曲名の一部ではない。
# 通常譜面と UPPER 譜面は同一 song_id 下の charts[].is_upper=True で表現する
# ため、楽曲名からは除去して通常エントリへマージする。
_UPPER_SUFFIX_RE = re.compile(r"\s*\(UPPER\)\s*$", re.IGNORECASE)


def _strip_title_annotations(title: str) -> str:
    """楽曲名末尾の注釈テキスト（*特別ボーナス曲 / *初移植曲 / (UPPER)）を除去する。

    "(UPPER)" は譜面区別のための表記であり、master.json では同一 song_id の
    charts[].is_upper=True で扱うため、楽曲名からは除去する。
    """
    cleaned = _TITLE_ANNOTATION_RE.sub("", title)
    cleaned = _UPPER_SUFFIX_RE.sub("", cleaned)
    return cleaned.strip()


def build_master(songs: list[tuple[str, str]]) -> dict:
    """(title, artist) のリストをマスタJSON形式に変換する。"""
    entries = []
    for title, artist in songs:
        song_id = _slug_song_id(title)
        entries.append({
            "song_id": song_id,
            "title": title,
            "title_norm": normalize_song_title(title),
            "artist": artist,
            "genre": None,         # 公式サイトでは取得できないので None
            "has_upper": False,    # 未取得。UPPER譜面は実機データから補完予定
            "charts": [
                {"difficulty": d, "level": None}
                for d in DEFAULT_DIFFICULTIES
            ],
        })
    return {
        "version": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": OFFICIAL_URL,
        "songs": entries,
    }


def build_minimal_master() -> dict:
    """サンプル用の最小マスタ（オフライン動作確認用）。"""
    songs = [
        ("ぽぽぽかレトロード", "Sample Artist"),
        ("漆黒のスペシャルプリンセスサンデー", "Sample Artist"),
    ]
    return build_master(songs)


def main() -> int:
    parser = argparse.ArgumentParser(description="楽曲マスタ JSON を生成する")
    parser.add_argument("--out", type=Path, default=Path("master.json"))
    parser.add_argument("--offline", action="store_true",
                        help="ネットアクセスなしで雛形マスタを出力する")
    parser.add_argument("--url", default=OFFICIAL_URL)
    parser.add_argument("--levels-from", type=Path, default=None,
                        help="難易度レベルを補完する CSV/JSON ファイル。"
                             " CSV列: title,difficulty,level（ヘッダあり）。"
                             " JSON形式: [{\"title\":..., \"difficulty\":..., \"level\":...}, ...]")
    args = parser.parse_args()

    if args.offline:
        data = build_minimal_master()
    else:
        print(f"fetching {args.url} ...", flush=True)
        t0 = time.perf_counter()
        songs = fetch_official(args.url)
        print(f"fetched {len(songs)} songs in {time.perf_counter() - t0:.1f}s", flush=True)
        data = build_master(songs)

    if args.levels_from is not None:
        n_filled = apply_level_overrides(data, args.levels_from)
        print(f"applied {n_filled} level overrides from {args.levels_from}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out} ({len(data['songs'])} songs)")
    return 0


def _load_level_overrides(path: Path) -> list[dict]:
    """CSV または JSON から (title, difficulty, level) のリストを読み込む。"""
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    # CSV (UTF-8 / UTF-8-BOM 両対応)
    import csv
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def apply_level_overrides(data: dict, path: Path) -> int:
    """master JSON の chart.level を上書きする。タイトル＋難易度で突合。"""
    overrides = _load_level_overrides(path)
    # title -> song の索引（O(1) ルックアップ）
    index = {s["title"]: s for s in data["songs"]}
    n = 0
    for row in overrides:
        title = row.get("title")
        difficulty = row.get("difficulty")
        level = row.get("level")
        if not (title and difficulty):
            continue
        song = index.get(title)
        if song is None:
            continue
        for c in song["charts"]:
            if c["difficulty"] == difficulty:
                try:
                    c["level"] = int(level) if level not in (None, "") else None
                except (TypeError, ValueError):
                    continue
                n += 1
                break
    return n


if __name__ == "__main__":
    raise SystemExit(main())
