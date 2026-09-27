"""Tests for the history store: request snapshots, ids, deletion and old files."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.models import GenerationRequest
from app.services.history_store import (
    HistoryRecord,
    HistoryStore,
    request_snapshot,
)


def _record(index: int = 0, **overrides) -> HistoryRecord:
    defaults = dict(
        timestamp=f"2026-01-01T00:00:{index:02d}",
        provider_id="aitunnel",
        model="gpt-image-1",
        prompt=f"prompt {index}",
    )
    defaults.update(overrides)
    return HistoryRecord(**defaults)


def test_add_assigns_an_id(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    first = store.add(_record(0))
    second = store.add(_record(1))

    assert first.id
    assert first.id != second.id


def test_add_fills_a_missing_timestamp(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    record = store.add(HistoryRecord(provider_id="polza", model="m", prompt="p"))

    assert record.timestamp


def test_delete_removes_one_record(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    first = store.add(_record(0))
    store.add(_record(1))

    assert store.delete(first.id) is True
    assert [record.prompt for record in store.records()] == ["prompt 1"]
    assert len(HistoryStore(path).load()) == 1


def test_delete_unknown_id_reports_nothing_removed(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.add(_record(0))

    assert store.delete("нет-такого") is False
    assert len(store.records()) == 1


def test_old_file_without_snapshot_still_loads(tmp_path: Path) -> None:
    # Records written by schema 1 have no id, snapshot or duration.
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "timestamp": "2026-01-01T00:00:00",
                        "provider_id": "aitunnel",
                        "model": "muse-image",
                        "prompt": "старая запись",
                        "n": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    record = HistoryStore(path).load()[0]

    assert record.prompt == "старая запись"
    assert record.id, "у старой записи должен появиться идентификатор"
    assert record.request == {}
    assert record.duration_seconds is None
    assert record.has_request_snapshot is False


def test_snapshot_survives_a_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.add(
        _record(
            0,
            request={"n": 3, "aspect_ratio": "16:9"},
            duration_seconds=12.5,
        )
    )

    record = HistoryStore(path).load()[0]

    assert record.request == {"n": 3, "aspect_ratio": "16:9"}
    assert record.duration_seconds == 12.5
    assert record.has_request_snapshot is True


def test_request_snapshot_captures_every_parameter() -> None:
    request = GenerationRequest(
        provider_id="polza",
        model="bytedance/seedream-4",
        prompt="кот",
        n=3,
        quality="high",
        resolution="2K",
        aspect_ratio="16:9",
        size="1024x1024",
        output_format="png",
        background="transparent",
        seed=42,
        passthrough={"isEnhance": True},
        reference_paths=["C:/tmp/ref.png"],
    )

    snapshot = request_snapshot(request)

    assert snapshot["n"] == 3
    assert snapshot["quality"] == "high"
    assert snapshot["resolution"] == "2K"
    assert snapshot["aspect_ratio"] == "16:9"
    assert snapshot["size"] == "1024x1024"
    assert snapshot["output_format"] == "png"
    assert snapshot["background"] == "transparent"
    assert snapshot["seed"] == 42
    assert snapshot["passthrough"] == {"isEnhance": True}
    assert snapshot["reference_paths"] == ["C:/tmp/ref.png"]


def test_request_snapshot_omits_reference_bytes() -> None:
    request = GenerationRequest(
        provider_id="polza",
        model="m",
        prompt="p",
        input_references=[b"\x89PNG\r\n" + b"0" * 32],
    )

    snapshot = request_snapshot(request)

    assert "input_references" not in snapshot


def test_snapshot_copies_the_passthrough_mapping() -> None:
    passthrough = {"upscale_factor": "2"}
    request = GenerationRequest(
        provider_id="polza", model="m", prompt="p", passthrough=passthrough
    )

    snapshot = request_snapshot(request)
    passthrough["upscale_factor"] = "4"

    assert snapshot["passthrough"] == {"upscale_factor": "2"}
