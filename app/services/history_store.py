"""Persistent storage for generation history (``data/history.json``).

Records are stored newest-first and trimmed to a configured limit. Writes are atomic.
A record keeps the full parameter snapshot of the request so that the interface can
restore it later; the generated images themselves are not stored, only their paths,
because the files already live in the output folder.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import HISTORY_FILE, HISTORY_SCHEMA_VERSION
from app.core.errors import ConfigError
from app.core.models import GenerationRequest
from app.services.json_file import read_json, write_json_atomic


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

    def __init__(self, path: Path | None = None) -> None:
        # Resolved at call time, not as a default argument: a default is bound when
        # the module is imported, which makes the store impossible to retarget.
        self._path = path or HISTORY_FILE
        self._records: list[HistoryRecord] = []
        self._loaded = False
        # The generation runs in a worker thread and the history window works in
        # the GUI thread, so both can add a record at the same time. Each of them
        # rewrites the whole file, and two os.replace calls to one target collide
        # on Windows with "Access is denied", which loses the record.
        self._lock = threading.RLock()

    def load(self) -> list[HistoryRecord]:
        """Load history from disk (empty list when the file is absent).

        A file that does not parse is moved aside, so the broken bytes survive
        and the app can start. It is a history of paid generations, so throwing
        it away quietly is not an option.
        """
        if not self._path.exists():
            self._records = []
            self._loaded = True
            return list(self._records)
        raw = read_json(self._path, "history")
        if not isinstance(raw, dict):
            raise ConfigError("The history file must contain a JSON object.")
        self._records = [
            self._record_from_dict(item)
            for item in raw.get("records", [])
            if isinstance(item, dict)
        ]
        self._loaded = True
        return list(self._records)

    def records(self) -> list[HistoryRecord]:
        """Return a snapshot of the records, loading them first if needed.

        A copy on purpose: the history window iterates the result in the GUI thread
        while a worker thread may prepend a new record.
        """
        if not self._loaded:
            with self._lock:
                self._load_locked()
        with self._lock:
            return list(self._records)

    def add(self, record: HistoryRecord, limit: int = 200) -> HistoryRecord:
        """Prepend a record, trim to ``limit``, persist and return it."""
        # The whole read-modify-write is under one lock: two workers finishing
        # at the same time would otherwise both read the same old list, and the
        # second write would drop the first record.
        with self._lock:
            self._load_locked()
            if not record.id:
                record.id = uuid.uuid4().hex[:12]
            if not record.timestamp:
                record.timestamp = now_iso()
            self._records.insert(0, record)
            if limit > 0:
                del self._records[limit:]
            self._save_locked()
        return record

    def delete(self, record_id: str, limit: int = 200) -> bool:
        """Remove one record by id; report whether something was removed."""
        with self._lock:
            self._load_locked()
            remaining = [record for record in self._records if record.id != record_id]
            if len(remaining) == len(self._records):
                return False
            self._records = remaining
            self._save_locked()
        return True

    def clear(self) -> None:
        """Remove all records and persist."""
        with self._lock:
            self._records = []
            self._loaded = True
            self._save_locked()

    def save(self) -> None:
        """Write history atomically."""
        with self._lock:
            self._save_locked()

    def _load_locked(self) -> None:
        if not self._loaded:
            self.load()

    def _save_locked(self) -> None:
        write_json_atomic(
            self._path,
            {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "records": [asdict(record) for record in self._records],
            },
        )

    @staticmethod
    def _record_from_dict(raw: dict) -> HistoryRecord:
        # A history file is written by many versions of the app and edited by
        # hand during support cases, so every field is read defensively: one
        # odd record must not cost the user the whole history window.
        return HistoryRecord(
            # Records written before schema 2 have no id; one is invented so the
            # window can address them, and it is persisted on the next write.
            id=raw.get("id") or uuid.uuid4().hex[:12],
            timestamp=raw.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
            provider_id=raw.get("provider_id", ""),
            model=raw.get("model", ""),
            prompt=raw.get("prompt", ""),
            n=_as_int(raw.get("n"), 1),
            cost_rub=_as_float(raw.get("cost_rub")),
            file_paths=[str(item) for item in (raw.get("file_paths") or [])],
            status=raw.get("status", "ok"),
            error=raw.get("error", ""),
            request=dict(raw.get("request") or {}),
            duration_seconds=_as_float(raw.get("duration_seconds")),
        )


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _as_float(value: object) -> float | None:
    """A price that cannot be read stays unknown, never zero: a wrong sum in
    the history is worse than a missing one."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def now_iso() -> str:
    """Current timestamp in ISO format (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")
