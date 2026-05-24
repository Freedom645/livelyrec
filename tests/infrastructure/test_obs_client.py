"""OBSClient（obs-websocket-py 同期ラッパ）のテスト。

実 OBS は使わず obsws をフェイクに差し替え、リクエスト分類・エラー
ハンドリングを検証する。実 OBS との疎通検証は結合テスト区分B。
"""

from __future__ import annotations

import base64

import pytest
from obswebsocket import exceptions as obs_exc

from livelyrec.infrastructure.obs_client import (
    OBSClient,
    ObsConfig,
    _classify_connect_error,
)
from livelyrec.shared.exceptions import (
    ObsAuthError,
    ObsConfigurationError,
    ObsConnectionError,
    ObsRequestError,
    ObsTimeoutError,
)


class _FakeResponse:
    def __init__(self, status: bool = True, datain: dict | None = None) -> None:
        self.status = status
        self.datain = datain or {}


class _FakeWs:
    """obsws の最小フェイク。request.name でレスポンスを引く。"""

    def __init__(
        self,
        responses: dict | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = responses or {}
        self._raise = raise_exc
        self.disconnected = False

    def call(self, request):
        if self._raise is not None:
            raise self._raise
        return self._responses.get(request.name, _FakeResponse())

    def disconnect(self) -> None:
        self.disconnected = True


def _client(ws: _FakeWs, source_name: str = "src") -> OBSClient:
    client = OBSClient(ObsConfig(source_name=source_name))
    client._ws = ws
    client._connected = True
    return client


# ---- 接続エラー分類 ----

@pytest.mark.parametrize(
    "message, exc_type",
    [
        ("authentication failed", ObsAuthError),
        ("wrong password provided", ObsAuthError),
        ("connection timed out", ObsTimeoutError),
        ("connection refused", ObsConnectionError),
    ],
)
def test_classify_connect_error(message: str, exc_type: type) -> None:
    assert isinstance(_classify_connect_error(Exception(message)), exc_type)


# ---- get_source_screenshot_png ----

def test_screenshot_unconfigured_source_raises_configuration_error() -> None:
    client = OBSClient(ObsConfig(source_name=""))
    with pytest.raises(ObsConfigurationError):
        client.get_source_screenshot_png()


def test_screenshot_success_returns_bytes() -> None:
    raw = b"fake-png-bytes"
    b64 = base64.b64encode(raw).decode()
    ws = _FakeWs({"GetSourceScreenshot": _FakeResponse(True, {"imageData": b64})})
    assert _client(ws).get_source_screenshot_png() == raw


def test_screenshot_strips_data_uri_prefix() -> None:
    raw = b"abc"
    b64 = base64.b64encode(raw).decode()
    ws = _FakeWs({
        "GetSourceScreenshot": _FakeResponse(
            True, {"imageData": f"data:image/png;base64,{b64}"}
        )
    })
    assert _client(ws).get_source_screenshot_png() == raw


def test_screenshot_request_failure_raises_request_error() -> None:
    ws = _FakeWs({"GetSourceScreenshot": _FakeResponse(status=False)})
    with pytest.raises(ObsRequestError):
        _client(ws).get_source_screenshot_png()


def test_screenshot_empty_imagedata_raises_request_error() -> None:
    ws = _FakeWs({"GetSourceScreenshot": _FakeResponse(True, {"imageData": ""})})
    with pytest.raises(ObsRequestError):
        _client(ws).get_source_screenshot_png()


# ---- list_sources / get_version ----

def test_list_sources_parses_input_names() -> None:
    ws = _FakeWs({
        "GetInputList": _FakeResponse(True, {"inputs": [
            {"inputName": "Game Capture"},
            {"inputName": "Mic"},
            {"inputName": ""},  # 空名は除外される
        ]})
    })
    assert _client(ws).list_sources() == ["Game Capture", "Mic"]


def test_get_version() -> None:
    ws = _FakeWs({
        "GetVersion": _FakeResponse(
            True, {"obsVersion": "30.1.0", "obsWebSocketVersion": "5.4.0"}
        )
    })
    info = _client(ws).get_version()
    assert info.obs_version == "30.1.0"
    assert info.websocket_version == "5.4.0"


# ---- _call の通信切断分類 ----

def test_call_connection_failure_raises_connection_error() -> None:
    ws = _FakeWs(raise_exc=obs_exc.ConnectionFailure("socket closed"))
    with pytest.raises(ObsConnectionError):
        _client(ws).get_version()


def test_call_without_connection_raises_connection_error() -> None:
    client = OBSClient(ObsConfig(source_name="src"))  # 未接続（_ws is None）
    with pytest.raises(ObsConnectionError):
        client.get_version()


def test_disconnect_is_idempotent_and_safe() -> None:
    ws = _FakeWs()
    client = _client(ws)
    client.disconnect()
    assert client.connected is False
    assert ws.disconnected is True
    client.disconnect()  # 2回目も例外を出さない


def test_source_name_property() -> None:
    assert OBSClient(ObsConfig(source_name="my-source")).source_name == "my-source"


# ---- connect() が obsws に legacy=False を明示すること（I-021）----

class _ObswsSpy:
    """obsws をフェイクし、コンストラクタに渡された kwargs を記録する。"""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None


@pytest.mark.parametrize("port", [4444, 4455, 4456])
def test_connect_forces_legacy_false_regardless_of_port(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    """obs-websocket-py は port==4444 で暗黙的に legacy=True（v4）に切り替える。
    LivelyRec は v5 onlyサポートなので、ポートに関わらず legacy=False を明示する。
    """
    _ObswsSpy.last_kwargs = None
    monkeypatch.setattr(
        "livelyrec.infrastructure.obs_client.obsws", _ObswsSpy
    )

    OBSClient(ObsConfig(host="127.0.0.1", port=port, password="pw")).connect()

    assert _ObswsSpy.last_kwargs is not None
    assert _ObswsSpy.last_kwargs.get("legacy") is False
    assert _ObswsSpy.last_kwargs.get("port") == port
