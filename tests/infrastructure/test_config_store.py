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
    assert settings.recording.fps == 2  # default (I-025 で 8→2 に再評価)


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(p).load()


def test_load_v1_settings_migrates_to_v2_with_defaults(tmp_path: Path) -> None:
    """v1 設定（result_capture / developer 不在）が v2 既定値で補完される。"""
    p = tmp_path / "settings.json"
    p.write_text(
        json.dumps({
            "schema_version": 1,
            "obs": {"host": "10.0.0.1"},
        }),
        encoding="utf-8",
    )
    settings = ConfigStore(p).load()
    assert settings.schema_version == 2
    assert settings.obs.host == "10.0.0.1"
    # v2 で追加されたセクションは既定値で埋まる
    assert settings.result_capture.enabled is False
    assert settings.result_capture.output_dir is None
    assert settings.developer.banner_capture_enabled is False
    assert settings.developer.banner_dir is None


def test_save_roundtrip_keeps_new_sections(tmp_path: Path) -> None:
    """新規セクションへ変更を加えても round-trip が保たれる。"""
    store = ConfigStore(tmp_path / "settings.json")
    s = store.load()
    s.result_capture.enabled = True
    s.result_capture.output_dir = "/tmp/result"
    s.developer.banner_capture_enabled = True
    s.developer.banner_dir = "/tmp/banner"
    store.save(s)
    again = store.load()
    assert again.result_capture.enabled is True
    assert again.result_capture.output_dir == "/tmp/result"
    assert again.developer.banner_capture_enabled is True
    assert again.developer.banner_dir == "/tmp/banner"
