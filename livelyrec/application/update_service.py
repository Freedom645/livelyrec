"""自動アップデート確認サービス。

詳細: docs/design/05_基本設計書.md §9.5
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

from livelyrec.infrastructure.github_client import GitHubClient, ReleaseInfo
from livelyrec.shared.exceptions import UpdateCheckError

logger = logging.getLogger("livelyrec.update")


@dataclass(frozen=True)
class UpdateCheckResult:
    has_update: bool
    latest: ReleaseInfo | None
    current_version: str
    error: str | None = None


class UpdateService:
    def __init__(self, client: GitHubClient, current_version: str) -> None:
        self._client = client
        self._current = current_version

    def check(self) -> UpdateCheckResult:
        try:
            latest = self._client.get_latest_release()
        except UpdateCheckError as e:
            return UpdateCheckResult(False, None, self._current, str(e))
        has_update = _is_newer(latest.tag_name, self._current)
        return UpdateCheckResult(has_update=has_update, latest=latest, current_version=self._current)

    def check_async(self, on_done) -> None:
        def _runner() -> None:
            result = self.check()
            try:
                on_done(result)
            except Exception:
                logger.exception("update on_done handler failed")
        threading.Thread(target=_runner, name="update-check", daemon=True).start()


_VER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _parse_version(s: str) -> tuple[int, int, int] | None:
    m = _VER_RE.match(s or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def _is_newer(remote: str, current: str) -> bool:
    r = _parse_version(remote)
    c = _parse_version(current)
    if r is None or c is None:
        return False
    return r > c
