"""外部連携 WebSocket Server。

詳細: docs/design/08_詳細設計_API設計.md §1
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import websockets
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from livelyrec.shared.constants import WS_SCHEMA_VERSION

logger = logging.getLogger("livelyrec.ws")

RequestHandler = Callable[[dict], dict]


@dataclass(frozen=True)
class WsServerConfig:
    host: str = "127.0.0.1"
    port: int = 14514
    lan_publish: bool = False
    token: str = ""


class WebSocketServer:
    """LivelyRec のイベント配信用 WebSocket Server。

    別スレッドで asyncio ループを回し、メイン側からは ``broadcast`` で
    メッセージをキューに積む。クライアントからの要求は
    ``register_request_handler`` で登録した関数で処理する。
    """

    def __init__(
        self,
        cfg: WsServerConfig,
        browser_source_dir: Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._browser_dir = browser_source_dir
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: websockets.WebSocketServer | None = None
        # サーバが listen 開始したことを start() 呼び出し元へ知らせる
        self._ready = threading.Event()
        self._clients: set[websockets.WebSocketServerProtocol] = set()
        self._handlers: dict[str, RequestHandler] = {}
        # 種別ごとの最新イベント（新規接続クライアントへ初期状態を再送する用）
        self._last_events: dict[str, str] = {}

    # --- 起動・停止 ---

    def start(self) -> None:
        if self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="ws-server", daemon=True
        )
        self._thread.start()
        # サーバが listen 開始するまで待つ。これをしないと、起動直後の
        # broadcast がサーバ未準備で取りこぼされる（配信支援の初期表示が出ない）。
        if not self._ready.wait(timeout=5.0):
            logger.warning("ws server did not become ready within 5s")

    def stop(self) -> None:
        if self._loop is None:
            return
        loop = self._loop
        loop.call_soon_threadsafe(self._signal_stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None
        self._loop = None
        self._ready.clear()

    def _signal_stop(self) -> None:
        if self._server is not None:
            self._server.close()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        self._server = await websockets.serve(
            self._handle_client,
            self._cfg.host,
            self._cfg.port,
            max_queue=100,
            process_request=self._process_request,
        )
        self._ready.set()
        logger.info(
            "ws server listening on ws://%s:%s/v1 (lan_publish=%s)",
            self._cfg.host,
            self._cfg.port,
            self._cfg.lan_publish,
        )
        try:
            await self._server.wait_closed()
        except asyncio.CancelledError:
            pass

    # --- 静的ファイル配信（配信支援ブラウザソース / I-014） ---

    def _process_request(self, connection, request):  # noqa: ARG002
        """WebSocket 以外の HTTP 要求には browser_source の静的ファイルを返す。

        ブラウザソース（OBS ブラウザソース／一般ブラウザ）が
        http://host:port/browser/index.html を開けるようにする。
        WebSocket アップグレード要求は None を返してハンドシェイクへ進める。
        """
        upgrade = request.headers.get("Upgrade", "") or ""
        if upgrade.lower() == "websocket":
            return None
        return self._serve_static(request.path)

    def _serve_static(self, path: str) -> Response:
        if self._browser_dir is None:
            return _http_response(404, "Not Found", b"browser source not available")
        rel = path.split("?", 1)[0].lstrip("/")
        if rel.startswith("browser/"):
            rel = rel[len("browser/") :]
        if rel in ("", "browser"):
            rel = "index.html"
        base = self._browser_dir.resolve()
        target = (base / rel).resolve()
        # ディレクトリトラバーサル防止
        if base != target and base not in target.parents:
            return _http_response(403, "Forbidden", b"forbidden")
        if not target.is_file():
            return _http_response(404, "Not Found", b"not found")
        try:
            body = target.read_bytes()
        except OSError:
            return _http_response(404, "Not Found", b"not found")
        return _http_response(200, "OK", body, _content_type(target.suffix))

    # --- ハンドラ登録 ---

    def register_request_handler(self, type_name: str, handler: RequestHandler) -> None:
        self._handlers[type_name] = handler

    # --- メッセージ送信 ---

    def broadcast(self, type_name: str, payload: dict) -> None:
        """全クライアントへメッセージを送信する（スレッドセーフ）。"""
        if self._loop is None or self._server is None:
            return
        msg = _envelope(type_name, payload)
        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(type_name, msg), self._loop
        )

    async def _broadcast_async(self, type_name: str, msg: str) -> None:
        # 新規接続クライアントへ初期状態を再送できるよう、種別ごとに最新を保持
        self._last_events[type_name] = msg
        dead: list[websockets.WebSocketServerProtocol] = []
        for ws in list(self._clients):
            try:
                await ws.send(msg)
            except ConnectionClosed:
                dead.append(ws)
            except Exception as e:
                logger.warning("send failed: %s", e)
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # --- クライアント処理 ---

    def _is_authorized(self, ws: websockets.WebSocketServerProtocol) -> bool:
        """LAN 公開時のトークン認証。

        Authorization ヘッダ（Bearer）に加え、URL クエリ ``?token=`` も受理する。
        ブラウザの WebSocket API は任意ヘッダを付与できないため、ブラウザソースは
        クエリでトークンを渡す。
        """
        expected = self._cfg.token
        # websockets 13+ の asyncio Server ではヘッダは ws.request.headers から取る
        if ws.request.headers.get("Authorization", "") == f"Bearer {expected}":
            return True
        query = urlsplit(ws.request.path).query
        return (parse_qs(query).get("token") or [""])[0] == expected

    async def _handle_client(self, ws: websockets.WebSocketServerProtocol) -> None:
        # 認証チェック（LAN公開時のみ）
        if (
            self._cfg.lan_publish
            and self._cfg.token
            and not self._is_authorized(ws)
        ):
            logger.warning("ws auth failed from %s", ws.remote_address)
            await ws.close(code=4401, reason="auth required")
            return
        self._clients.add(ws)
        logger.info("ws client connected: %s (n=%d)", ws.remote_address, len(self._clients))
        # 接続直後に種別ごとの最新イベントを再送し、オーバーレイを即座に同期させる
        for cached in list(self._last_events.values()):
            try:
                await ws.send(cached)
            except ConnectionClosed:
                self._clients.discard(ws)
                return
            except Exception as e:
                logger.warning("snapshot send failed: %s", e)
        try:
            async for raw in ws:
                await self._dispatch(ws, raw)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            logger.info("ws client disconnected (n=%d)", len(self._clients))

    async def _dispatch(self, ws: websockets.WebSocketServerProtocol, raw: Any) -> None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            await ws.send(_envelope("error", {
                "code": "INVALID_REQUEST",
                "message": "invalid JSON",
            }))
            return
        type_name = data.get("type", "")
        handler = self._handlers.get(type_name)
        if handler is None:
            await ws.send(_envelope("error", {
                "request_id": data.get("payload", {}).get("request_id"),
                "code": "INVALID_REQUEST",
                "message": f"unknown type: {type_name}",
            }))
            return
        try:
            payload = data.get("payload", {}) or {}
            response_payload = handler(payload)
        except Exception as e:
            logger.exception("handler %s failed", type_name)
            await ws.send(_envelope("error", {
                "request_id": (data.get("payload") or {}).get("request_id"),
                "code": "INTERNAL",
                "message": str(e),
            }))
            return
        # type_name="chart.history.request" → 応答 type は "chart.history.response"
        if type_name.endswith(".request"):
            resp_type = type_name[:-len(".request")] + ".response"
        else:
            resp_type = type_name + ".response"
        await ws.send(_envelope(resp_type, response_payload))


def _envelope(type_name: str, payload: dict) -> str:
    return json.dumps({
        "type": type_name,
        "ts": datetime.now().astimezone().isoformat(),
        "schema": WS_SCHEMA_VERSION,
        "payload": payload,
    }, ensure_ascii=False)


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _content_type(suffix: str) -> str:
    return _CONTENT_TYPES.get(suffix.lower(), "application/octet-stream")


def _http_response(
    status: int,
    reason: str,
    body: bytes,
    content_type: str = "text/plain; charset=utf-8",
) -> Response:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    return Response(status, reason, headers, body)
