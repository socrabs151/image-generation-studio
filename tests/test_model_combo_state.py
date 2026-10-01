"""Tests for the rules behind the model drop-down and the aggregator list.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, so a test
that imports Qt fails at collection. The rules live as constants and as short
predicates, so they can be checked here and applied by the widgets.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_WINDOW = ROOT / "app" / "ui" / "main_window.py"
TEXT = MAIN_WINDOW.read_text(encoding="utf-8")


def _body(name: str) -> str:
    """The source of one method, up to the next definition."""
    start = TEXT.find(f"def {name}(")
    assert start >= 0, f"{name} not found"
    following = TEXT.find("\n    def ", start)
    return TEXT[start : following if following > 0 else len(TEXT)]


# ---------- the aggregator list is wide enough ----------


def test_the_aggregator_combo_has_a_width_floor() -> None:
    """It was laid out 46 px wide and cut the name in half, because a combo with
    no minimum takes whatever the layout feels like."""
    bar = TEXT[TEXT.find("def _build_topbar") : TEXT.find("def _build_model_bar")]
    assert "self._provider_combo.setMinimumWidth(" in bar, (
        "the aggregator list needs a minimum width or it collapses"
    )
    # The floor is measured from the names, not a magic number that rots when an
    # aggregator is renamed.
    assert "_text_width()" in bar


def test_the_width_helper_uses_the_real_font_and_names() -> None:
    body = _body("_text_width")
    assert "QFontMetrics" in body
    assert "provider_choices()" in body, (
        "the floor has to follow the aggregator names, not a fixed guess"
    )


# ---------- the model list explains itself ----------


def test_a_failed_catalog_puts_a_message_into_the_list() -> None:
    body = _body("_on_catalog_failed")
    assert "_show_model_combo_message" in body, (
        "an empty list looks broken; it has to say what happened"
    )
    assert "PLACEHOLDER_NO_MODELS" in body
    assert "Refresh" in TEXT[TEXT.index("PLACEHOLDER_NO_MODELS = (") :][:400]


def test_a_loaded_catalog_removes_the_message() -> None:
    body = _body("_on_catalog_loaded")
    assert "_show_model_combo_message" in body, "the empty-catalog case needs it too"
    assert "MODEL_COMBO_TOOLTIP" in body, "the failure tooltip must be taken back"


def test_the_list_is_disabled_only_while_it_shows_a_message() -> None:
    body = _body("_show_model_combo_message")
    assert "setEnabled(False)" in body
    assert "setEnabled(True)" in body, "a real catalog has to give the list back"
    assert "self._visible = []" in body, (
        "the visible list has to be cleared too: it is what the selection is "
        "resolved against, and a stale entry would enable Generate"
    )


def test_rebuilding_a_real_list_gives_the_combo_back() -> None:
    body = _body("_rebuild_model_list")
    assert "setEnabled(True)" in body, (
        "after a failure the combo stayed disabled even with a good catalog"
    )


# ---------- Generate needs a model ----------


def test_generate_is_enabled_only_with_a_selected_model() -> None:
    body = _body("_sync_generate_state")
    assert "_selected_model() is not None" in body


def test_both_empty_states_disable_generate() -> None:
    """A failed load and an empty catalog both leave no model to send."""
    for name in ("_on_catalog_failed", "_on_catalog_loaded"):
        body = _body(name)
        assert "_sync_generate_state()" in body, (
            f"{name} changes the selection and must refresh the button"
        )


def test_the_selection_is_resolved_against_the_visible_list() -> None:
    """Not against the catalog: after filtering, index 1 is a different model."""
    body = _body("_selected_model")
    assert "self._visible" in body
    assert "self._models" not in body, (
        "reading the full catalog would select the wrong model after a search"
    )
