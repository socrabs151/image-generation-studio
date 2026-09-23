"""Tests for the generation history store."""

from __future__ import annotations

from pathlib import Path

from app.services.history_store import HistoryRecord, HistoryStore


def _record(index: int) -> HistoryRecord:
    return HistoryRecord(
        timestamp=f"2026-01-01T00:00:{index:02d}",
        provider_id="aitunnel",
        model="gpt-image-1",
        prompt=f"prompt {index}",
    )


def test_add_prepends_and_limits(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    for index in range(5):
        store.add(_record(index), limit=3)

    records = store.records()
    assert len(records) == 3
    # newest first
    assert records[0].prompt == "prompt 4"
    assert records[-1].prompt == "prompt 2"


def test_clear(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.json")
    store.add(_record(0), limit=10)
    store.clear()
    assert store.records() == []


def test_persistence(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    HistoryStore(path).add(_record(0), limit=10)
    assert len(HistoryStore(path).load()) == 1
