"""IT-WS: WebSocket Server の結合テスト。

実バインドした WebSocketServer に対し、`websockets` のクライアントで実接続し、
ブロードキャスト・リクエスト応答・エラー応答・トークン認証を検証する。
サーバは実スレッド上の実 asyncio ループで動作する。
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
import urllib.error
import urllib.request

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from livelyrec.infrastructure.ws_server import WebSocketServer, WsServerConfig

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_listening(server: WebSocketServer, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server._loop is not None and server._server is not None:
            return
        time.sleep(0.02)
    raise TimeoutError("WebSocket server did not start in time")


def _uri(port: int) -> str:
    return f"ws://127.0.0.1:{port}"


# ---- IT-WS-01: ブロードキャスト ----

async def _recv_broadcast(port: int, server: WebSocketServer) -> dict:
    async with websockets.connect(_uri(port)) as ws:
        await asyncio.sleep(0.3)  # サーバ側のクライアント登録を待つ
        server.broadcast("score.update", {"score": 12345})
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


def test_it_ws_01_broadcast_reaches_client() -> None:
    port = _free_port()
    server = WebSocketServer(WsServerConfig(host="127.0.0.1", port=port))
    server.start()
    _wait_listening(server)
    try:
        env = asyncio.run(_recv_broadcast(port, server))
    finally:
        server.stop()
    assert env["type"] == "score.update"
    assert env["payload"] == {"score": 12345}
    assert "ts" in env and "schema" in env


# ---- IT-WS-02: リクエスト/レスポンス ----

async def _request_response(port: int) -> dict:
    async with websockets.connect(_uri(port)) as ws:
        await ws.send(json.dumps({"type": "ping.request", "payload": {"v": 7}}))
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


def test_it_ws_02_request_handler_responds() -> None:
    port = _free_port()
    server = WebSocketServer(WsServerConfig(host="127.0.0.1", port=port))
    server.register_request_handler("ping.request", lambda payload: {"echo": payload})
    server.start()
    _wait_listening(server)
    try:
        resp = asyncio.run(_request_response(port))
    finally:
        server.stop()
    assert resp["type"] == "ping.response"
    assert resp["payload"]["echo"] == {"v": 7}


# ---- IT-WS-03: エラー応答 ----

async def _error_scenarios(port: int) -> tuple[dict, dict]:
    async with websockets.connect(_uri(port)) as ws:
        await ws.send("this is not valid json")
        invalid = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        await ws.send(json.dumps({"type": "no.such.type", "payload": {}}))
        unknown = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
    return invalid, unknown


def test_it_ws_03_invalid_request_returns_error() -> None:
    port = _free_port()
    server = WebSocketServer(WsServerConfig(host="127.0.0.1", port=port))
    server.start()
    _wait_listening(server)
    try:
        invalid, unknown = asyncio.run(_error_scenarios(port))
    finally:
        server.stop()
    assert invalid["type"] == "error"
    assert invalid["payload"]["code"] == "INVALID_REQUEST"
    assert unknown["type"] == "error"
    assert unknown["payload"]["code"] == "INVALID_REQUEST"


# ---- IT-WS-04: トークン認証 ----

async def _connect_without_token(port: int) -> bool:
    """認証必須サーバへトークン無しで接続 → 拒否されたら True。"""
    try:
        async with websockets.connect(_uri(port)) as ws:
            await asyncio.wait_for(ws.recv(), timeout=3.0)
        return False
    except (ConnectionClosed, OSError, TimeoutError):
        return True
    except Exception:
        return True


async def _connect_with_token(port: int, server: WebSocketServer, token: str) -> dict:
    """正しいトークンで接続 → ブロードキャストを受信できる。"""
    async with websockets.connect(
        _uri(port), additional_headers={"Authorization": f"Bearer {token}"}
    ) as ws:
        await asyncio.sleep(0.3)
        server.broadcast("authed.event", {"ok": True})
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


def test_it_ws_04a_auth_rejects_without_token() -> None:
    port = _free_port()
    server = WebSocketServer(
        WsServerConfig(host="127.0.0.1", port=port, lan_publish=True, token="secret-xyz")
    )
    server.start()
    _wait_listening(server)
    try:
        rejected = asyncio.run(_connect_without_token(port))
    finally:
        server.stop()
    assert rejected is True


async def _connect_with_query_token(port: int, server: WebSocketServer, token: str) -> dict:
    """URL クエリ ?token= で接続 → ブラウザソース想定の認証経路。"""
    async with websockets.connect(f"{_uri(port)}/v1?token={token}") as ws:
        await asyncio.sleep(0.3)
        server.broadcast("authed.event", {"ok": True})
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


def test_it_ws_04c_auth_accepts_query_token() -> None:
    # ブラウザはヘッダを付けられないため、?token= クエリでの認証を受理する
    port = _free_port()
    token = "secret-xyz"
    server = WebSocketServer(
        WsServerConfig(host="127.0.0.1", port=port, lan_publish=True, token=token)
    )
    server.start()
    _wait_listening(server)
    try:
        env = asyncio.run(_connect_with_query_token(port, server, token))
    finally:
        server.stop()
    assert env["type"] == "authed.event"
    assert env["payload"] == {"ok": True}


def test_it_ws_04b_auth_accepts_with_valid_token() -> None:
    port = _free_port()
    token = "secret-xyz"
    server = WebSocketServer(
        WsServerConfig(host="127.0.0.1", port=port, lan_publish=True, token=token)
    )
    server.start()
    _wait_listening(server)
    try:
        env = asyncio.run(_connect_with_token(port, server, token))
    finally:
        server.stop()
    assert env["type"] == "authed.event"
    assert env["payload"] == {"ok": True}


# ---- IT-WS-06: 接続直後の現在状態再送 ----

async def _recv_on_connect(port: int) -> dict:
    async with websockets.connect(_uri(port)) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return json.loads(raw)


def test_it_ws_06_replays_last_event_on_connect() -> None:
    # 接続前にブロードキャストした最新イベントが、新規接続時に再送される
    port = _free_port()
    server = WebSocketServer(WsServerConfig(host="127.0.0.1", port=port))
    server.start()
    _wait_listening(server)
    try:
        server.broadcast("judgements.tick", {"daily_total": {"total": 99}})
        time.sleep(0.3)  # broadcast の非同期処理（キャッシュ）完了を待つ
        env = asyncio.run(_recv_on_connect(port))
    finally:
        server.stop()
    assert env["type"] == "judgements.tick"
    assert env["payload"]["daily_total"]["total"] == 99


def test_it_ws_07_start_blocks_until_ready() -> None:
    # start() はサーバが listen 開始するまでブロックする。
    # これにより起動直後の broadcast（初期状態通知）が取りこぼされない。
    port = _free_port()
    server = WebSocketServer(WsServerConfig(host="127.0.0.1", port=port))
    server.start()
    try:
        assert server._server is not None  # start() 戻り時点で listen 済み
        server.broadcast("judgements.tick", {"daily_total": {"total": 7}})
        time.sleep(0.2)
        env = asyncio.run(_recv_on_connect(port))
    finally:
        server.stop()
    assert env["payload"]["daily_total"]["total"] == 7


# ---- IT-WS-05: ブラウザソースの HTTP 配信 ----

def test_it_ws_05_serves_browser_source_over_http(tmp_path) -> None:
    bdir = tmp_path / "browser_source"
    bdir.mkdir()
    (bdir / "index.html").write_text(
        "<html>LivelyRec overlay</html>", encoding="utf-8"
    )
    port = _free_port()
    server = WebSocketServer(
        WsServerConfig(host="127.0.0.1", port=port), browser_source_dir=bdir
    )
    server.start()
    _wait_listening(server)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/browser/index.html", timeout=5
        ) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")
        not_found = False
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/browser/missing.html", timeout=5
            )
        except urllib.error.HTTPError as e:
            not_found = e.code == 404
    finally:
        server.stop()
    assert status == 200
    assert "text/html" in ctype
    assert "LivelyRec overlay" in body
    assert not_found is True
