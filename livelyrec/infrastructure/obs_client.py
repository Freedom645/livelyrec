"""OBS WebSocket v5 クライアント（obs-websocket-py / 同期）。

詳細: docs/design/08_詳細設計_API設計.md §2

2026-05-20: 旧実装（simpleobsws / 非同期）から obs-websocket-py（同期）へ移行。
同期 API のため、呼び出し側（recording_service）はワーカースレッド上の
単純なポーリングループとして実装できる。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

from obswebsocket import exceptions as obs_exc
from obswebsocket import obsws, requests

from livelyrec.shared.exceptions import (
    ObsAuthError,
    ObsConfigurationError,
    ObsConnectionError,
    ObsRequestError,
    ObsTimeoutError,
)

logger = logging.getLogger("livelyrec.obs")

# 接続・リクエストのタイムアウト（秒）
_TIMEOUT = 5.0


@dataclass(frozen=True)
class ObsConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    source_name: str = ""


@dataclass(frozen=True)
class ObsInfo:
    obs_version: str
    websocket_version: str


def _classify_connect_error(e: Exception) -> ObsConnectionError:
    """接続時例外を認証／タイムアウト／一般接続エラーに分類する。"""
    msg = str(e).lower()
    if "auth" in msg or "password" in msg or "challenge" in msg:
        return ObsAuthError(
            f"OBS 認証に失敗しました（パスワードを確認してください）: {e}"
        )
    if "time" in msg and "out" in msg:
        return ObsTimeoutError(f"OBS への接続がタイムアウトしました: {e}")
    return ObsConnectionError(
        f"OBS に接続できませんでした（OBS の起動・WebSocket 設定を確認してください）: {e}"
    )


class OBSClient:
    """obs-websocket-py を用いた同期 OBS クライアント。"""

    def __init__(self, cfg: ObsConfig) -> None:
        self._cfg = cfg
        self._ws: obsws | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def source_name(self) -> str:
        return self._cfg.source_name

    # ---- 接続ライフサイクル ----

    def connect(self) -> None:
        """OBS へ接続する。失敗時は分類した例外を送出する。

        `legacy=False` を明示する理由:
        obs-websocket-py は `legacy=None`（既定）かつ `port==4444` の場合、
        暗黙的に `legacy=True`（v4 プロトコル）へ切り替える内部実装を持つ
        (`obswebsocket.core.obsws.__init__`)。LivelyRec は OBS Studio 28 以降の
        WebSocket v5 のみサポートする（NFR-PORT-002）ため、ユーザが過去の
        v4 既定ポート 4444 を設定していても v5 ハンドシェイクを行うよう固定する。
        固定しないと "Invalid initial response" でハンドシェイクに失敗する。
        """
        try:
            ws = obsws(
                host=self._cfg.host,
                port=self._cfg.port,
                password=self._cfg.password or "",
                legacy=False,
                timeout=_TIMEOUT,
            )
            ws.connect()
        except obs_exc.ConnectionFailure as e:
            raise _classify_connect_error(e) from e
        except (TimeoutError, OSError) as e:
            raise ObsTimeoutError(f"OBS への接続がタイムアウトしました: {e}") from e
        except Exception as e:  # noqa: BLE001  (ライブラリ内例外を広く分類)
            raise _classify_connect_error(e) from e
        self._ws = ws
        self._connected = True
        logger.info("OBS connected: %s:%s", self._cfg.host, self._cfg.port)

    def disconnect(self) -> None:
        ws, self._ws = self._ws, None
        self._connected = False
        if ws is not None:
            try:
                ws.disconnect()
            except Exception:
                logger.debug("OBS disconnect ignored exception", exc_info=True)

    def test_connect(self) -> ObsInfo:
        """疎通確認用: 接続 → バージョン取得 → 切断。設定検証に用いる。"""
        self.connect()
        try:
            return self.get_version()
        finally:
            self.disconnect()

    # ---- リクエスト ----

    def get_version(self) -> ObsInfo:
        data = self._call(requests.GetVersion())
        return ObsInfo(
            obs_version=str(data.get("obsVersion", "")),
            websocket_version=str(data.get("obsWebSocketVersion", "")),
        )

    def list_sources(self) -> list[str]:
        """入力ソース名の一覧を返す（設定画面のソース選択に用いる）。"""
        data = self._call(requests.GetInputList())
        inputs = data.get("inputs", []) or []
        return [
            str(i.get("inputName", ""))
            for i in inputs
            if i.get("inputName")
        ]

    def get_source_screenshot_png(
        self,
        source_name: str | None = None,
        width: int = 1366,
        height: int = 768,
    ) -> bytes:
        """ソースのスクリーンショットを PNG バイト列で取得する。"""
        name = source_name or self._cfg.source_name
        if not name:
            raise ObsConfigurationError("OBS ソース名が設定されていません")
        data = self._call(
            requests.GetSourceScreenshot(
                sourceName=name,
                imageFormat="png",
                imageWidth=width,
                imageHeight=height,
            )
        )
        b64 = data.get("imageData", "") or ""
        if not b64:
            raise ObsRequestError(
                f"ソース '{name}' のスクリーンショットを取得できませんでした"
            )
        # data URI 形式（"data:image/png;base64,..."）の場合がある
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)

    # ---- 内部 ----

    def _call(self, request) -> dict:
        """リクエストを送出しレスポンス data(dict) を返す。

        通信切断は ObsConnectionError、リクエスト失敗（不正なソース名等）は
        ObsRequestError に分類する。両者の分離により、呼び出し側は
        「再接続すべき切断」と「再接続しても無駄な設定/要求エラー」を区別できる。
        """
        if self._ws is None:
            raise ObsConnectionError("OBS に接続していません")
        try:
            resp = self._ws.call(request)
        except (obs_exc.ConnectionFailure, obs_exc.MessageTimeout) as e:
            self._connected = False
            raise ObsConnectionError(f"OBS との通信が切断されました: {e}") from e
        except Exception as e:  # noqa: BLE001
            self._connected = False
            raise ObsConnectionError(f"OBS との通信に失敗しました: {e}") from e
        if not getattr(resp, "status", False):
            raise ObsRequestError(
                f"OBS リクエスト {getattr(request, 'name', '?')} が失敗しました"
            )
        return getattr(resp, "datain", {}) or {}
