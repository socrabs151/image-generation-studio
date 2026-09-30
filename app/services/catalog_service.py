"""Loading and caching of provider model catalogs.

The catalog is cached per provider in a single JSON file (``data/catalog_cache.json``)
so the application can start and show models without a network connection. When a
fetch fails, the service falls back to the cache and reports that it did so.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import CATALOG_CACHE_FILE
from app.core.errors import ConfigError
from app.core.models import ModelInfo
from app.logging_setup import get_logger
from app.providers import create_provider
from app.services.json_file import read_json, write_json_atomic

LOGGER = get_logger()


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
            raw = self._read_all().get(provider_id)
        if not isinstance(raw, list):
            return []
        models: list[ModelInfo] = []
        for item in raw:
            if not isinstance(item, dict) or "id" not in item:
                continue
            try:
                models.append(self._model_from_dict(item))
            except (TypeError, ValueError) as exc:
                LOGGER.warning("Skipping a broken cache entry: %s", exc)
        return models

    def _write_cache(self, provider_id: str, models: list[ModelInfo]) -> None:
        with self._lock:
            store = self._read_all()
            store[provider_id] = [self._model_to_dict(model) for model in models]
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
    def _model_from_dict(raw: dict) -> ModelInfo:
        fields = ModelInfo.__dataclass_fields__
        return ModelInfo(**{key: raw[key] for key in fields if key in raw})
