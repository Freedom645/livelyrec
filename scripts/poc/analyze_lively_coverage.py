"""CS_pnm_Lively ページのリンクから lively 楽曲候補を抽出し、master.json と突合する。

詳細: docs/design/poc/04_banner_recognition.md 関連
PoC 追加調査（2026-05-29）

remywiki の CS_pnm_Lively ページにある全リンクから:
- AC/CS pnm シリーズページ・カテゴリ等のメタリンクを除外
- 残ったリンクを「楽曲タイトル候補」とみなす
- 各候補について、ローマ字読みのページ名と master.json の `title` / `title_norm` を rapidfuzz で照合
- 結果サマリと差分一覧を出力

注意: remywiki は楽曲ページ名がローマ字読み（例: 'Nishi-Shinjuku seisou kyoku'）であり、
master.json の公式表記（例: '西新宿清掃曲'）とは直接照合できないため、
個別ページの Song Information テーブルから原タイトルを取る必要がある（本スクリプトは概況のみ）。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from rapidfuzz import fuzz as rf_fuzz
    from rapidfuzz import process as rf_process
except ImportError:  # pragma: no cover
    rf_process = None
    rf_fuzz = None

logger = logging.getLogger("analyze_lively_coverage")

UA = "LivelyRec-PoC/0.1 (research)"

# 除外パターン: シリーズページ・カテゴリ・特殊ページ
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
)
EXCLUDE_EXACT = {
    "Main Page", "Konami", "BEMANI", "DanceDanceRevolution",
    "GuitarFreaks", "DrumMania", "GITADORA", "jubeat", "REFLEC BEAT",
    "SOUND VOLTEX", "beatmania", "beatmania IIDX", "DANCERUSH STARDOM",
    "NOSTALGIA",
}


def fetch_page_links(title: str) -> list[str]:
    url_base = (
        "https://remywiki.com/api.php?action=query&format=json&prop=links"
        f"&titles={quote(title)}&pllimit=500"
    )
    all_links: list[str] = []
    plcontinue: str | None = None
    while True:
        url = url_base + (f"&plcontinue={quote(plcontinue)}" if plcontinue else "")
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {}) or {}
        for _, p in pages.items():
            for link in p.get("links", []) or []:
                all_links.append(link["title"])
        plcontinue = data.get("continue", {}).get("plcontinue")
        if not plcontinue:
            break
        time.sleep(1.0)
    return all_links


def is_song_candidate(title: str) -> bool:
    if title in EXCLUDE_EXACT:
        return False
    return not title.startswith(EXCLUDE_PREFIXES)


def normalize_for_compare(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[\s\-_()（）「」『』,\.!?'\"]+", "", s)
    return s


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--master-json", default="data/master.json")
    p.add_argument("--lively-page", default="CS_pnm_Lively")
    p.add_argument("--out", default="poc_out/lively_coverage.json")
    p.add_argument("--score-cutoff", type=int, default=85)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    logger.info("fetching links from %s", args.lively_page)
    all_links = fetch_page_links(args.lively_page)
    logger.info("got %d links total", len(all_links))

    candidates = [t for t in all_links if is_song_candidate(t)]
    logger.info("song candidates: %d", len(candidates))

    with open(args.master_json, encoding="utf-8") as f:
        master_doc = json.load(f)
    master_songs = master_doc["songs"]
    logger.info("master songs: %d", len(master_songs))

    # rapidfuzz で各 Wiki 候補が master.json にマッチするか
    titles = [m["title"] for m in master_songs]
    title_norms = [m["title_norm"] for m in master_songs]

    matched: list[dict] = []
    unmatched_wiki: list[str] = []
    for wiki_title in candidates:
        q_norm = normalize_for_compare(wiki_title)
        # 公式タイトル直マッチ
        r1 = rf_process.extractOne(
            wiki_title, titles, scorer=rf_fuzz.WRatio, score_cutoff=args.score_cutoff
        )
        # title_norm でも試す
        r2 = rf_process.extractOne(
            q_norm, title_norms, scorer=rf_fuzz.WRatio, score_cutoff=args.score_cutoff
        )
        best = None
        if r1 and r2:
            best = r1 if r1[1] >= r2[1] else (titles[r2[2]], r2[1], r2[2])
        elif r1:
            best = r1
        elif r2:
            best = (titles[r2[2]], r2[1], r2[2])
        if best:
            matched.append({"wiki": wiki_title, "master": best[0], "score": int(best[1])})
        else:
            unmatched_wiki.append(wiki_title)

    matched_master_titles = {m["master"] for m in matched}
    unmatched_master = [t for t in titles if t not in matched_master_titles]

    summary = {
        "wiki_page": args.lively_page,
        "wiki_links_total": len(all_links),
        "wiki_song_candidates": len(candidates),
        "master_songs": len(master_songs),
        "matched": len(matched),
        "unmatched_wiki_count": len(unmatched_wiki),
        "unmatched_master_count": len(unmatched_master),
        "coverage_master_pct": round(100 * len(matched) / max(1, len(master_songs)), 1),
        "coverage_wiki_pct": round(100 * len(matched) / max(1, len(candidates)), 1),
        "score_cutoff": args.score_cutoff,
    }
    out_doc = {
        "summary": summary,
        "matched_examples": matched[:20],
        "unmatched_wiki_examples": unmatched_wiki[:30],
        "unmatched_master_examples": unmatched_master[:30],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("wrote %s", out_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
