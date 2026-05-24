"""ConfigStore のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from livelyrec.infrastructure.config_store import (
    AppSettings,
    ConfigStore,
    ObsSettings,
)
from livelyrec.shared.exceptions import ConfigError


def test_load_creates_default_when_missing(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    settings = store.load()
    assert isinstance(settings, AppSettings)
    assert store.path.exists()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    settings = store.load()
    settings.obs = ObsSettings(host="192.168.0.10", port=4500, source_name="game", password="x")
    store.save(settings)

    again = store.load()
    assert again.obs.host == "192.168.0.10"
    assert again.obs.port == 4500
    assert again.obs.source_name == "game"
    assert again.obs.password == "x"  # 平文保存方針


def test_load_partial_json_merges_defaults(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"obs": {"host": "127.0.0.1"}}), encoding="utf-8")
    settings = ConfigStore(p).load()
    assert settings.obs.host == "127.0.0.1"
    assert settings.obs.port == 4455  # default
    assert settings.recording.fps == 8  # default


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(p).load()
