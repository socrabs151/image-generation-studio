"""Tests for the keystore built on top of the settings store."""

from __future__ import annotations

from pathlib import Path

from app.services.keystore import KeyStore
from app.services.settings_store import SettingsStore


def test_get_missing_key_is_empty(tmp_path: Path) -> None:
    keystore = KeyStore(SettingsStore(tmp_path / "settings.json"))
    keystore.load()
    assert keystore.get("aitunnel") == ""


def test_set_and_get_key(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    keystore = KeyStore(store)
    keystore.load()

    keystore.set("aitunnel", "sk-aitunnel-key")

    assert keystore.get("aitunnel") == "sk-aitunnel-key"
    # persisted
    assert SettingsStore(tmp_path / "settings.json").load().providers["aitunnel"].api_key == (
        "sk-aitunnel-key"
    )
