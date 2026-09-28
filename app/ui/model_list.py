"""Model list helpers: search and favourites.

Qt-free on purpose: the CI runner has no ``libEGL``, so anything imported by the
test suite must not pull in PySide6.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.models import ModelInfo

FAVOURITE_MARK = "★ "
UNMARKED = "☆"


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


def combo_label(model: ModelInfo, favourites: Iterable[str]) -> str:
    """How a model is written in the model combo, with the favourite mark."""
    prefix = FAVOURITE_MARK if is_favourite(model, favourites) else ""
    return prefix + model.display_name()


def toggle_favourite(favourites: Iterable[str], model: ModelInfo) -> list[str]:
    """Add or remove a model from the favourites list, keeping it without duplicates."""
    key = favourite_key(model)
    result = [item for item in favourites if item != key]
    result.append(key)
    return result
