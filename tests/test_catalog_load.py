"""CatalogService.load(): the public path, not the private helpers.

Until now the tests called ``_write_cache``/``_read_cache`` directly, which never
crossed the part that matters to a user: the network fails, the application must
still start and show the models it saw last time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.services.catalog_service as module
from app.core.errors import ConfigError
from app.core.models import ModelInfo
from app.services.catalog_service import CatalogService


class _Provider:
    """Fetches a catalog, or fails the way a real aggregator fails."""

    def __init__(self, models: list[ModelInfo] | Exception) -> None:
        self.models = models
        self.calls = 0

    def fetch_catalog(self) -> list[ModelInfo]:
        self.calls += 1
        if isinstance(self.models, Exception):
            raise self.models
        return self.models


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "catalog_cache.json"


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch):
    """Put a provider where create_provider is called, and hand it back."""

    def install(provider: _Provider) -> _Provider:
        monkeypatch.setattr(module, "create_provider", lambda *_, **__: provider)
        return provider

    return install


def _model(identifier: str = "seedream-4") -> ModelInfo:
    return ModelInfo(id=identifier, provider_id="polza", max_price=2.5)


class TestTheNetworkAnswers:
    def test_the_fetched_models_are_returned_and_cached(
        self, cache: Path, fetched
    ) -> None:
        service = CatalogService(cache)
        provider = fetched(_Provider([_model()]))

        result = service.load("polza", "key")

        assert result.from_cache is False
        assert [model.id for model in result.models] == ["seedream-4"]
        assert provider.calls == 1

        second = CatalogService(cache).load("polza", "key", allow_network=False)
        assert [model.id for model in second.models] == ["seedream-4"]

    def test_a_second_load_replaces_the_provider_entry(
        self, cache: Path, fetched
    ) -> None:
        service = CatalogService(cache)
        # The first load fills the cache, the second replaces it. The stub must be
        # in place for both: without it the real aggregator answers over the network.
        provider = fetched(_Provider([_model("seedream-4")]))
        service.load("polza", "key")

        fetched(_Provider([_model("imagen"), _model("nanobanana")]))
        service.load("polza", "key")
        assert provider.calls == 1

        cached = CatalogService(cache).load("polza", allow_network=False)
        assert [model.id for model in cached.models] == ["imagen", "nanobanana"]


class TestTheNetworkFails:
    def test_the_cached_catalog_is_served_instead(
        self, cache: Path, fetched
    ) -> None:
        """The point of the cache: the application starts without a network."""
        service = CatalogService(cache)
        fetched(_Provider([_model()]))
        service.load("polza", "key")

        fetched(_Provider(ConfigError("the aggregator is unreachable")))
        result = service.load("polza", "key")

        assert result.from_cache is True
        assert [model.id for model in result.models] == ["seedream-4"]

    def test_a_broken_cache_file_does_not_crash_the_load(
        self, cache: Path, fetched
    ) -> None:
        cache.write_text("{not json at all", encoding="utf-8")
        fetched(_Provider(ConfigError("no network")))

        with pytest.raises(ConfigError):
            """No cache to fall back to means the original error must surface."""

            CatalogService(cache).load("polza", "key")

        assert list(cache.parent.glob("catalog_cache.json*")), "the file is kept for inspection"

    def test_an_empty_catalog_in_the_cache_is_not_a_fallback(
        self, cache: Path, fetched
    ) -> None:
        """An empty list means 'the provider has no models', not 'we know nothing'."""
        service = CatalogService(cache)
        fetched(_Provider([_model()]))
        service.load("polza", "key")  # writes one model
        service._write_cache("polza", [])

        fetched(_Provider(ConfigError("no network")))

        with pytest.raises(ConfigError):
            CatalogService(cache).load("polza", "key")

    def test_a_provider_without_a_cache_lets_the_error_through(self, cache: Path, fetched) -> None:
        fetched(_Provider(ConfigError("the aggregator is unreachable")))

        with pytest.raises(ConfigError):
            CatalogService(cache).load("unknown-provider", "key")


class TestOfflineLoads:
    def test_nothing_is_requested_from_the_network(
        self, cache: Path, fetched
    ) -> None:
        service = CatalogService(cache)
        service._write_cache("polza", [_model()])
        provider = fetched(_Provider([_model("must-not-be-used")]))

        result = service.load("polza", "key", allow_network=False)

        assert result.from_cache is True
        assert provider.calls == 0
        assert [model.id for model in result.models] == ["seedream-4"]

    def test_an_unknown_provider_offline_is_an_empty_catalog_not_a_crash(
        self, cache: Path
    ) -> None:
        result = CatalogService(cache).load("unknown-provider", allow_network=False)

        assert result.models == []
        assert result.from_cache is True


class TestUnwritableCache:
    def test_a_successful_fetch_is_not_undone_by_a_cache_failure(
        self, cache: Path, fetched, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The models are in memory; losing the cache must not lose the load."""
        service = CatalogService(cache)

        def failing(path: Path, _data: object) -> None:
            raise OSError("the disk is full")

        monkeypatch.setattr(module, "write_json_atomic", failing)
        provider = fetched(_Provider([_model()]))

        result = service.load("polza", "key")

        assert result.from_cache is False, "a failed cache write must not claim a cache hit"
        assert [model.id for model in result.models] == ["seedream-4"]
        assert provider.calls == 1

    def test_a_failed_cache_write_is_reported(
        self, cache: Path, fetched, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """Silent: the models show up and next start without a network has nothing."""
        service = CatalogService(cache)
        fetched(_Provider([_model()]))

        def failing(path: Path, _data: object) -> None:
            raise OSError("the disk is full")

        monkeypatch.setattr(module, "write_json_atomic", failing)

        with caplog.at_level("WARNING"):
            CatalogService(cache).load("polza", "key")

        assert any("catalog cache" in record.message for record in caplog.records), (
            "a cache that could not be written must leave a trace"
        )
