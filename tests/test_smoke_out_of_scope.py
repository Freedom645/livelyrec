"""「対象外」モジュールのスモークテスト。

単体テスト計画書 §2.2 で後工程（結合テスト／システムテスト）へ委譲した
モジュール（OBS クライアント・WebSocket Server・PaddleOCR・エントリポイント）
について、「例外なく import・構築できる」ことのみを確認する。
実通信・実推論を伴う検証はここでは行わない。
"""

from __future__ import annotations

import json
from pathlib import Path


def test_app_module_imports() -> None:
    import livelyrec.app  # noqa: F401


def test_obs_client_constructs() -> None:
    from livelyrec.infrastructure.obs_client import OBSClient, ObsConfig

    client = OBSClient(ObsConfig())
    assert client.connected is False


def test_ws_server_constructs_and_registers_handler() -> None:
    from livelyrec.infrastructure.ws_server import WebSocketServer, WsServerConfig

    server = WebSocketServer(WsServerConfig())
    server.register_request_handler("ping.request", lambda payload: {"ok": True})
    # 未起動状態の broadcast は例外を出さず何もしない
    server.broadcast("some.event", {"value": 1})


def test_ws_envelope_produces_valid_json() -> None:
    from livelyrec.infrastructure.ws_server import _envelope

    env = json.loads(_envelope("test.event", {"value": 42}))
    assert env["type"] == "test.event"
    assert env["payload"] == {"value": 42}
    assert "ts" in env
    assert "schema" in env


def test_paddle_engine_constructs_without_loading_model() -> None:
    from livelyrec.infrastructure.ocr.base import OcrEngine
    from livelyrec.infrastructure.ocr.paddle import PaddleOcrEngine

    # 構築のみ。学習済みモデルの実ロードは結合テストで検証する
    engine = PaddleOcrEngine()
    assert isinstance(engine, OcrEngine)


def test_github_client_constructs() -> None:
    from livelyrec.infrastructure.github_client import GitHubClient, MasterFetcher

    GitHubClient(owner="example", repo="livelyrec")
    MasterFetcher(
        endpoint_url="https://example/master.json",
        cache_path=Path("master_cache.json"),
    )
