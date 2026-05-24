"""network 補助関数のテスト。"""

from __future__ import annotations

import socket

import pytest

from livelyrec.shared import network

# ---- resolve_advertised_host: 純粋ロジック ----

def test_advertised_host_returns_setting_when_lan_publish_off() -> None:
    # lan_publish=False のときは設定値をそのまま返す
    assert network.resolve_advertised_host("127.0.0.1", False) == "127.0.0.1"
    assert network.resolve_advertised_host("192.168.1.10", False) == "192.168.1.10"


@pytest.mark.parametrize("loopback", ["", "0.0.0.0", "127.0.0.1", "localhost"])
def test_advertised_host_resolves_lan_ip_for_loopback(
    monkeypatch: pytest.MonkeyPatch, loopback: str
) -> None:
    # lan_publish=True かつ host が loopback / 0.0.0.0 のとき LAN IP に置換する
    monkeypatch.setattr(network, "get_lan_ip", lambda fallback="127.0.0.1": "192.168.0.42")
    assert network.resolve_advertised_host(loopback, True) == "192.168.0.42"


def test_advertised_host_keeps_explicit_host_when_lan_publish_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ユーザが明示的に IP/ホスト名を指定している場合はそれを優先（LAN IP 取得しない）
    called = {"v": False}

    def _spy(fallback: str = "127.0.0.1") -> str:
        called["v"] = True
        return "should-not-be-used"

    monkeypatch.setattr(network, "get_lan_ip", _spy)
    assert network.resolve_advertised_host("10.0.0.5", True) == "10.0.0.5"
    assert called["v"] is False


# ---- get_lan_ip: socket をモック化 ----

class _FakeSocket:
    def __init__(self, getsockname_ret=("192.168.1.50", 0), raise_on_connect=False):
        self._ret = getsockname_ret
        self._raise = raise_on_connect

    def connect(self, _addr):
        if self._raise:
            raise OSError("no route")

    def getsockname(self):
        return self._ret

    def close(self):
        return None


def test_get_lan_ip_uses_udp_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeSocket())
    assert network.get_lan_ip() == "192.168.1.50"


def test_get_lan_ip_falls_back_to_hostname_when_udp_yields_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(getsockname_ret=("127.0.0.1", 0))
    )
    monkeypatch.setattr(socket, "gethostname", lambda: "myhost")
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "192.168.10.20")
    assert network.get_lan_ip() == "192.168.10.20"


def test_get_lan_ip_returns_fallback_when_all_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(raise_on_connect=True)
    )

    def _raise_oserror(_):
        raise OSError("no host")

    monkeypatch.setattr(socket, "gethostname", lambda: "myhost")
    monkeypatch.setattr(socket, "gethostbyname", _raise_oserror)
    assert network.get_lan_ip(fallback="127.0.0.1") == "127.0.0.1"
