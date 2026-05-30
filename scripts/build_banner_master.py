"""バナー特徴量マスタ JSON 生成スクリプト（FR-BAN-003, FR-BAN-011, v2.0）。

★ 開発者専用ツール ★
本スクリプトは **開発者の作業環境でのみ実行するツール** であり、エンドユーザは
実行しない。アプリのランタイム動作とは独立しており、生成物
（data/banner_features.json、数値ハッシュのみ）を GitHub Releases に同梱配布する。

詳細: docs/design/11_詳細設計_バナー認識.md §4

remywiki.com および popnmusic.fandom.com の各楽曲ページから:

1. CS_pnm_Lively ページの楽曲ページリンクを抽出
2. 各曲ページ wikitext を MediaWiki API で取得
3. Infobox から **原タイトル（Japanese title）** を抽出
4. master.json と rapidfuzz マッチで突合
5. 画像 URL を取得 → 開発者ローカル一時キャッシュへ DL
6. 390×94 リサイズ正規化 → pHash/dHash 計算
7. data/banner_features.json 出力（ハッシュ値のみ。画像本体はコミット対象外）

要件 v0.8（2026-05-29）でアプリのランタイム動作からはバナー画像本体を完全
排除した。ローカル DL する画像本体は本スクリプトの作業用一時ファイルであり、
.gitignore で除外され配布物・リポジトリには一切含まれない（NFR-LEGAL-001 / 005）。

Usage（開発者環境のみ）:
    python scripts/build_banner_master.py \\
        --master-json data/master.json \\
        --cache-dir poc_out/banners_ref \\
        --out data/banner_features.json \\
        --limit 50
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livelyrec.infrastructure.banner_features import (  # noqa: E402
    DEFAULT_TARGET_SIZE,
    dhash64,
    hex_from_hash,
    phash64,
)

logger = logging.getLogger("build_banner_master")

USER_AGENT = (
    "LivelyRec/0.2 (banner-master builder; non-commercial; +https://example.invalid)"
)

REMYWIKI_API = "https://remywiki.com/api.php"
FANDOM_API = "https://popnmusic.fandom.com/api.php"

# 収集起点ページ群（v3、2026-05-29）。
# CS_pnm_Lively だけだと AC peace 以降で初登場した lively 収録曲（例: 革命パッショネイト）が
# 漏れるため、最近の AC pnm シリーズページも起点に加えて和集合を取る。
# 各ページから抽出したリンク群は重複除去後、is_song_page() で楽曲ページのみに絞られる。
LIVELY_SOURCE_PAGES: tuple[str, ...] = (
    "CS_pnm_Lively",
    "AC_pnm_peace",
    "AC_pnm_UniLab",
    "AC_pnm_Jam&Fizz",
    "AC_pnm_Kaimei_Riddles",
)

EXCLUDE_PREFIXES = (
    "AC pnm",
    "CS pnm",
    "Pop'n music",
    "Category:",
    "File:",
    "Template:",
    "Help:",
    "User:",
    "MediaWiki:",
    "Special:",
)
EXCLUDE_EXACT = {
    "Main Page", "Konami", "BEMANI", "DanceDanceRevolution",
    "GuitarFreaks", "DrumMania", "GITADORA", "jubeat", "REFLEC BEAT",
    "SOUND VOLTEX", "beatmania", "beatmania IIDX", "DANCERUSH STARDOM",
    "NOSTALGIA",
}

# Infobox から原タイトル候補を抽出する正規表現（remywiki 慣例）
INFOBOX_TITLE_KEYS = (
    "japanese_title",
    "jp_title",
    "japanese",
    "original_title",
    "title",
    "song_name",
    "genre",
)


def http_json(url: str, timeout: float = 30.0) -> dict:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_page_links(page_title: str, rate_sec: float) -> list[str]:
    """指定 MediaWiki ページの全リンクを取得する（continue 対応）。"""
    titles: list[str] = []
    plcontinue: str | None = None
    while True:
        url = (
            f"{REMYWIKI_API}?action=query&format=json&prop=links"
            f"&titles={quote(page_title)}&pllimit=500"
        )
        if plcontinue:
            url += f"&plcontinue={quote(plcontinue)}"
        data = http_json(url)
        pages = data.get("query", {}).get("pages", {}) or {}
        for _, p in pages.items():
            for link in p.get("links", []) or []:
                titles.append(link["title"])
        plcontinue = data.get("continue", {}).get("plcontinue")
        if not plcontinue:
            break
        time.sleep(rate_sec)
    return titles


def fetch_lively_page_links(rate_sec: float) -> list[str]:
    """LIVELY_SOURCE_PAGES の全リンクを和集合（重複除去）で取得する。

    CS_pnm_Lively だけだと AC peace 以降で初登場した楽曲（例: 革命パッショネイト）が
    漏れるため、複数の AC pnm シリーズページも起点に加える。
    """
    seen: set[str] = set()
    titles: list[str] = []
    for i, page in enumerate(LIVELY_SOURCE_PAGES):
        logger.info(
            "fetching links from [%d/%d] %s ...",
            i + 1, len(LIVELY_SOURCE_PAGES), page,
        )
        page_titles = fetch_page_links(page, rate_sec)
        added = 0
        for t in page_titles:
            if t not in seen:
                seen.add(t)
                titles.append(t)
                added += 1
        logger.info(
            "  %s: %d links (+%d new, total %d)",
            page, len(page_titles), added, len(titles),
        )
        if i < len(LIVELY_SOURCE_PAGES) - 1:
            time.sleep(rate_sec)
    return titles


def fetch_lively_songs_by_search(rate_sec: float) -> list[str]:
    """remywiki の wikitext 全文検索 `insource:"pop'n music Lively"` で
    Lively 収録楽曲ページを取得する（v4、2026-05-30）。

    起点ページ方式（fetch_lively_page_links）では他機種初出曲（REFLEC BEAT
    colette 等）のページが捕捉できない問題があり、wikitext 内に
    `pop'n music Lively` を含むページを直接検索することで救済する。
    収集対象は楽曲ページ（Song Information セクションあり）のみに後段で
    フィルタされる。
    """
    titles: list[str] = []
    seen: set[str] = set()
    sroffset = 0
    query = "insource:\"pop'n music Lively\""
    while True:
        url = (
            f"{REMYWIKI_API}?action=query&format=json&list=search"
            f"&srsearch={quote(query)}&srlimit=500&srwhat=text"
            f"&sroffset={sroffset}"
        )
        data = http_json(url)
        hits = data.get("query", {}).get("search", []) or []
        if not hits:
            break
        for h in hits:
            t = h.get("title")
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
        nxt = data.get("continue", {}).get("sroffset")
        if nxt is None:
            break
        sroffset = int(nxt)
        time.sleep(rate_sec)
    logger.info("insource search yielded %d lively-related pages", len(titles))
    return titles


def is_song_candidate(title: str) -> bool:
    if title in EXCLUDE_EXACT:
        return False
    return not title.startswith(EXCLUDE_PREFIXES)


def fetch_page_wikitext(api_url: str, title: str) -> str | None:
    url = (
        f"{api_url}?action=parse&format=json&prop=wikitext"
        f"&page={quote(title)}"
    )
    try:
        data = http_json(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("wikitext fetch failed for %s: %s", title, e)
        return None
    text = data.get("parse", {}).get("wikitext", {}).get("*")
    return text


_INFOBOX_PARAM_RE = re.compile(r"\|\s*([a-zA-Z_]+)\s*=\s*([^\n|]+)")
# remywiki 慣例: `Genre: <英字ジャンル名> (<日本語ジャンル名>)<br>` 形式
_GENRE_LINE_RE = re.compile(
    r"Genre:\s*([^\n<(]+?)(?:\s*\(([^)]+)\))?\s*<br>", re.IGNORECASE
)
# remywiki ページタイトル: `= <タイトル> =`
_PAGE_TITLE_RE = re.compile(r"^=\s*([^=\n]+?)\s*=\s*$", re.MULTILINE)


def extract_original_titles(wikitext: str) -> list[str]:
    """wikitext から原タイトル候補を抽出する。

    1. ページ冒頭 H1（`= <title> =`）
    2. Genre 行のかっこ外（英字ジャンル名）とかっこ内（日本語ジャンル名）
    3. Infobox の `|<key>=<value>` パラメータ
    4. 本文先頭太字
    """
    candidates: list[str] = []
    m = _PAGE_TITLE_RE.search(wikitext)
    if m:
        candidates.append(m.group(1).strip())
    for gm in _GENRE_LINE_RE.finditer(wikitext):
        en = gm.group(1).strip()
        ja = (gm.group(2) or "").strip()
        if en:
            candidates.append(en)
        if ja:
            candidates.append(ja)
    for fm in _INFOBOX_PARAM_RE.finditer(wikitext):
        if fm.group(1).lower() in INFOBOX_TITLE_KEYS:
            value = fm.group(2).strip()
            value = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", value)
            value = value.strip()
            if value:
                candidates.append(value)
    bm = re.search(r"'''([^']{1,80})'''", wikitext)
    if bm:
        candidates.append(bm.group(1).strip())
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# `[[Image:<file>|...|<曲名>'s pop'n music banner.]]` の最初の <file> を引く
_BANNER_IMAGE_RE = re.compile(
    r"\[\[(?:Image|File):([^|\]]+)\|[^\]]*?pop'?n\s+music\s+banner",
    re.IGNORECASE,
)


def is_song_page(wikitext: str) -> bool:
    """remywiki の楽曲ページかどうかを判別する。

    楽曲ページには必ず `== Song Information ==`（または `==Song Information==`）
    セクションが存在する。アーティスト・作曲者・楽曲集ページ等の非楽曲ページは
    本セクションが無いため、これで判別する。
    """
    return bool(re.search(r"==\s*Song\s+Information\s*==", wikitext, re.IGNORECASE))


# 楽曲ページの Artist / Composer 行から候補名を抽出する
# 例: "Artist: Orange Lounge<br>" や "Composition/Arrangement: [[Tomosuke Funaki|TOMOSUKE]]<br>"
_ARTIST_LINE_RE = re.compile(
    r"(?:Artist|Composition(?:/Arrangement)?|Vocals?):\s*"
    r"((?:\[\[[^\]]+\]\]|[^<\n])+)\s*<br>",
    re.IGNORECASE,
)


def extract_artist_candidates(wikitext: str) -> list[str]:
    """Artist / Composer / Vocals 行から master 突合用の候補名を抽出する。

    remywiki ページのローマ字読み名だけでは突合困難な楽曲（例: 西新宿清掃曲）
    でも、Artist 名が master.json と一致すれば紐付けできる可能性がある。
    """
    out: list[str] = []
    for m in _ARTIST_LINE_RE.finditer(wikitext):
        value = m.group(1).strip()
        # ウィキリンク [[Foo|Bar]] → Bar / [[Foo]] → Foo の正規化
        value = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", value)
        value = value.strip().rstrip(",.;")
        if value:
            out.append(value)
    return out


# === master.json enrich 機能（v3、--enrich-master オプション） ===
# `{{pnm Chart|pop'n music Lively|EASY|NORMAL|HYPER|EX|BAT_N|BAT_H}}` から
# 各譜面のレベルを抽出する。Lively 行は通常譜面と UPPER 譜面それぞれの
# Chart Header 内に 1 回ずつ出現する（UPPER 譜面ありの場合）。
_PNM_CHART_LIVELY_RE = re.compile(
    r"\{\{\s*pnm\s+Chart\s*\|\s*pop'?n\s+music\s+Lively\s*\|"
    r"\s*([^|\}]*)\|\s*([^|\}]*)\|\s*([^|\}]*)\|\s*([^|\}]*)"
    r"(?:\|\s*([^|\}]*)\|\s*([^|\}]*))?"
    r"\s*\}\}",
    re.IGNORECASE,
)
_PNM_CHART_HEADER_RE = re.compile(r"\{\{\s*pnm\s+Chart\s+Header\b", re.IGNORECASE)
_GENRE_FULL_RE = re.compile(
    r"Genre:\s*([^<\n(]+?)(?:\s*\(\s*([^)]+?)\s*\))?\s*<br>",
    re.IGNORECASE,
)


def _parse_level(text: str) -> int | None:
    """`12` / `↑29` / `&uarr;29` / `-` から数値だけ抽出。

    `-` や空文字や非数字は None。HTML エンティティの装飾矢印を含む値も
    数字列を取り出して整数化する。
    """
    text = text.strip()
    if not text or text in ("-", "?"):
        return None
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def extract_lively_charts(wikitext: str) -> tuple[list[dict], bool]:
    """pop'n music Lively の譜面情報（EASY/NORMAL/HYPER/EX）と UPPER 有無を返す。

    UPPER 譜面の有無は `{{pnm Chart Header}}` テンプレートが 2 回出現することで
    判定する（remywiki の慣例）。Lively 行は通常 Header と UPPER Header に
    1 行ずつ出るため、`_PNM_CHART_LIVELY_RE.findall()` の 1 つ目が通常、
    2 つ目が UPPER と扱う。

    Returns:
        (charts, has_upper)
        charts は normal 4 件 + （UPPER があれば）upper 4 件 のリスト。
        各 chart は ``{"difficulty": str, "is_upper": bool, "level": int|None}``。
    """
    matches = list(_PNM_CHART_LIVELY_RE.finditer(wikitext))
    if not matches:
        return [], False
    header_count = len(_PNM_CHART_HEADER_RE.findall(wikitext))
    has_upper = header_count >= 2 and len(matches) >= 2

    diffs = ("EASY", "NORMAL", "HYPER", "EX")
    out: list[dict] = []
    # 通常譜面（1 行目）
    m = matches[0]
    for diff, idx in zip(diffs, range(1, 5), strict=True):
        out.append({
            "difficulty": diff,
            "is_upper": False,
            "level": _parse_level(m.group(idx) or ""),
        })
    if has_upper:
        m = matches[1]
        for diff, idx in zip(diffs, range(1, 5), strict=True):
            out.append({
                "difficulty": diff,
                "is_upper": True,
                "level": _parse_level(m.group(idx) or ""),
            })
    return out, has_upper


def extract_genre_pair(wikitext: str) -> tuple[str | None, str | None]:
    """Genre 行から (英字ジャンル名, 日本語ジャンル名) のタプルを返す。"""
    m = _GENRE_FULL_RE.search(wikitext)
    if not m:
        return None, None
    en = (m.group(1) or "").strip() or None
    ja = (m.group(2) or "").strip() or None
    return en, ja


def find_banner_file_in_wikitext(wikitext: str) -> str | None:
    """wikitext からバナー画像ファイル名を抽出する。

    優先順:
    1. キャプションに「pop'n music banner」を含む `[[Image:...]]`／`[[File:...]]`
    2. Infobox `|banner = <file>` パラメータ
    3. `[[File:BN_<...>]]` / `[[Image:BN_<...>]]`
    """
    m = _BANNER_IMAGE_RE.search(wikitext)
    if m:
        return m.group(1).strip()
    for pm in _INFOBOX_PARAM_RE.finditer(wikitext):
        if pm.group(1).lower() == "banner":
            value = pm.group(2).strip()
            value = re.sub(r"^File:", "", value, flags=re.IGNORECASE)
            if value:
                return value
    m = re.search(r"\[\[(?:Image|File):(BN[_\s][^\]\|]+)", wikitext)
    if m:
        return m.group(1).strip()
    return None


def fetch_image_url(api_url: str, file_title: str) -> str | None:
    title = file_title if file_title.lower().startswith("file:") else f"File:{file_title}"
    url = (
        f"{api_url}?action=query&format=json&prop=imageinfo&iiprop=url"
        f"&titles={quote(title)}"
    )
    try:
        data = http_json(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("imageinfo fetch failed for %s: %s", file_title, e)
        return None
    pages = data.get("query", {}).get("pages", {}) or {}
    for _, p in pages.items():
        infos = p.get("imageinfo") or []
        if infos:
            return infos[0].get("url")
    return None


def safe_filename(title: str) -> str:
    name = re.sub(r"^File:", "", title, flags=re.IGNORECASE)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.replace(" ", "_")


def download_image(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        logger.debug("cache hit: %s", dest.name)
        return True
    try:
        data = http_bytes(url)
        dest.write_bytes(data)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("download failed: %s — %s", url, e)
        return False


def compute_hashes(image_path: Path) -> tuple[int, int] | None:
    data = np.fromfile(str(image_path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        logger.warning("decode failed: %s", image_path)
        return None
    resized = cv2.resize(img, DEFAULT_TARGET_SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return phash64(gray), dhash64(gray)


def match_to_master(
    candidates: list[str],
    master_songs: list[dict],
    score_cutoff: int = 85,
    artist_candidates: list[str] | None = None,
) -> tuple[dict, int] | None:
    """master.json のタイトルおよび（任意で）アーティストに対し fuzzy 突合する。

    タイトル系候補と artist 系候補で `master_songs` をスキャンし、最高スコアを
    返す。タイトル直一致を優先し、artist 突合は補助的に扱う（score-2 のペナルティ）。
    """
    from rapidfuzz import fuzz, process

    titles = [s["title"] for s in master_songs]
    best_song: dict | None = None
    best_score = 0
    for cand in candidates:
        result = process.extractOne(
            cand, titles, scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )
        if result and result[1] > best_score:
            _matched, score, idx = result
            best_song = master_songs[idx]
            best_score = int(score)
    # artist 突合（あれば）。タイトルでヒット済みでもより高ければ更新するが、
    # 同一スコアでの上書きは避けるためペナルティ -2 を引いて優先順位を下げる。
    if artist_candidates:
        artists = [s.get("artist", "") or "" for s in master_songs]
        for cand in artist_candidates:
            if not cand:
                continue
            result = process.extractOne(
                cand, artists, scorer=fuzz.WRatio,
                score_cutoff=max(score_cutoff, 90),
            )
            if result:
                _matched, score, idx = result
                adjusted = int(score) - 2
                if adjusted > best_score:
                    best_song = master_songs[idx]
                    best_score = adjusted
    if best_song is None:
        return None
    return best_song, best_score


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--master-json", required=True, type=Path)
    p.add_argument("--cache-dir", type=Path, default=Path("livelyrec_data/banners_ref"))
    p.add_argument("--out", type=Path, default=Path("data/banner_features.json"))
    p.add_argument("--unmatched-csv", type=Path, default=Path("data/banner_features.unmatched.csv"))
    p.add_argument("--rate-sec", type=float, default=1.0)
    p.add_argument("--limit", type=int, default=0, help="0=全件、>0 で件数制限")
    p.add_argument(
        "--score-cutoff", type=int, default=85,
        help="rapidfuzz WRatio の閾値（v2 既定 85、ローマ字読み楽曲を救うため緩和）",
    )
    p.add_argument(
        "--enrich-master", action="store_true",
        help="マッチした楽曲ページの wikitext から Lively 譜面レベル・ジャンル名・"
             "UPPER 譜面有無を抽出し、`--master-json` を上書き更新する（v3、開発者ツール）",
    )
    p.add_argument(
        "--master-out", type=Path, default=None,
        help="--enrich-master 時の出力先（既定: --master-json と同じパスへ上書き）",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    master_doc = json.loads(args.master_json.read_text(encoding="utf-8"))
    master_songs = master_doc.get("songs", [])
    logger.info("master songs: %d", len(master_songs))

    # --enrich-master 用の集計カウンタ
    enrich_stats = {"genre": 0, "charts": 0, "upper": 0}
    if args.enrich_master:
        logger.info("master enrich mode ON (genre/charts/upper を Wiki から補完)")

    logger.info("fetching links from %d source pages...", len(LIVELY_SOURCE_PAGES))
    link_titles = fetch_lively_page_links(rate_sec=args.rate_sec)
    logger.info("source pages: %d raw links", len(link_titles))
    # v4: 起点ページに含まれない楽曲（他機種初出など）を救うため、
    # wikitext 検索 `insource:"pop'n music Lively"` の結果と和集合を取る
    logger.info("fetching lively pages via wikitext search...")
    search_titles = fetch_lively_songs_by_search(rate_sec=args.rate_sec)
    seen_all: set[str] = set()
    merged: list[str] = []
    for t in (*link_titles, *search_titles):
        if t not in seen_all:
            seen_all.add(t)
            merged.append(t)
    logger.info(
        "merged source: %d unique pages (links=%d + search=%d)",
        len(merged), len(link_titles), len(search_titles),
    )
    candidates = [t for t in merged if is_song_candidate(t)]
    logger.info(
        "candidates: %d (after meta-link filter, from %d merged)",
        len(candidates), len(merged),
    )
    if args.limit > 0:
        candidates = candidates[: args.limit]
    logger.info("song candidates: %d", len(candidates))

    features: list[dict] = []
    unmatched: list[tuple[str, str, int]] = []
    skipped_non_song = 0
    seen_song_ids: set[str] = set()

    for i, page_title in enumerate(candidates, start=1):
        logger.info("[%d/%d] %s", i, len(candidates), page_title)

        wikitext = fetch_page_wikitext(REMYWIKI_API, page_title)
        time.sleep(args.rate_sec)
        if not wikitext:
            # 楽曲ページかどうか判別できないため未マッチ扱い（多くはアーティスト系）
            unmatched.append((page_title, "wikitext-missing", 0))
            continue

        # 改善 A（v2）: 楽曲ページ判別。`== Song Information ==` セクション
        # が無いページ（アーティスト・作曲者・楽曲集ページ等）は未マッチではなく
        # 「楽曲ページではない」として静かにスキップする。
        if not is_song_page(wikitext):
            skipped_non_song += 1
            logger.debug("  skipped (non-song page): %s", page_title)
            continue

        title_candidates = extract_original_titles(wikitext)
        title_candidates.insert(0, page_title)
        artist_candidates = extract_artist_candidates(wikitext)
        match = match_to_master(
            title_candidates, master_songs, args.score_cutoff,
            artist_candidates=artist_candidates,
        )
        if match is None:
            reason = "titles=" + ";".join(title_candidates[:3])
            if artist_candidates:
                reason += " / artists=" + ";".join(artist_candidates[:3])
            unmatched.append((page_title, reason, 0))
            continue
        song, match_score = match

        if song["song_id"] in seen_song_ids:
            logger.debug("duplicate song_id skipped: %s", song["song_id"])
            continue

        banner_file = find_banner_file_in_wikitext(wikitext)
        if not banner_file:
            unmatched.append((page_title, f"no-banner;matched={song['title']}", match_score))
            continue

        image_url = fetch_image_url(REMYWIKI_API, banner_file)
        time.sleep(args.rate_sec)
        if not image_url:
            unmatched.append((page_title, f"no-image-url;file={banner_file}", match_score))
            continue

        cache_path = args.cache_dir / "remywiki" / safe_filename(banner_file)
        if not download_image(image_url, cache_path):
            unmatched.append((page_title, f"dl-failed;file={banner_file}", match_score))
            continue
        time.sleep(args.rate_sec)

        hashes = compute_hashes(cache_path)
        if hashes is None:
            unmatched.append((page_title, f"hash-failed;file={banner_file}", match_score))
            continue
        ph, dh = hashes

        features.append(
            {
                "song_id": song["song_id"],
                "phash": hex_from_hash(ph),
                "dhash": hex_from_hash(dh),
                "src": [f"remywiki:File:{banner_file}"],
            }
        )
        seen_song_ids.add(song["song_id"])
        logger.info(
            "  ✓ matched=%s score=%d phash=%s",
            song["title"],
            match_score,
            hex_from_hash(ph),
        )

        # --enrich-master: 同じ wikitext から master 拡張情報を抽出して反映
        if args.enrich_master:
            genre_en, genre_jp = extract_genre_pair(wikitext)
            new_charts, has_upper = extract_lively_charts(wikitext)
            if genre_en or genre_jp:
                # 既存値より新規取得値を優先（再生成時は最新）
                song["genre"] = genre_en or song.get("genre")
                if genre_jp:
                    song["genre_jp"] = genre_jp
                enrich_stats["genre"] += 1
            if new_charts:
                song["charts"] = new_charts
                enrich_stats["charts"] += 1
            if has_upper:
                song["has_upper"] = True
                enrich_stats["upper"] += 1

    # 出力
    out_doc = {
        "version": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "remywiki.com (CS_pnm_Lively)",
        "schema_version": 1,
        "target_size": list(DEFAULT_TARGET_SIZE),
        "songs": features,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "wrote %d features to %s (skipped %d non-song pages)",
        len(features), args.out, skipped_non_song,
    )

    if unmatched:
        args.unmatched_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.unmatched_csv.open("w", encoding="utf-8") as f:
            f.write("wiki_page,reason,match_score\n")
            for page, reason, score in unmatched:
                # 簡易 CSV エスケープ
                page_e = page.replace('"', '""')
                reason_e = reason.replace('"', '""')
                f.write(f'"{page_e}","{reason_e}",{score}\n')
        logger.info("wrote %d unmatched entries to %s", len(unmatched), args.unmatched_csv)

    # --enrich-master: master.json を保存
    if args.enrich_master:
        out_path = args.master_out or args.master_json
        master_doc["version"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(master_doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "enriched master saved to %s "
            "(genre=%d, charts=%d, upper=%d)",
            out_path,
            enrich_stats["genre"], enrich_stats["charts"], enrich_stats["upper"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
