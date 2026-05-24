"""統合テスト用 pytest fixture。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _unlock_fps_for_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """記録ループ統合テストは fps を高めに設定して短時間で多フレーム回す。

    本番上限 MAX_FPS=2 のままだと `_wait_for(timeout=10s)` 内に必要フレームが
    消費できず欠陥でない理由でタイムアウトする。テスト中のみ上限を解除する。
    """
    monkeypatch.setattr("livelyrec.shared.constants.MAX_FPS", 60)
