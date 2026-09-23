"""Persistent storage for generation history (``data/history.json``).

Records are stored newest-first and trimmed to a configured limit. Writes are atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import HISTORY_FILE, HISTORY_SCHEMA_VERSION
from app.core.errors import ConfigError


@dataclass(slots=True)
class HistoryRecord:
    """One generation attempt."""

    timestamp: str
    provider_id: str
    model: str
    prompt: str
    n: int = 1
    cost_rub: float | None = None
    file_paths: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str = ""


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

    def add(self, record: HistoryRecord, limit: int = 200) -> None:
        """Prepend a record, trim to ``limit`` and persist."""
        self.records()
        self._records.insert(0, record)
        if limit > 0:
            del self._records[limit:]
        self.save()

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
            timestamp=raw.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
            provider_id=raw.get("provider_id", ""),
            model=raw.get("model", ""),
            prompt=raw.get("prompt", ""),
            n=int(raw.get("n", 1)),
            cost_rub=raw.get("cost_rub"),
            file_paths=list(raw.get("file_paths") or []),
            status=raw.get("status", "ok"),
            error=raw.get("error", ""),
        )


def now_iso() -> str:
    """Current timestamp in ISO format (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")
