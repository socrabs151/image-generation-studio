"""Loading and caching of provider model catalogs.

The catalog is cached per provider in a single JSON file (``data/catalog_cache.json``)
so the application can start and show models without a network connection. When a
fetch fails, the service falls back to the cache and reports that it did so.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import CATALOG_CACHE_FILE
from app.core.errors import ConfigError
from app.core.models import ModelInfo
from app.logging_setup import get_logger
from app.providers import create_provider
from app.services.json_file import read_json, write_json_atomic

LOGGER = get_logger()

# A cached catalog is a fallback, not a source of truth: it lets the application
# start without a network. Prices are read from it, so its age is worth knowing.
CACHE_TTL = timedelta(days=7)
_MODELS_KEY = "models"
_SAVED_AT_KEY = "saved_at"



class _Unusable:
    """Marker for a cache value that does not fit its field."""

    def __repr__(self) -> str:
        return "<unusable>"


_UNUSABLE = _Unusable()


def _unpack_entry(entry: object) -> tuple[list, datetime | None]:
    """Read a cache entry written by this or by an older build.

    The current format is ``{"saved_at": ..., "models": [...]}``; before the
    timestamp it was a bare list, and those files are still on users' disks.
    """
    if isinstance(entry, list):
        return entry, None
    if not isinstance(entry, dict):
        return [], None
    models = entry.get(_MODELS_KEY)
    if not isinstance(models, list):
        return [], None
    saved_at = entry.get(_SAVED_AT_KEY)
    parsed: datetime | None = None
    if isinstance(saved_at, str):
        try:
            parsed = datetime.fromisoformat(saved_at)
        except ValueError:
            LOGGER.warning("Catalog cache carries an unreadable timestamp: %r", saved_at)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return models, parsed


# Base types the cache can be checked against; a "X | None" field accepts a
# real X or nothing.
_SIMPLE_TYPES = {"bool": bool, "int": int, "float": float, "str": str, "list": list}


def _expected(field: object) -> tuple[type | None, bool]:
    """The base type of a dataclass field and whether ``None`` is allowed.

    ``__dataclass_fields__`` maps a name to a ``Field`` object, so taking
    ``type(default)`` describes the Field, not the value — and every field then
    passed through unchecked.
    """
    annotation = getattr(field, "type", None)
    if not isinstance(annotation, str):
        return None, True
    parts = [part.strip() for part in annotation.split("|")]
    # "list[str]" is a list; the parameter inside it does not matter here.
    base = _SIMPLE_TYPES.get(parts[0].split("[")[0].strip())
    return base, "None" in parts[1:]


def _coerce(value: object, expected: type | None, optional: bool = False) -> object:
    """Narrow a JSON value to the type the field expects, or reject it."""
    if value is None:
        # An optional price is written as null and read back as null.
        return value if optional else _UNUSABLE
    if expected is bool:
        return value if isinstance(value, bool) else _UNUSABLE
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _UNUSABLE
        return int(value)
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _UNUSABLE
        return float(value)
    if expected is str:
        return value if isinstance(value, str) else _UNUSABLE
    if expected is list:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return _UNUSABLE
        return value
    return value


@dataclass(slots=True)
class CatalogResult:
    """Outcome of a catalog load."""

    models: list[ModelInfo]
    from_cache: bool


class CatalogService:
    """Fetch provider catalogs and keep a disk cache."""

    def __init__(self, cache_path: Path = CATALOG_CACHE_FILE) -> None:
        self._cache_path = cache_path
        # Loading a catalog runs in a worker thread, and switching the aggregator
        # starts a second one. Each write replaces the whole file, so two of them
        # racing would collide on Windows and lose a provider's catalog.
        self._lock = threading.Lock()

    def load(
        self, provider_id: str, api_key: str = "", allow_network: bool = True
    ) -> CatalogResult:
        """Return the catalog for a provider, using the cache as a fallback."""
        if allow_network:
            try:
                models = create_provider(provider_id, api_key).fetch_catalog()
                self._write_cache(provider_id, models)
                return CatalogResult(models=models, from_cache=False)
            except Exception:  # noqa: BLE001 - fall back to the cache on any error
                cached = self._read_cache(provider_id)
                if cached:
                    return CatalogResult(models=cached, from_cache=True)
                raise
        cached = self._read_cache(provider_id)
        return CatalogResult(models=cached, from_cache=True)

    # ---------- cache ----------
    def _read_all(self) -> dict:
        if not self._cache_path.exists():
            return {}
        try:
            data = read_json(self._cache_path, "catalog cache")
        except ConfigError as exc:
            # A broken cache is not worth an error dialog: the network fetch has
            # already failed, and there is nothing to fall back to.
            LOGGER.warning("Catalog cache ignored: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _read_cache(self, provider_id: str) -> list[ModelInfo]:
        with self._lock:
            entry = self._read_all().get(provider_id)
        models, saved_at = _unpack_entry(entry)
        if saved_at is not None and datetime.now(UTC) - saved_at > CACHE_TTL:
            LOGGER.warning(
                "The cached catalog of %s is older than %d days; prices may be out of date.",
                provider_id,
                CACHE_TTL.days,
            )
        result: list[ModelInfo] = []
        for item in models:
            model = self._model_from_dict(item)
            if model is not None:
                result.append(model)
        return result

    def _write_cache(self, provider_id: str, models: list[ModelInfo]) -> None:
        with self._lock:
            store = self._read_all()
            store[provider_id] = {
                _SAVED_AT_KEY: datetime.now(UTC).isoformat(timespec="seconds"),
                _MODELS_KEY: [self._model_to_dict(model) for model in models],
            }
            try:
                write_json_atomic(self._cache_path, store)
            except OSError as exc:
                # The models are already in memory. Failing to cache them must not
                # turn a successful load into an error, and must not claim the
                # prices came from the cache.
                LOGGER.warning("Could not write the catalog cache: %s", exc)

    @staticmethod
    def _model_to_dict(model: ModelInfo) -> dict:
        from dataclasses import asdict

        return asdict(model)

    @staticmethod
    def _model_from_dict(raw: object) -> ModelInfo | None:
        """Build a model from a cache entry, or ``None`` when it is unusable.

        The dataclass does not check its arguments, so ``max_n: "3"`` used to be
        stored happily and only failed later, in the parameters panel, as a
        ``TypeError`` in the middle of the interface.
        """
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            return None
        values: dict = {}
        for key, field in ModelInfo.__dataclass_fields__.items():
            if key not in raw:
                continue
            expected, optional = _expected(field)
            value = _coerce(raw[key], expected, optional)
            if value is _UNUSABLE:
                LOGGER.warning("Skipping cache entry %r: %s has the wrong type", raw.get("id"), key)
                return None
            values[key] = value
        try:
            return ModelInfo(**values)
        except TypeError as exc:
            LOGGER.warning("Skipping a broken cache entry: %s", exc)
            return None
