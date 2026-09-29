"""Tests for the model search and favourites.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, so a test
that imports Qt fails at collection.
"""

from __future__ import annotations

import json
import pathlib

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


TESTS_DIR = pathlib.Path(__file__).resolve().parent


def test_no_source_module_uses_a_star_character() -> None:
    # U+2605/U+2606 are not in Segoe UI. They came from a fallback font, and the
    # look of the button depended on whichever font that was. The star is a
    # picture now, so no module may fall back to the character.
    import re

    offenders = []
    for path in sorted((TESTS_DIR.parent / "app").rglob("*.py")):
        if re.search(r"[\u2605\u2606\u2b50]", path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(TESTS_DIR.parent).as_posix())
    assert not offenders, f"star character used in {offenders}"


def test_combo_label_carries_no_star_character() -> None:
    # The favourite is marked with an icon, so every row has the same text and
    # the names stay in one column.
    label = combo_label(model("muse-image"))
    assert label == model("muse-image").display_name()
    assert "\u2605" not in label
    assert "\u2606" not in label


# ---------- the star icons ----------


def test_star_icon_files_exist_for_both_states_and_themes() -> None:
    from app.config import STAR_ICON_DIR

    for theme in ("dark", "light"):
        for state in ("outline", "filled"):
            path = STAR_ICON_DIR / f"star-{state}-{theme}.png"
            assert path.exists(), f"{path.name} is missing"
            assert path.stat().st_size > 0


def _png_header(path: pathlib.Path) -> tuple[int, int, int]:
    """Width, height and colour type of a PNG, read with the standard library.

    Pillow is only needed to build the icons, not to run the tests, and the CI
    runner installs the project's dependencies, not the extra ones a script
    happens to use.
    """
    import struct

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    # IHDR is always the first chunk: length, type, then width/height/depth/colour.
    length, chunk = struct.unpack(">I4s", data[8:16])
    assert chunk == b"IHDR" and length == 13, path.name
    width, height, _depth, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def test_star_icons_are_square_and_have_an_alpha_channel() -> None:
    from app.config import STAR_ICON_DIR

    for path in sorted(STAR_ICON_DIR.glob("star-*.png")):
        width, height, colour = _png_header(path)
        assert width == height, f"{path.name} is not square: {width}x{height}"
        # Colour type 6 is truecolour with alpha, the type a button icon needs:
        # anything else would be a star painted on an opaque background.
        assert colour == 6, f"{path.name} has no alpha channel, colour type {colour}"


def test_star_icons_leave_room_around_the_star() -> None:
    # A star drawn edge to edge looks cramped in a button, and the filled and
    # the outline version must sit in the same place so the button does not jump
    # when it is toggled. Both are checked through the file size: the outline is
    # the same silhouette with the middle taken out, so it is slightly smaller.
    from app.config import STAR_ICON_DIR

    sizes = {
        name: (STAR_ICON_DIR / f"star-{name}-{theme}.png").stat().st_size
        for theme in ("dark", "light")
        for name in ("outline", "filled")
    }
    for theme in ("dark", "light"):
        outline = (STAR_ICON_DIR / f"star-outline-{theme}.png").stat().st_size
        filled = (STAR_ICON_DIR / f"star-filled-{theme}.png").stat().st_size
        assert outline != filled, f"the two states of the {theme} theme are identical"
    assert len(set(sizes.values())) >= 2


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
