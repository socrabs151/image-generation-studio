"""Persistent storage for generation history (``data/history.json``).

Records are stored newest-first and trimmed to a configured limit. Writes are atomic.
A record keeps the full parameter snapshot of the request so that the interface can
restore it later; the generated images themselves are not stored, only their paths,
because the files already live in the output folder.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import HISTORY_FILE, HISTORY_SCHEMA_VERSION
from app.core.errors import ConfigError
from app.core.models import GenerationRequest


@dataclass(slots=True)
class HistoryRecord:
    """One generation attempt."""

    id: str = ""
    timestamp: str = ""
    provider_id: str = ""
    model: str = ""
    prompt: str = ""
    n: int = 1
    cost_rub: float | None = None
    file_paths: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str = ""
    # Snapshot of the request parameters, see :func:`request_snapshot`.
    request: dict = field(default_factory=dict)
    duration_seconds: float | None = None

    @property
    def has_request_snapshot(self) -> bool:
        """Whether the parameters behind this attempt were recorded."""
        return bool(self.request)


def request_snapshot(request: GenerationRequest) -> dict:
    """Capture the parameters of a request for the history.

    Reference images are left out on purpose: the bytes would be useless in the
    history file, and their paths are kept in ``reference_paths`` instead.
    """
    return {
        "n": request.n,
        "quality": request.quality,
        "resolution": request.resolution,
        "aspect_ratio": request.aspect_ratio,
        "size": request.size,
        "output_format": request.output_format,
        "background": request.background,
        "seed": request.seed,
        "passthrough": dict(request.passthrough),
        "reference_paths": list(request.reference_paths),
    }


class HistoryStore:
    """Load, append and trim generation history."""

    def __init__(self, path: Path = HISTORY_FILE) -> None:
        self._path = path
        self._records: list[HistoryRecord] = []
        self._loaded = False

    def load(self) -> list[HistoryRecord]:
        """Load history from disk (empty list when the file is absent)."""
        if not self._path.exists():
            self._records = []
            self._loaded = True
            return self._records
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read history file: {exc}") from exc
        self._records = [self._record_from_dict(item) for item in raw.get("records", [])]
        self._loaded = True
        return self._records

    def records(self) -> list[HistoryRecord]:
        """Return the in-memory records, loading them first if needed."""
        if not self._loaded:
            self.load()
        return self._records

    def add(self, record: HistoryRecord, limit: int = 200) -> HistoryRecord:
        """Prepend a record, trim to ``limit``, persist and return it."""
        self.records()
        if not record.id:
            record.id = uuid.uuid4().hex[:12]
        if not record.timestamp:
            record.timestamp = now_iso()
        self._records.insert(0, record)
        if limit > 0:
            del self._records[limit:]
        self.save()
        return record

    def delete(self, record_id: str, limit: int = 200) -> bool:
        """Remove one record by id; report whether something was removed."""
        records = self.records()
        remaining = [record for record in records if record.id != record_id]
        if len(remaining) == len(records):
            return False
        self._records = remaining
        self.save()
        return True

    def clear(self) -> None:
        """Remove all records and persist."""
        self._records = []
        self._loaded = True
        self.save()

    def save(self) -> None:
        """Write history atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "records": [asdict(record) for record in self._records],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._path.parent, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                handle.write(text)
            os.replace(handle.name, self._path)
        except OSError:
            Path(handle.name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _record_from_dict(raw: dict) -> HistoryRecord:
        return HistoryRecord(
            # Records written before schema 2 have no id; one is invented so the
            # window can address them, and it is persisted on the next write.
            id=raw.get("id") or uuid.uuid4().hex[:12],
            timestamp=raw.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
            provider_id=raw.get("provider_id", ""),
            model=raw.get("model", ""),
            prompt=raw.get("prompt", ""),
            n=int(raw.get("n", 1)),
            cost_rub=raw.get("cost_rub"),
            file_paths=list(raw.get("file_paths") or []),
            status=raw.get("status", "ok"),
            error=raw.get("error", ""),
            request=dict(raw.get("request") or {}),
            duration_seconds=raw.get("duration_seconds"),
        )


def now_iso() -> str:
    """Current timestamp in ISO format (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")
