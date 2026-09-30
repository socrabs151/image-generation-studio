"""Tests for concurrent access to the stores.

A generation finishes in a worker thread while the history window works in the
GUI thread, and switching the aggregator starts a second worker. Both rewrite the
whole file, so without a lock two ``os.replace`` calls to one target collide on
Windows ("Access is denied") and a paid record is lost.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.core.models import ModelInfo
from app.services.catalog_service import CatalogService
from app.services.history_store import HistoryRecord, HistoryStore


def _fill_two_threads(rounds: int = 25) -> tuple[list[str], list[str]]:
    """Add records from two threads at once and report what each saw."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "history.json"
    store = HistoryStore(path)
    errors: list[str] = []
    done: list[str] = []
    barrier = threading.Barrier(2)

    def worker(tag: str) -> None:
        barrier.wait()
        for index in range(rounds):
            try:
                store.add(HistoryRecord(prompt=f"{tag}-{index}", model="muse-image"))
                done.append(f"{tag}-{index}")
            except OSError as exc:
                errors.append(f"{tag}-{index}: {exc}")

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return done, errors


def test_no_record_is_lost_when_two_threads_add() -> None:
    done, errors = _fill_two_threads()

    assert not errors, f"a write failed under concurrency: {errors[:3]}"
    assert len(done) == 50, "every add has to be acknowledged"


def test_the_file_holds_every_record_after_concurrent_adds() -> None:
    """The in-memory list and the file must agree, and a second store has to see
    the same records: that is what "not lost" means for the next run."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "history.json"
    store = HistoryStore(path)
    barrier = threading.Barrier(2)

    def worker(tag: str) -> None:
        barrier.wait()
        for index in range(20):
            store.add(HistoryRecord(prompt=f"{tag}-{index}", model="m"))

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    on_disk = json.loads(path.read_text(encoding="utf-8"))["records"]
    reread = HistoryStore(path).load()

    assert len(on_disk) == 40, "both threads' records have to be in the file"
    assert len(reread) == 40
    prompts = {record.prompt for record in reread}
    assert prompts == {f"{tag}-{i}" for tag in ("a", "b") for i in range(20)}


def test_a_delete_does_not_drop_a_concurrent_add() -> None:
    """The window deletes an entry while a generation is being recorded. The
    record of the paid generation has to survive."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "history.json"
    store = HistoryStore(path)
    doomed = store.add(HistoryRecord(prompt="old", model="m"))
    added = threading.Event()
    errors: list[str] = []

    def worker() -> None:
        try:
            store.add(HistoryRecord(prompt="paid", model="m"))
        except OSError as exc:  # pragma: no cover - only on failure
            errors.append(str(exc))
        finally:
            added.set()

    thread = threading.Thread(target=worker)
    thread.start()
    store.delete(doomed.id)
    added.wait(timeout=10)
    thread.join(timeout=10)

    assert not errors
    assert [record.prompt for record in store.records()] == ["paid"]


def test_two_catalogs_do_not_overwrite_each_other() -> None:
    """Writing one aggregator's catalog must not drop the other's: the catalog
    of the other one is then gone until the next successful fetch."""
    import tempfile

    path = Path(tempfile.mkdtemp()) / "catalog.json"
    service = CatalogService(path)
    first = [ModelInfo(id="a1", provider_id="aitunnel", max_price=1.0)]
    second = [ModelInfo(id="b1", provider_id="polza", max_price=2.0)]

    service._write_cache("aitunnel", first)
    service._write_cache("polza", second)

    assert [m.id for m in service._read_cache("aitunnel")] == ["a1"]
    assert [m.id for m in service._read_cache("polza")] == ["b1"]


def test_concurrent_catalog_writes_keep_both_providers() -> None:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "catalog.json"
    service = CatalogService(path)
    barrier = threading.Barrier(2)
    errors: list[str] = []

    def worker(provider_id: str, model_id: str) -> None:
        barrier.wait()
        try:
            service._write_cache(
                provider_id, [ModelInfo(id=model_id, provider_id=provider_id, max_price=1.0)]
            )
        except OSError as exc:  # pragma: no cover - only on failure
            errors.append(str(exc))

    threads = [
        threading.Thread(target=worker, args=("aitunnel", "a1")),
        threading.Thread(target=worker, args=("polza", "b1")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    cached = json.loads(path.read_text(encoding="utf-8"))
    assert set(cached) == {"aitunnel", "polza"}, (
        f"one provider's catalog was lost: {sorted(cached)}"
    )
