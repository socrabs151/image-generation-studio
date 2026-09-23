"""Tests for the settings store: bootstrap and round-trip persistence."""

from __future__ import annotations

from pathlib import Path

from app.services.settings_store import Settings, SettingsStore


def test_bootstrap_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert not path.exists()

    settings = store.load()

    assert path.exists()
    assert isinstance(settings, Settings)
    assert settings.default_provider == "aitunnel"
    assert "aitunnel" in settings.providers


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = store.load()
    settings.providers["aitunnel"].api_key = "sk-aitunnel-test"
    settings.theme = "dark"
    store.save(settings)

    reloaded = store.load()

    assert reloaded.providers["aitunnel"].api_key == "sk-aitunnel-test"
    assert reloaded.theme == "dark"
