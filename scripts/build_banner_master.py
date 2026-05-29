"""バナー特徴量マスタ JSON 生成スクリプト（FR-BAN-003, FR-BAN-011, v2.0）。

詳細: docs/design/11_詳細設計_バナー認識.md §4

remywiki.com および popnmusic.fandom.com の各楽曲ページから:

1. CS_pnm_Lively ページの楽曲ページリンクを抽出
2. 各曲ページ wikitext を MediaWiki API で取得
3. Infobox から **原タイトル（Japanese title）** を抽出
4. master.json と rapidfuzz マッチで突合
5. 画像 URL を取得 → ローカルキャッシュ DL
6. 390×94 リサイズ正規化 → pHash/dHash 計算
7. data/banner_features.json 出力

画像本体はユーザ PC ローカルキャッシュのみ保存し、配布物（リポジトリ・
PyInstaller 出力）には含めない（NFR-LEGAL-001 / 005）。

Usage:
    python scripts/build_banner_master.py \\
        --master-json data/master.json \\
        --cache-dir livelyrec_data/banners_ref \\
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
LIVELY_PAGE = "CS_pnm_Lively"

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


def fetch_lively_page_links(rate_sec: float) -> list[str]:
    """CS_pnm_Lively ページの全リンクを取得する。"""
    titles: list[str] = []
    plcontinue: str | None = None
    while True:
        url = (
            f"{REMYWIKI_API}?action=query&format=json&prop=links"
            f"&titles={quote(LIVELY_PAGE)}&pllimit=500"
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
    score_cutoff: int = 95,
) -> tuple[dict, int] | None:
    from rapidfuzz import fuzz, process

    titles = [s["title"] for s in master_songs]
    best_song = None
    best_score = 0
    for cand in candidates:
        result = process.extractOne(
            cand, titles, scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )
        if result and result[1] > best_score:
            matched_title, score, idx = result
            best_song = master_songs[idx]
            best_score = int(score)
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
    p.add_argument("--score-cutoff", type=int, default=95)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    master_doc = json.loads(args.master_json.read_text(encoding="utf-8"))
    master_songs = master_doc.get("songs", [])
    logger.info("master songs: %d", len(master_songs))

    logger.info("fetching CS_pnm_Lively page links...")
    all_titles = fetch_lively_page_links(rate_sec=args.rate_sec)
    candidates = [t for t in all_titles if is_song_candidate(t)]
    if args.limit > 0:
        candidates = candidates[: args.limit]
    logger.info("song candidates: %d", len(candidates))

    features: list[dict] = []
    unmatched: list[tuple[str, str, int]] = []
    seen_song_ids: set[str] = set()

    for i, page_title in enumerate(candidates, start=1):
        logger.info("[%d/%d] %s", i, len(candidates), page_title)

        wikitext = fetch_page_wikitext(REMYWIKI_API, page_title)
        time.sleep(args.rate_sec)
        if not wikitext:
            unmatched.append((page_title, "wikitext-missing", 0))
            continue

        title_candidates = extract_original_titles(wikitext)
        title_candidates.insert(0, page_title)
        match = match_to_master(title_candidates, master_songs, args.score_cutoff)
        if match is None:
            unmatched.append((page_title, ";".join(title_candidates[:3]), 0))
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
    logger.info("wrote %d features to %s", len(features), args.out)

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

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
