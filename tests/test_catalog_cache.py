"""B6: the cache carries a timestamp and rejects entries of the wrong shape."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.models import ModelInfo
from app.services.catalog_service import CACHE_TTL, CatalogService


def _model(model_id: str = "z-image", max_n: int = 6) -> ModelInfo:
    return ModelInfo(
        id=model_id, provider_id="polza", description="d", min_price=1.4, max_price=1.4, max_n=max_n
    )


class TestTimestamp:
    def test_a_written_entry_carries_the_time(self, tmp_path: Path) -> None:
        service = CatalogService(tmp_path / "cache.json")

        service._write_cache("polza", [_model()])

        store = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
        assert "saved_at" in store["polza"]
        assert isinstance(store["polza"]["models"], list)

    def test_the_models_are_still_readable(self, tmp_path: Path) -> None:
        service = CatalogService(tmp_path / "cache.json")
        service._write_cache("polza", [_model()])

        models = service._read_cache("polza")

        assert [m.id for m in models] == ["z-image"]

    def test_an_old_cache_is_still_used_but_logged(self, tmp_path: Path) -> None:
        """A stale catalog beats no catalog when the network is down."""
        path = tmp_path / "cache.json"
        stale = datetime.now(UTC) - CACHE_TTL - timedelta(days=1)
        old = stale.isoformat(timespec="seconds")
        path.write_text(
            json.dumps(
                {"polza": {"saved_at": old, "models": [{"id": "z", "provider_id": "polza"}]}}
            ),
            encoding="utf-8",
        )

        models = CatalogService(path)._read_cache("polza")

        assert [m.id for m in models] == ["z"]

    def test_an_old_bare_list_is_still_readable(self, tmp_path: Path) -> None:
        """Caches written by earlier builds have no timestamp at all."""
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps({"polza": [{"id": "z", "provider_id": "polza", "max_n": 3}]}),
            encoding="utf-8",
        )

        models = CatalogService(path)._read_cache("polza")

        assert len(models) == 1
        assert models[0].max_n == 3

    def test_an_unreadable_timestamp_does_not_hide_the_models(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "polza": {
                        "saved_at": "вчера",
                        "models": [{"id": "z", "provider_id": "polza"}],
                    }
                }
            ),
            encoding="utf-8",
        )

        models = CatalogService(path)._read_cache("polza")

        assert [m.id for m in models] == ["z"]


class TestShape:
    def test_a_number_stored_as_text_is_rejected(self, tmp_path: Path) -> None:
        """It used to reach the parameters panel and fail there."""
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {"polza": {"saved_at": "2026-10-02T10:00:00+00:00",
                           "models": [{"id": "z", "provider_id": "polza", "max_n": "3"}]}}
            ),
            encoding="utf-8",
        )

        assert CatalogService(path)._read_cache("polza") == []

    def test_one_broken_entry_does_not_hide_the_good_ones(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "polza": {
                        "saved_at": "2026-10-02T10:00:00+00:00",
                        "models": [
                            {"id": "good", "provider_id": "polza"},
                            {"id": "bad", "provider_id": "polza", "max_n": "3"},
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        models = CatalogService(path)._read_cache("polza")

        assert [m.id for m in models] == ["good"]

    def test_an_entry_without_an_id_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "polza": {
                        "saved_at": "2026-10-02T10:00:00+00:00",
                        "models": [{"provider_id": "polza"}, "not a dict", 7],
                    }
                }
            ),
            encoding="utf-8",
        )

        assert CatalogService(path)._read_cache("polza") == []

    def test_a_list_where_text_belongs_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "polza": {
                        "saved_at": "2026-10-02T10:00:00+00:00",
                        "models": [{"id": "z", "provider_id": "polza", "resolutions": "1K"}],
                    }
                }
            ),
            encoding="utf-8",
        )

        assert CatalogService(path)._read_cache("polza") == []

    def test_a_float_in_an_integer_field_is_accepted(self, tmp_path: Path) -> None:
        """JSON has one number type, so 3.0 for max_n is not a mistake."""
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "polza": {
                        "saved_at": "2026-10-02T10:00:00+00:00",
                        "models": [{"id": "z", "provider_id": "polza", "max_n": 6.0}],
                    }
                }
            ),
            encoding="utf-8",
        )

        models = CatalogService(path)._read_cache("polza")

        assert len(models) == 1
        assert models[0].max_n == 6
