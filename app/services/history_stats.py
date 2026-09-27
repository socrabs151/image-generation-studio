"""Totals and export for the generation history.

Kept apart from the dialog and free of Qt so the numbers and the exported files can
be tested without a display. The images themselves are not exported: the records
only carry the paths of the files that were already saved.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.services.history_store import HistoryRecord

EXPORT_COLUMNS = (
    "id",
    "timestamp",
    "provider_id",
    "model",
    "prompt",
    "n",
    "cost_rub",
    "status",
    "error",
    "duration_seconds",
    "file_paths",
    "request",
)


@dataclass(frozen=True, slots=True)
class HistoryTotals:
    """Aggregated numbers over a set of history records."""

    attempts: int = 0
    succeeded: int = 0
    failed: int = 0
    images: int = 0
    spent_rub: float = 0.0
    unpriced: int = 0

    def summary(self) -> str:
        """One-line description for the history window."""
        return (
            f"{self.attempts} attempts · {self.succeeded} ok · {self.failed} failed · "
            f"{self.images} images · {self.spent_rub:.2f} ₽"
        )


@dataclass(frozen=True, slots=True)
class GroupTotal:
    """Spend and count for one model or provider."""

    name: str
    attempts: int
    images: int
    spent_rub: float


def summarize(records: Iterable[HistoryRecord]) -> HistoryTotals:
    """Total spend, counts and image number over ``records``."""
    attempts = succeeded = failed = images = unpriced = 0
    spent = 0.0
    for record in records:
        attempts += 1
        if record.status == "ok":
            succeeded += 1
            images += len(record.file_paths) or record.n
        else:
            failed += 1
        if record.cost_rub is None:
            unpriced += 1
        else:
            spent += record.cost_rub
    return HistoryTotals(
        attempts=attempts,
        succeeded=succeeded,
        failed=failed,
        images=images,
        spent_rub=spent,
        unpriced=unpriced,
    )


def _group(records: Iterable[HistoryRecord], name_of) -> list[GroupTotal]:
    buckets: dict[str, list[int]] = {}
    for record in records:
        name = name_of(record) or "(unknown)"
        bucket = buckets.setdefault(name, [0, 0, 0.0])
        bucket[0] += 1
        bucket[1] += len(record.file_paths) if record.status == "ok" else 0
        if record.cost_rub:
            bucket[2] += record.cost_rub
    return [
        GroupTotal(name=name, attempts=data[0], images=data[1], spent_rub=data[2])
        for name, data in buckets.items()
    ]


def totals_by_provider(records: Iterable[HistoryRecord]) -> list[GroupTotal]:
    """Spend per provider, most expensive first."""
    groups = _group(records, lambda record: record.provider_id)
    return sorted(groups, key=lambda group: (-group.spent_rub, group.name))


def totals_by_model(records: Iterable[HistoryRecord]) -> list[GroupTotal]:
    """Spend per model, most expensive first."""
    groups = _group(records, lambda record: record.model)
    return sorted(groups, key=lambda group: (-group.spent_rub, group.name))


def filter_records(
    records: Iterable[HistoryRecord],
    query: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
) -> list[HistoryRecord]:
    """Narrow ``records`` down to a search phrase and the chosen facets.

    The phrase is matched case-insensitively against the prompt and the model. Empty
    facet values mean "any".
    """
    needle = query.strip().lower()
    result = []
    for record in records:
        if needle and needle not in record.prompt.lower() and needle not in record.model.lower():
            continue
        if provider and record.provider_id != provider:
            continue
        if model and record.model != model:
            continue
        if status and record.status != status:
            continue
        result.append(record)
    return result


def filter_options(records: Iterable[HistoryRecord]) -> tuple[list[str], list[str], list[str]]:
    """Distinct providers, models and statuses, sorted for the filter controls."""
    records = list(records)
    providers = sorted({record.provider_id for record in records if record.provider_id})
    models = sorted({record.model for record in records if record.model})
    statuses = sorted({record.status for record in records if record.status})
    return providers, models, statuses


def to_csv(records: Sequence[HistoryRecord]) -> str:
    """Render records as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for record in records:
        writer.writerow(_csv_row(record))
    return buffer.getvalue()


def _csv_row(record: HistoryRecord) -> list[str]:
    return [
        record.id,
        record.timestamp,
        record.provider_id,
        record.model,
        record.prompt,
        str(record.n),
        "" if record.cost_rub is None else f"{record.cost_rub:.2f}",
        record.status,
        record.error,
        "" if record.duration_seconds is None else f"{record.duration_seconds:.1f}",
        "; ".join(record.file_paths),
        json.dumps(record.request, ensure_ascii=False, sort_keys=True),
    ]


def to_json(records: Sequence[HistoryRecord]) -> str:
    """Render records as a JSON document."""
    payload = {
        "version": 1,
        "records": [
            {
                "id": record.id,
                "timestamp": record.timestamp,
                "provider_id": record.provider_id,
                "model": record.model,
                "prompt": record.prompt,
                "n": record.n,
                "cost_rub": record.cost_rub,
                "file_paths": list(record.file_paths),
                "status": record.status,
                "error": record.error,
                "duration_seconds": record.duration_seconds,
                "request": dict(record.request),
            }
            for record in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
