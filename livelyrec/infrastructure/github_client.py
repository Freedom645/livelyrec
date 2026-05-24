"""GitHub Releases / Pages クライアント。

詳細: docs/design/08_詳細設計_API設計.md §5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from livelyrec.shared.exceptions import MasterFetchError, UpdateCheckError

logger = logging.getLogger("livelyrec.github")


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    name: str
    html_url: str
    assets: list[dict]


class GitHubClient:
    """GitHub Releases API ラッパ。"""

    def __init__(self, owner: str, repo: str, user_agent: str = "LivelyRec") -> None:
        self._owner = owner
        self._repo = repo
        self._ua = user_agent

    def get_latest_release(self, timeout: float = 10.0) -> ReleaseInfo:
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/releases/latest"
        try:
            resp = requests.get(
                url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": self._ua},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise UpdateCheckError(f"failed to fetch latest release: {e}") from e
        return ReleaseInfo(
            tag_name=data.get("tag_name", ""),
            name=data.get("name", ""),
            html_url=data.get("html_url", ""),
            assets=data.get("assets", []) or [],
        )

    def download_asset(
        self,
        download_url: str,
        out_path: Path,
        timeout: float = 60.0,
    ) -> None:
        try:
            with requests.get(
                download_url,
                stream=True,
                timeout=timeout,
                headers={"User-Agent": self._ua},
            ) as resp:
                resp.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with out_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
        except Exception as e:
            raise UpdateCheckError(f"failed to download asset: {e}") from e


class MasterFetcher:
    """マスタ JSON を GitHub Pages 等から取得する。ETag キャッシュ対応。"""

    def __init__(
        self,
        endpoint_url: str,
        cache_path: Path,
        user_agent: str = "LivelyRec",
    ) -> None:
        self._url = endpoint_url
        self._cache_path = cache_path
        self._etag_path = cache_path.with_suffix(cache_path.suffix + ".etag")
        self._ua = user_agent

    def fetch(self, timeout: float = 30.0) -> dict:
        """マスタ JSON を取得する。失敗時はキャッシュ、それもなければ例外。"""
        headers = {"User-Agent": self._ua}
        if self._etag_path.exists():
            try:
                headers["If-None-Match"] = self._etag_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        try:
            resp = requests.get(self._url, headers=headers, timeout=timeout)
        except Exception as e:
            logger.warning("master fetch failed: %s", e)
            return self._load_cache_or_raise(e)
        if resp.status_code == 304 and self._cache_path.exists():
            logger.info("master not modified (304), using cache")
            return self._load_cache_or_raise(MasterFetchError("304 but no cache"))
        if not resp.ok:
            return self._load_cache_or_raise(
                MasterFetchError(f"HTTP {resp.status_code}")
            )
        try:
            data = resp.json()
        except ValueError as e:
            return self._load_cache_or_raise(e)
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                resp.text, encoding="utf-8"
            )
            etag = resp.headers.get("ETag")
            if etag:
                self._etag_path.write_text(etag, encoding="utf-8")
        except OSError as e:
            logger.warning("failed to write master cache: %s", e)
        return data

    def _load_cache_or_raise(self, original_error: Exception) -> dict:
        if self._cache_path.exists():
            try:
                import json
                return json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        raise MasterFetchError(str(original_error)) from original_error
