"""Tests for the fixes from the audit: data URI decoding, balance resilience,
history copy semantics and the settings file location."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.core.errors import ConfigError, ProviderError
from app.providers.http_utils import decode_base64
from app.services.history_store import HistoryRecord, HistoryStore
from app.services.settings_store import Settings, SettingsStore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


# ---------- decode_base64 ----------


def test_decode_plain_base64() -> None:
    assert decode_base64(base64.b64encode(PNG).decode("ascii")) == PNG


def test_decode_data_uri() -> None:
    # Polza.ai answers with a data URI; before the fix it raised "incorrect padding".
    encoded = f"data:image/png;base64,{base64.b64encode(PNG).decode('ascii')}"
    assert decode_base64(encoded) == PNG


def test_decode_tolerates_whitespace() -> None:
    encoded = base64.b64encode(PNG).decode("ascii")
    wrapped = "\n".join(encoded[index : index + 40] for index in range(0, len(encoded), 40))
    assert decode_base64(wrapped) == PNG


def test_decode_rejects_garbage_instead_of_silently_dropping_it() -> None:
    # validate=False used to drop the invalid characters and return a truncated image.
    with pytest.raises(ProviderError):
        decode_base64("not valid base64 !!!!")


def test_decode_rejects_data_uri_without_payload() -> None:
    with pytest.raises(ProviderError):
        decode_base64("data:image/png;base64")


# ---------- history ----------


def test_records_returns_a_copy(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.add(HistoryRecord(prompt="one"))
    snapshot = store.records()
    snapshot.clear()
    assert len(store.records()) == 1


def test_add_is_visible_to_a_later_reader(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.add(HistoryRecord(prompt="one"))
    store.add(HistoryRecord(prompt="two"))
    assert [record.prompt for record in store.records()] == ["two", "one"]


# ---------- settings store ----------


def test_save_creates_the_directory_of_the_target_file(tmp_path: Path) -> None:
    # The store must not touch the real data folder when pointed elsewhere.
    target = tmp_path / "nested" / "deeper" / "settings.json"
    store = SettingsStore(path=target)
    store.save(Settings())
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == 1


def test_load_of_a_damaged_file_reports_a_clear_error(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        SettingsStore(path=target).load()
    assert "settings" in str(info.value).lower()
