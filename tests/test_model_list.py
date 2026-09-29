"""Tests for the model search and favourites.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, so a test
that imports Qt fails at collection.
"""

from __future__ import annotations

import json

from app.core.models import ModelInfo
from app.services.settings_store import Settings, SettingsStore
from app.ui.model_list import (
    RECENT_LIMIT,
    combo_label,
    favourite_key,
    is_favourite,
    matches,
    recent_models,
    remember_model,
    split_key,
    toggle_favourite,
    visible_models,
)


def model(
    model_id: str, provider: str = "aitunnel", description: str = ""
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        provider_id=provider,
        description=description,
        min_price=0.0,
        max_price=1.0,
        max_n=4,
    )


CATALOG = [
    model("muse-image", description="Фотореалистичные изображения"),
    model("gemini-3.1-flash-image", description="Быстрая генерация"),
    model("seedream-4", provider="polza", description="Редактирование изображений"),
    model("gpt-image-1", description="Точное следование промпту"),
]


def ids(models: list[ModelInfo]) -> list[str]:
    return [item.id for item in models]


# ---------- search ----------


def test_empty_search_keeps_catalog_order() -> None:
    assert ids(visible_models(CATALOG, "", [])) == ids(CATALOG)


def test_search_matches_model_id_case_insensitively() -> None:
    found = visible_models(CATALOG, "GEMINI", [])
    assert ids(found) == ["gemini-3.1-flash-image"]


def test_search_matches_description() -> None:
    found = visible_models(CATALOG, "редактирование", [])
    assert ids(found) == ["seedream-4"]


def test_search_matches_provider() -> None:
    found = visible_models(CATALOG, "polza", [])
    assert ids(found) == ["seedream-4"]


def test_search_ignores_surrounding_spaces() -> None:
    assert ids(visible_models(CATALOG, "  muse  ", [])) == ["muse-image"]


def test_search_without_matches_is_empty() -> None:
    assert visible_models(CATALOG, "нет такого", []) == []


def test_matches_accepts_empty_needle_for_every_model() -> None:
    assert all(matches(item, "") for item in CATALOG)


def test_missing_description_does_not_break_the_search() -> None:
    bare = model("no-description", description="")
    assert matches(bare, "no-description") is True
    assert matches(bare, "описание") is False


# ---------- favourites ----------


def test_favourite_key_includes_the_provider() -> None:
    # The same model at two aggregators is two separate favourites.
    assert favourite_key(model("muse-image", "aitunnel")) == "aitunnel:muse-image"
    assert favourite_key(model("muse-image", "polza")) == "polza:muse-image"


def test_is_favourite_compares_the_full_key() -> None:
    favorites = ["aitunnel:muse-image"]
    assert is_favourite(model("muse-image", "aitunnel"), favorites) is True
    assert is_favourite(model("muse-image", "polza"), favorites) is False
    assert is_favourite(None, favorites) is False


def test_favourites_come_first_when_the_search_is_empty() -> None:
    found = visible_models(CATALOG, "", ["aitunnel:gpt-image-1"])
    assert ids(found) == ["gpt-image-1", "muse-image", "gemini-3.1-flash-image", "seedream-4"]


def test_favourites_come_first_inside_a_search_result() -> None:
    # "image" matches three models, the favourite one leads the result.
    found = visible_models(CATALOG, "image", ["aitunnel:gpt-image-1"])
    assert ids(found)[0] == "gpt-image-1"
    assert len(found) == 3


def test_favourite_of_another_provider_is_not_a_match() -> None:
    # The favourite key carries the provider, so the Polza key does not mark
    # the AITUNNEL model with the same name as a favourite.
    same_name = [model("muse-image", "aitunnel"), model("muse-image", "polza")]
    found = visible_models(same_name, "", ["polza:muse-image"])
    assert [f"{item.provider_id}:{item.id}" for item in found] == [
        "polza:muse-image",
        "aitunnel:muse-image",
    ]


def test_favourites_do_not_resurrect_filtered_out_models() -> None:
    found = visible_models(CATALOG, "gemini", ["aitunnel:muse-image"])
    assert ids(found) == ["gemini-3.1-flash-image"]


def test_toggle_favourite_adds_and_removes_without_duplicates() -> None:
    target = model("muse-image")
    added = toggle_favourite([], target)
    assert added == ["aitunnel:muse-image"]
    assert toggle_favourite(added, target) == ["aitunnel:muse-image"]
    assert toggle_favourite(added + ["aitunnel:muse-image"], target) == ["aitunnel:muse-image"]


def test_toggle_favourite_keeps_the_other_entries() -> None:
    added = toggle_favourite(["aitunnel:gpt-image-1"], model("muse-image"))
    assert added == ["aitunnel:gpt-image-1", "aitunnel:muse-image"]


# ---------- combo labels ----------


def test_combo_label_marks_only_favourites() -> None:
    assert combo_label(model("muse-image"), ["aitunnel:muse-image"]).startswith("★ ")
    assert not combo_label(model("muse-image"), []).startswith("★")
    assert not combo_label(model("muse-image"), ["polza:muse-image"]).startswith("★")


# ---------- settings ----------


def test_settings_round_trip_keeps_favourites(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(favorite_models=["aitunnel:muse-image"]))
    assert store.load().favorite_models == ["aitunnel:muse-image"]


def test_favourites_are_empty_by_default(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load().favorite_models == []


def test_broken_favourites_in_the_file_do_not_break_the_load(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"favorite_models": "not-a-list", "theme": "dark"}),
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.favorite_models == []
    assert settings.theme == "dark"


# ---------- lately used models ----------


def test_split_key_returns_provider_and_model() -> None:
    assert split_key("aitunnel:muse-image") == ("aitunnel", "muse-image")


def test_split_key_of_a_key_without_a_colon() -> None:
    # A malformed key has no model part, so it never resolves to a model.
    assert split_key("muse-image") == ("muse-image", "")


def test_remember_model_puts_the_model_first() -> None:
    recents = remember_model(["aitunnel:gpt-image-1"], model("muse-image"))
    assert recents == ["aitunnel:muse-image", "aitunnel:gpt-image-1"]


def test_remember_model_moves_a_repeated_model_back_to_the_head() -> None:
    recents = remember_model(
        ["aitunnel:muse-image", "aitunnel:gpt-image-1"], model("muse-image")
    )
    assert recents == ["aitunnel:muse-image", "aitunnel:gpt-image-1"]


def test_remember_model_keeps_the_same_model_of_two_providers_apart() -> None:
    recents = remember_model(["polza:muse-image"], model("muse-image", "aitunnel"))
    assert recents == ["aitunnel:muse-image", "polza:muse-image"]


def test_remember_model_never_grows_past_the_limit() -> None:
    recents: list[str] = []
    for index in range(RECENT_LIMIT + 5):
        recents = remember_model(recents, model(f"model-{index}"))
    assert len(recents) == RECENT_LIMIT
    assert recents[0] == f"aitunnel:model-{RECENT_LIMIT + 4}"
    assert "aitunnel:model-0" not in recents


def test_recent_models_keep_the_recorded_order() -> None:
    recents = ["aitunnel:gpt-image-1", "aitunnel:muse-image"]
    found = recent_models(CATALOG, recents)
    assert [(item.id, present) for item, present in found] == [
        ("gpt-image-1", True),
        ("muse-image", True),
    ]


def test_recent_models_of_the_other_provider_resolve_by_key() -> None:
    # A model of another aggregator is not in the current catalog, but the key
    # still names it, so the entry can be shown and picked.
    found = recent_models(CATALOG, ["polza:topaz/image-upscale"])
    assert [(item.id, item.provider_id, present) for item, present in found] == [
        ("topaz/image-upscale", "polza", False)
    ]


def test_recent_models_ignore_a_key_without_a_model_name() -> None:
    assert recent_models(CATALOG, [":", "aitunnel:"]) == []


def test_recent_models_are_empty_by_default(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load().recent_models == []


def test_recent_models_survive_a_restart(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(recent_models=["aitunnel:muse-image"]))
    assert store.load().recent_models == ["aitunnel:muse-image"]


def test_broken_recents_in_the_file_do_not_break_the_load(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"recent_models": {"model": "muse-image"}}), encoding="utf-8"
    )
    assert SettingsStore(path).load().recent_models == []
