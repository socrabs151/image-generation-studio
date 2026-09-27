"""Tests for the history totals and the CSV/JSON export."""

from __future__ import annotations

import json

from app.services.history_stats import (
    filter_options,
    filter_records,
    summarize,
    to_csv,
    to_json,
    totals_by_model,
    totals_by_provider,
)
from app.services.history_store import HistoryRecord


def _record(**overrides) -> HistoryRecord:
    defaults = dict(
        id="abc",
        timestamp="2026-01-01T00:00:00",
        provider_id="polza",
        model="bytedance/seedream-4",
        prompt="кот",
        n=1,
    )
    defaults.update(overrides)
    return HistoryRecord(**defaults)


def test_summarize_counts_and_spend() -> None:
    totals = summarize(
        [
            _record(cost_rub=2.9, file_paths=["a.png"]),
            _record(cost_rub=8.4, file_paths=["b.png", "c.png", "d.png"]),
            _record(status="error", cost_rub=None, error="нет денег"),
        ]
    )

    assert totals.attempts == 3
    assert totals.succeeded == 2
    assert totals.failed == 1
    assert totals.images == 4
    assert totals.spent_rub == 11.3
    assert totals.unpriced == 1
    assert "11.30" in totals.summary()


def test_summarize_counts_requested_images_without_files() -> None:
    # A record whose files were deleted still reports how many images it produced.
    totals = summarize([_record(cost_rub=1.0, n=3, file_paths=[])])

    assert totals.images == 3


def test_summarize_of_nothing() -> None:
    totals = summarize([])

    assert totals.attempts == 0
    assert totals.spent_rub == 0.0


def test_totals_by_provider_sorted_by_spend() -> None:
    groups = totals_by_provider(
        [
            _record(provider_id="aitunnel", cost_rub=1.0),
            _record(provider_id="polza", cost_rub=5.0),
            _record(provider_id="polza", cost_rub=2.0),
        ]
    )

    assert [group.name for group in groups] == ["polza", "aitunnel"]
    assert groups[0].spent_rub == 7.0
    assert groups[0].attempts == 2


def test_totals_by_model_counts_images() -> None:
    groups = totals_by_model(
        [
            _record(cost_rub=1.0, file_paths=["a.png", "b.png"]),
            _record(status="error", error="boom"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].attempts == 2
    assert groups[0].images == 2


def test_csv_has_a_header_and_one_row_per_record() -> None:
    text = to_csv(
        [
            _record(cost_rub=2.5, file_paths=["a.png", "b.png"], request={"n": 2}),
            _record(cost_rub=None, status="error", error="boom"),
        ]
    )
    lines = text.strip().splitlines()

    assert lines[0].startswith("id,timestamp,provider_id")
    assert len(lines) == 3
    assert "кот" in lines[1]
    assert "a.png; b.png" in lines[1]
    # The snapshot is embedded as JSON and therefore CSV-escaped.
    assert '""n"": 2' in lines[1]
    # An unknown cost stays empty rather than becoming a zero.
    assert ",,error," in lines[2]


def test_csv_quotes_a_prompt_with_a_comma() -> None:
    text = to_csv([_record(prompt="кот, который гуляет")])

    assert '"кот, который гуляет"' in text


def test_json_export_round_trips() -> None:
    text = to_json([_record(cost_rub=2.5, request={"aspect_ratio": "1:1"})])
    payload = json.loads(text)

    assert payload["version"] == 1
    entry = payload["records"][0]
    assert entry["model"] == "bytedance/seedream-4"
    assert entry["cost_rub"] == 2.5
    assert entry["request"] == {"aspect_ratio": "1:1"}


def test_json_export_of_nothing_is_still_valid() -> None:
    assert json.loads(to_json([]))["records"] == []


def test_filter_by_prompt_is_case_insensitive() -> None:
    records = [
        _record(prompt="Черничка поехала домой"),
        _record(prompt="Лунный пейзаж"),
    ]

    assert len(filter_records(records, query="черничка")) == 1
    assert len(filter_records(records, query="ЧЕРНИЧКА")) == 1
    assert len(filter_records(records, query="  пейзаж ")) == 1
    assert filter_records(records, query="собака") == []


def test_filter_also_matches_the_model() -> None:
    records = [_record(model="qwen-image-3", prompt="кот")]

    assert len(filter_records(records, query="qwen")) == 1
    assert filter_records(records, query="seedream") == []


def test_filter_by_facets() -> None:
    records = [
        _record(provider_id="aitunnel", model="muse-image", status="ok"),
        _record(provider_id="polza", model="qwen/image", status="error"),
    ]

    assert len(filter_records(records, provider="polza")) == 1
    assert len(filter_records(records, model="muse-image")) == 1
    assert len(filter_records(records, status="error")) == 1
    assert len(filter_records(records)) == 2


def test_filter_combines_facets_and_phrase() -> None:
    records = [
        _record(provider_id="polza", prompt="Черничка", status="ok"),
        _record(provider_id="aitunnel", prompt="Черничка", status="ok"),
        _record(provider_id="polza", prompt="Луна", status="ok"),
    ]

    found = filter_records(records, query="Черничка", provider="polza")

    assert len(found) == 1
    assert found[0].provider_id == "polza"


def test_filter_options_lists_distinct_values() -> None:
    records = [
        _record(provider_id="polza", model="qwen/image", status="ok"),
        _record(provider_id="aitunnel", model="muse-image", status="error"),
        _record(provider_id="polza", model="qwen/image", status="ok"),
    ]

    providers, models, statuses = filter_options(records)

    assert providers == ["aitunnel", "polza"]
    assert models == ["muse-image", "qwen/image"]
    assert statuses == ["error", "ok"]
