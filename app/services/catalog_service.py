"""Loading and caching of provider model catalogs.

The catalog is cached per provider in a single JSON file (``data/catalog_cache.json``)
so the application can start and show models without a network connection. When a
fetch fails, the service falls back to the cache and reports that it did so.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import CATALOG_CACHE_FILE
from app.core.models import ModelInfo
from app.providers import create_provider


@dataclass(slots=True)
class CatalogResult:
    """Outcome of a catalog load."""

    models: list[ModelInfo]
    from_cache: bool


class CatalogService:
    """Fetch provider catalogs and keep a disk cache."""

    def __init__(self, cache_path: Path = CATALOG_CACHE_FILE) -> None:
        self._cache_path = cache_path

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
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_cache(self, provider_id: str) -> list[ModelInfo]:
        raw = self._read_all().get(provider_id)
        if not raw:
            return []
        return [self._model_from_dict(item) for item in raw]

    def _write_cache(self, provider_id: str, models: list[ModelInfo]) -> None:
        store = self._read_all()
        store[provider_id] = [self._model_to_dict(model) for model in models]
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(store, ensure_ascii=False, indent=2)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._cache_path.parent, delete=False, suffix=".tmp"
        )
        try:
            with handle:
                handle.write(text)
            os.replace(handle.name, self._cache_path)
        except OSError:
            Path(handle.name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _model_to_dict(model: ModelInfo) -> dict:
        from dataclasses import asdict

        return asdict(model)

    @staticmethod
    def _model_from_dict(raw: dict) -> ModelInfo:
        fields = ModelInfo.__dataclass_fields__
        return ModelInfo(**{key: raw[key] for key in fields if key in raw})
