"""Model list helpers: search and favourites.

Qt-free on purpose: the CI runner has no ``libEGL``, so anything imported by the
test suite must not pull in PySide6.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.models import ModelInfo

# How many lately used models the app keeps.
RECENT_LIMIT = 10


def split_key(key: str) -> tuple[str, str]:
    """Split a "provider_id:model_id" key back into its two parts."""
    provider, _, model_id = key.partition(":")
    return provider, model_id


def favourite_key(model: ModelInfo) -> str:
    """How a model is remembered in the favourites list.

    The provider is part of the key because the same model name at two
    aggregators is two different entries.
    """
    return f"{model.provider_id}:{model.id}"


def is_favourite(model: ModelInfo | None, favourites: Iterable[str]) -> bool:
    """Whether the model is in the favourites list."""
    return model is not None and favourite_key(model) in set(favourites)


def matches(model: ModelInfo, needle: str) -> bool:
    """Whether a model matches the search text (case-insensitive)."""
    if not needle:
        return True
    return (
        needle in model.id.lower()
        or needle in (model.description or "").lower()
        or needle in model.provider_id.lower()
    )


def visible_models(
    models: Iterable[ModelInfo], needle: str, favourites: Iterable[str]
) -> list[ModelInfo]:
    """The models to show for a search, favourites first.

    Favourites keep their relative order, the rest follow in catalog order.
    """
    wanted = set(favourites)
    needle = needle.strip().lower()
    found = [model for model in models if matches(model, needle)]
    return [model for model in found if favourite_key(model) in wanted] + [
        model for model in found if favourite_key(model) not in wanted
    ]


def combo_label(model: ModelInfo) -> str:
    """How a model is written in the model combo.

    A favourite is marked with an icon, not with a character, so the label is
    the same for every row.
    """
    return model.display_name()


def toggle_favourite(favourites: Iterable[str], model: ModelInfo) -> list[str]:
    """Add or remove a model from the favourites list, keeping it without duplicates."""
    key = favourite_key(model)
    result = [item for item in favourites if item != key]
    result.append(key)
    return result


def remember_model(
    recents: Iterable[str], model: ModelInfo, limit: int = RECENT_LIMIT
) -> list[str]:
    """Put a model at the head of the lately used list.

    A model used again moves back to the head, so the list stays unique and
    never grows past ``limit``.
    """
    key = favourite_key(model)
    return [key, *[item for item in recents if item != key]][:limit]


def recent_models(
    models: Iterable[ModelInfo], recents: Iterable[str]
) -> list[tuple[ModelInfo, bool]]:
    """The lately used models as (model, is_in_current_catalog) pairs.

    Models that are not in the catalog right now are kept, marked as missing:
    a model can disappear from an aggregator between two sessions, and silently
    dropping it would hide why the entry is there.
    """
    by_key = {favourite_key(model): model for model in models}
    found: list[tuple[ModelInfo, bool]] = []
    for key in recents:
        model = by_key.get(key)
        if model is not None:
            found.append((model, True))
        else:
            provider, model_id = split_key(key)
            if model_id:
                found.append((ModelInfo(id=model_id, provider_id=provider), False))
    return found
