"""Tests for the JSON files under ``data/``.

The rule these cover: a file the app cannot parse is kept, never overwritten.
For the settings file that means the API keys, which live nowhere else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ConfigError
from app.services.history_store import HistoryRecord, HistoryStore
from app.services.json_file import UnreadableFile, read_json, write_json_atomic
from app.services.settings_store import Settings, SettingsStore

# ---------- settings ----------


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_a_broken_settings_file_is_kept_aside_and_the_keys_survive(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = '{"providers": {"aitunnel": {"api_key": "sk-secret"}}, "history_limit": '
    _write(path, original)
    store = SettingsStore(path)

    with pytest.raises(ConfigError):
        store.load()

    kept = list(tmp_path.glob("settings.json.unreadable-*"))
    assert len(kept) == 1, "the unreadable file must be kept"
    assert kept[0].read_text(encoding="utf-8") == original
    assert not path.exists(), "the broken file is moved, not left in place"


def test_a_bom_in_the_settings_file_is_not_a_broken_file(tmp_path: Path) -> None:
    # A BOM is valid and used by other tools; treating it as corruption would
    # throw away the keys for no reason.
    path = tmp_path / "settings.json"
    path.write_bytes(
        json.dumps({"providers": {"aitunnel": {"api_key": "sk-secret"}}}).encode("utf-8-sig")
    )

    settings = SettingsStore(path).load()

    assert settings.providers["aitunnel"].api_key == "sk-secret"


def test_settings_of_the_wrong_shape_do_not_raise_anything_but_config_error(
    tmp_path: Path,
) -> None:
    for payload in ("[]", '"text"', "null", '{"providers": []}'):
        path = tmp_path / "settings.json"
        _write(path, payload)
        store = SettingsStore(path)
        try:
            settings = store.load()
        except ConfigError as exc:
            # A file that is valid JSON but not an object is kept aside, like a
            # file that does not parse at all.
            assert "settings" in str(exc)
            continue
        assert isinstance(settings, Settings)


def test_wrong_types_in_the_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write(
        path,
        json.dumps(
            {
                "save_dir": None,
                "theme": 7,
                "history_limit": "many",
                "session_limit_rub": None,
                "favorite_models": {"a": 1},
                "providers": {"aitunnel": {"api_key": None}},
            }
        ),
    )

    settings = SettingsStore(path).load()

    default = Settings()
    assert settings.save_dir == default.save_dir
    assert settings.theme == default.theme
    assert settings.history_limit == default.history_limit
    assert settings.session_limit_rub == default.session_limit_rub
    assert settings.favorite_models == []
    assert settings.providers["aitunnel"].api_key == ""


def test_a_locked_settings_file_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    """A file that cannot be opened holds the keys. Writing defaults over it
    would destroy them silently, so the store refuses and says so."""
    path = tmp_path / "settings.json"
    _write(path, '{"providers": {"aitunnel": {"api_key": "sk-secret"}}}')
    store = SettingsStore(path)

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "the file is in use")

    monkeypatch.setattr(Path, "read_text", refuse)
    with pytest.raises(ConfigError):
        store.load()
    assert store.damaged is True

    monkeypatch.undo()
    store.save(Settings())
    # The keys are still there, because the save was refused.
    assert "sk-secret" in path.read_text(encoding="utf-8")


def test_reading_a_healthy_settings_file_clears_the_damaged_flag(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    _write(path, "not json at all")
    with pytest.raises(ConfigError):
        store.load()

    _write(path, "{}")
    store.load()

    assert store.damaged is False


# ---------- history ----------


def test_a_broken_history_file_is_kept_aside(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    original = '{"records": [{"prompt": "a cat", "cost_rub": 12.5},'
    _write(path, original)
    store = HistoryStore(path)

    with pytest.raises(ConfigError):
        store.load()

    kept = list(tmp_path.glob("history.json.unreadable-*"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == original
    assert "a cat" in kept[0].read_text(encoding="utf-8")


def test_history_survives_a_bom(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_bytes(
        json.dumps({"records": [{"prompt": "кот", "cost_rub": 3.0}]}).encode("utf-8-sig")
    )

    records = HistoryStore(path).load()

    assert [record.prompt for record in records] == ["кот"]
    assert records[0].cost_rub == 3.0


def test_history_of_the_wrong_shape_does_not_crash_the_window(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    _write(
        path,
        json.dumps(
            {"records": ["oops", {"n": "x", "cost_rub": "free"}, {"prompt": "ok"}]}
        ),
    )

    records = HistoryStore(path).load()

    # A string where a record belongs is skipped; a record with odd values is
    # kept with defaults rather than taking the whole window down.
    assert "oops" not in [record.prompt for record in records]
    assert records[-1].prompt == "ok"
    odd = next(record for record in records if record.prompt == "")
    assert odd.n == 1
    assert odd.cost_rub is None, "an unreadable price stays unknown, never zero"


def test_a_new_record_is_written_after_the_file_was_quarantined(tmp_path: Path) -> None:
    """The app has to start working again: the broken file is set aside, the
    history keeps filling up from there."""
    path = tmp_path / "history.json"
    _write(path, "broken")
    store = HistoryStore(path)
    with pytest.raises(ConfigError):
        store.load()
    store.load()

    store.add(HistoryRecord(prompt="new", model="muse-image", cost_rub=1.0))

    assert [record.prompt for record in store.records()] == ["new"]
    assert json.loads(path.read_text(encoding="utf-8"))["records"][0]["prompt"] == "new"


# ---------- the shared helpers ----------


def test_write_json_atomic_replaces_the_file(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    write_json_atomic(path, {"a": 1})
    write_json_atomic(path, {"a": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert list(tmp_path.glob("*.tmp")) == [], "no temporary file is left behind"


def test_write_json_refuses_nan(tmp_path: Path) -> None:
    # NaN is not JSON; a history file that other tools cannot read is a trap.
    path = tmp_path / "data.json"
    with pytest.raises(ValueError):
        write_json_atomic(path, {"cost": float("nan")})
    assert not path.exists()


def test_a_missing_file_is_an_open_error_not_a_corrupt_one(tmp_path: Path) -> None:
    with pytest.raises(UnreadableFile):
        read_json(tmp_path / "nope.json", "settings")
