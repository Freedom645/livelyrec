"""PoC #04: バナー画像収集スクリプト

詳細: docs/design/poc/04_banner_recognition.md §4.1

MediaWiki API を用いて、以下サイトの「pop'n music バナー」カテゴリから
画像ファイル一覧とダウンロード URL を取得し、ローカルに保存する。

- remywiki.com  (Category:Pop'n_music_Banners)
- popnmusic.fandom.com (Category:Song_Banners)

レート制御 (既定 1.0 秒/req) を守り、UA を明示する。

使用例:
  python scripts/poc/banner_collect.py --site remywiki --limit 20 --out-dir ./poc_out
  python scripts/poc/banner_collect.py --site fandom   --limit 20 --out-dir ./poc_out

設計方針:
- 画像本体はユーザ PC のローカル保存のみ。アプリ同梱は特徴量のみ (FR-DEV-002 §3.3)。
- 失敗は WARN ログで継続。1 件失敗で全体停止はしない。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger("banner_collect")

DEFAULT_USER_AGENT = "LivelyRec-PoC/0.1 (banner-recognition research; +https://github.com/Freedom645/livelyrec)"


@dataclass(frozen=True)
class SiteConfig:
    name: str
    api_url: str
    category: str

    @property
    def slug(self) -> str:
        return self.name.replace(" ", "_")


SITES: dict[str, SiteConfig] = {
    "remywiki": SiteConfig(
        name="remywiki",
        api_url="https://remywiki.com/api.php",
        category="Category:Pop'n_music_Banners",
    ),
    "fandom": SiteConfig(
        name="fandom",
        api_url="https://popnmusic.fandom.com/api.php",
        category="Category:Song_Banners",
    ),
}


def http_get_json(url: str, user_agent: str, timeout: float = 15.0) -> dict:
    req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def http_get_bytes(url: str, user_agent: str, timeout: float = 30.0) -> bytes:
    req = Request(url, headers={"User-Agent": user_agent})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_category_files(
    site: SiteConfig,
    *,
    user_agent: str,
    limit: int,
    rate_sec: float,
) -> list[str]:
    """カテゴリ内の File: タイトル一覧を取得"""
    titles: list[str] = []
    cont: str | None = None
    while len(titles) < limit:
        params = [
            "action=query",
            "format=json",
            "list=categorymembers",
            f"cmtitle={quote(site.category)}",
            "cmtype=file",
            "cmlimit=200",
        ]
        if cont:
            params.append(f"cmcontinue={quote(cont)}")
        url = f"{site.api_url}?{'&'.join(params)}"
        data = http_get_json(url, user_agent)
        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            titles.append(m["title"])
            if len(titles) >= limit:
                break
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        time.sleep(rate_sec)
    return titles


def get_image_urls(
    site: SiteConfig,
    file_titles: list[str],
    *,
    user_agent: str,
    rate_sec: float,
) -> dict[str, str]:
    """File:Foo.png のリスト → 直 URL の dict"""
    out: dict[str, str] = {}
    for i in range(0, len(file_titles), 50):
        batch = file_titles[i : i + 50]
        joined = "|".join(quote(t, safe="") for t in batch)
        url = (
            f"{site.api_url}?action=query&format=json&prop=imageinfo"
            f"&iiprop=url&titles={joined}"
        )
        data = http_get_json(url, user_agent)
        pages = data.get("query", {}).get("pages", {}) or {}
        for _, page in pages.items():
            title = page.get("title")
            infos = page.get("imageinfo") or []
            if not title or not infos:
                continue
            file_url = infos[0].get("url")
            if file_url:
                out[title] = file_url
        time.sleep(rate_sec)
    return out


def safe_filename(title: str) -> str:
    """File:Foo bar.png → Foo_bar.png（簡易サニタイズ）"""
    name = title.split(":", 1)[-1]
    bad = '\\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.replace(" ", "_")


def download_images(
    url_map: dict[str, str],
    out_dir: Path,
    *,
    user_agent: str,
    rate_sec: float,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for title, url in url_map.items():
        fname = safe_filename(title)
        path = out_dir / fname
        if path.exists():
            logger.info("skip existing: %s", path.name)
            saved.append(path)
            continue
        try:
            data = http_get_bytes(url, user_agent)
            path.write_bytes(data)
            saved.append(path)
            logger.info("saved: %s (%d bytes)", path.name, len(data))
        except Exception as e:  # noqa: BLE001 - PoC では幅広く拾う
            logger.warning("download failed: %s — %s", title, e)
        time.sleep(rate_sec)
    return saved


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", choices=list(SITES.keys()), required=True)
    p.add_argument("--limit", type=int, default=20, help="取得最大件数")
    p.add_argument("--rate-sec", type=float, default=1.0, help="リクエスト間隔(秒)")
    p.add_argument("--out-dir", type=Path, default=Path("./poc_out/banners_ref"))
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--dry-run", action="store_true", help="一覧取得のみ。DL しない")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    site = SITES[args.site]
    out_dir = args.out_dir / site.slug
    logger.info("site=%s category=%s limit=%d", site.name, site.category, args.limit)

    titles = list_category_files(
        site, user_agent=args.user_agent, limit=args.limit, rate_sec=args.rate_sec
    )
    logger.info("listed %d files", len(titles))
    if not titles:
        logger.warning("no files returned")
        return 1

    url_map = get_image_urls(
        site, titles, user_agent=args.user_agent, rate_sec=args.rate_sec
    )
    logger.info("resolved %d image urls", len(url_map))

    index = {
        "site": site.name,
        "category": site.category,
        "count": len(url_map),
        "items": [{"title": t, "url": u} for t, u in url_map.items()],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "_index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("wrote index: %s", index_path)

    if args.dry_run:
        logger.info("dry-run: skip download")
        return 0

    saved = download_images(
        url_map, out_dir, user_agent=args.user_agent, rate_sec=args.rate_sec
    )
    logger.info("saved %d files to %s", len(saved), out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
