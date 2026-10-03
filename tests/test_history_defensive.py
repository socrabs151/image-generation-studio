"""B5: a hand-edited history file must not take the window down."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.history_stats import summarize
from app.services.history_store import (
    HistoryRecord,
    HistoryStore,
    _as_dict,
    _as_float,
    _as_int,
    _as_str,
    _as_str_list,
)


class TestTheHelpers:
    @pytest.mark.parametrize("value", [None, 42, 3.5, True, ["a"], {"a": 1}])
    def test_anything_becomes_a_string(self, value: object) -> None:
        assert isinstance(_as_str(value), str)

    def test_a_real_string_is_untouched(self) -> None:
        assert _as_str("hello") == "hello"

    def test_a_single_path_does_not_become_letters(self) -> None:
        """The bug: "C:\\a.png" iterated character by character."""
        assert _as_str_list("C:\\images\\cat.png") == ["C:\\images\\cat.png"]

    def test_a_list_of_paths_is_kept(self) -> None:
        assert _as_str_list(["a.png", "b.png"]) == ["a.png", "b.png"]

    def test_a_list_with_nulls_is_kept_whole(self) -> None:
        assert _as_str_list(["a.png", None, 7]) == ["a.png", "", "7"]

    @pytest.mark.parametrize("value", [None, 42, {"a": 1}, []])
    def test_a_non_list_of_paths_is_empty(self, value: object) -> None:
        assert _as_str_list(value) == []

    def test_a_lone_string_counts_as_one_path_not_as_letters(self) -> None:
        """Hand-written files hold one path, not a list of them."""
        assert _as_str_list("single.png") == ["single.png"]

    def test_booleans_are_not_numbers(self) -> None:
        """True would otherwise become 1, a price of 1 ₽ out of nowhere."""
        assert _as_float(True) is None
        assert _as_float(False) is None
        assert _as_int(True, 1) == 1
        assert _as_int(None, 7) == 7

    def test_a_request_snapshot_must_be_a_dict(self) -> None:
        assert _as_dict({"a": 1}) == {"a": 1}
        assert _as_dict(["a"]) == {}
        assert _as_dict(None) == {}
        assert _as_dict("n") == {}


class _Store:
    """A history file with exactly the given body."""

    def __init__(self, tmp_path: Path, records: list[dict]) -> HistoryStore:
        self.path = tmp_path / "history.json"
        self.path.write_text(
            json.dumps({"schema_version": 2, "records": records}), encoding="utf-8"
        )
        self.store = HistoryStore(self.path)

    def read(self) -> HistoryRecord:
        return self.store.records()[0]


class TestExplicitNulls:
    def test_nulls_in_every_field_are_survivable(self, tmp_path: Path) -> None:
        store = _Store(
            tmp_path,
            [
                {
                    "id": None,
                    "timestamp": None,
                    "provider_id": None,
                    "model": None,
                    "prompt": None,
                    "n": None,
                    "cost_rub": None,
                    "file_paths": None,
                    "status": None,
                    "error": None,
                    "request": None,
                    "duration_seconds": None,
                }
            ],
        )

        record = store.read()

        assert record.id, "an id is invented so the window can address the record"
        assert record.timestamp
        assert record.provider_id == ""
        assert record.model == ""
        assert record.prompt == ""
        assert record.n == 1
        assert record.cost_rub is None
        assert record.file_paths == []
        assert record.status == "ok"
        assert record.error == ""
        assert record.request == {}

    def test_the_statistics_survive_a_null_prompt(self, tmp_path: Path) -> None:
        """This is what used to crash: None.lower() in the GUI thread."""
        store = _Store(tmp_path, [{"prompt": None, "model": None, "cost_rub": None}])

        summary = summarize(store.store.records())

        assert summary is not None

    def test_the_window_can_filter_a_null_prompt(self, tmp_path: Path) -> None:
        store = _Store(tmp_path, [{"prompt": None}, {"prompt": "a cat"}])

        found = [r for r in store.store.records() if "cat" in r.prompt.lower()]

        assert len(found) == 1


class TestWrongTypes:
    def test_numbers_where_text_belongs(self, tmp_path: Path) -> None:
        store = _Store(tmp_path, [{"model": 42, "prompt": 7, "status": 200}])

        record = store.read()

        assert record.model == "42"
        assert record.prompt == "7"
        assert record.status == "200"

    def test_a_prompt_as_a_list_does_not_crash(self, tmp_path: Path) -> None:
        store = _Store(tmp_path, [{"prompt": ["a", "b"]}])

        assert store.read().prompt

    def test_a_price_as_text_still_reads(self, tmp_path: Path) -> None:
        store = _Store(tmp_path, [{"cost_rub": "1.26"}])

        assert store.read().cost_rub == 1.26

    def test_a_price_that_is_not_a_number_stays_unknown(self, tmp_path: Path) -> None:
        store = _Store(tmp_path, [{"cost_rub": "unknown"}])

        assert store.read().cost_rub is None

    def test_an_odd_record_does_not_cost_the_others(self, tmp_path: Path) -> None:
        """One bad record must not empty the whole history."""
        store = _Store(
            tmp_path,
            [{"prompt": None, "model": "seedream"}, {"prompt": "a cat", "file_paths": "x.png"}],
        )

        records = store.store.records()

        assert len(records) == 2
        assert records[1].file_paths == ["x.png"]

    def test_a_reload_writes_the_sanitised_record(self, tmp_path: Path) -> None:
        """The fixed shape is what gets persisted next time."""
        store = _Store(tmp_path, [{"prompt": None, "file_paths": "x.png"}])
        store.store.add(HistoryRecord(prompt="second"))

        raw = json.loads(store.path.read_text(encoding="utf-8"))
        newest = raw["records"][0]
        assert isinstance(newest["prompt"], str)
        assert isinstance(newest["file_paths"], list)
