"""UpdateService のテスト。"""

from __future__ import annotations

import threading

import pytest

from livelyrec.application.update_service import (
    UpdateService,
    _is_newer,
    _parse_version,
)
from livelyrec.infrastructure.github_client import ReleaseInfo
from livelyrec.shared.exceptions import UpdateCheckError


@pytest.mark.parametrize(
    "remote, current, expected",
    [
        ("v1.2.3", "1.2.2", True),
        ("1.2.3", "v1.2.3", False),
        ("1.2.3", "1.2.4", False),
        ("2.0.0", "1.9.9", True),
        ("invalid", "1.0.0", False),
        ("1.0.0", "invalid", False),
    ],
)
def test_is_newer(remote: str, current: str, expected: bool) -> None:
    assert _is_newer(remote, current) is expected


def test_parse_version_handles_prefix() -> None:
    assert _parse_version("v1.2.3") == (1, 2, 3)
    assert _parse_version("1.2.3") == (1, 2, 3)
    assert _parse_version("garbage") is None


class _FakeGitHubClient:
    """get_latest_release が固定の結果／例外を返すフェイク。"""

    def __init__(self, release: ReleaseInfo | None = None, error: Exception | None = None) -> None:
        self._release = release
        self._error = error

    def get_latest_release(self) -> ReleaseInfo:
        if self._error is not None:
            raise self._error
        assert self._release is not None
        return self._release


def _release(tag: str = "v2.0.0") -> ReleaseInfo:
    return ReleaseInfo(tag_name=tag, name="release", html_url="https://example/r", assets=[])


def test_check_detects_newer_release() -> None:
    svc = UpdateService(_FakeGitHubClient(release=_release("v2.0.0")), "1.0.0")
    result = svc.check()
    assert result.has_update is True
    assert result.latest is not None
    assert result.latest.tag_name == "v2.0.0"
    assert result.error is None


def test_check_no_update_for_same_version() -> None:
    svc = UpdateService(_FakeGitHubClient(release=_release("v1.0.0")), "1.0.0")
    assert svc.check().has_update is False


def test_check_handles_fetch_error() -> None:
    svc = UpdateService(_FakeGitHubClient(error=UpdateCheckError("network down")), "1.0.0")
    result = svc.check()
    assert result.has_update is False
    assert result.latest is None
    assert result.error is not None and "network down" in result.error


def test_check_async_invokes_callback() -> None:
    svc = UpdateService(_FakeGitHubClient(release=_release("v3.1.0")), "1.0.0")
    done = threading.Event()
    captured: list = []

    def on_done(result) -> None:
        captured.append(result)
        done.set()

    svc.check_async(on_done)
    assert done.wait(timeout=5.0)
    assert captured[0].has_update is True
