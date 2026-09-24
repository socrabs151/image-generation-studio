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


def test_new_spending_fields_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = store.load()
    settings.confirm_threshold_rub = 120.0
    settings.session_limit_rub = 500.0
    settings.generation_timeout = 90
    store.save(settings)

    reloaded = store.load()

    assert reloaded.confirm_threshold_rub == 120.0
    assert reloaded.session_limit_rub == 500.0
    assert reloaded.generation_timeout == 90


def test_missing_new_fields_get_defaults(tmp_path: Path) -> None:
    # Simulate an old settings file without the M2 fields.
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.confirm_threshold_rub == 50.0
    assert settings.session_limit_rub == 0.0
    assert settings.generation_timeout == 180
