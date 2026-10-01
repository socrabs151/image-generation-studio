"""Tests for the theme files and the delete confirmation.

The QSS is the only styling the app has, so a rule that is missing or that
changes a size cannot be caught by any other test. The checks are on the source
text, so no Qt is needed.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
THEMES = ROOT / "resources" / "themes"
THEME_FILES = ("light.qss", "dark.qss")


def _theme(name: str) -> str:
    return (THEMES / name).read_text(encoding="utf-8")


# ---------- disabled elements have to look disabled ----------


def test_both_themes_exist_and_load() -> None:
    for name in THEME_FILES:
        text = _theme(name)
        assert text.strip(), f"{name} is empty"


def test_every_theme_gives_disabled_fields_another_colour() -> None:
    """A field the model does not support used to look exactly like a working
    one, so the only way to tell was to read the hint under the model."""
    for name in THEME_FILES:
        text = _theme(name)
        rule = re.search(
            r"QComboBox:disabled[^{]*\{([^}]*)\}", text, re.S
        )
        assert rule, f"{name} has no disabled rule for the parameter fields"
        body = rule.group(1)
        assert "background-color" in body, f"{name}: disabled fields need a background"
        assert "color" in body, f"{name}: disabled fields need a dimmer text"


def test_every_theme_styles_disabled_buttons() -> None:
    for name in THEME_FILES:
        text = _theme(name)
        assert "QPushButton:disabled" in text, f"{name}: no disabled button rule"
        assert "QPushButton#primary:disabled" in text, (
            f"{name}: Generate is disabled while busy and must look it"
        )


def test_a_disabled_rule_never_changes_the_size() -> None:
    """A padding or width in a disabled rule would make the fields jump when the
    user switches model, which is how the layout used to break.

    The drop-down arrow is the exception: Qt resets a sub-control unless it is
    named again, so it has to repeat the width of the enabled rule to keep the
    arrow from moving.
    """
    forbidden = ("padding", "width", "height", "margin", "font-size", "border-width")
    for name in THEME_FILES:
        text = _theme(name)
        for match in re.finditer(r"[^\n{}]*:[a-z-]*disabled[^\n{}]*\{([^}]*)\}", text, re.S):
            selector, body = match.group(0).split("{", 1)
            if "::drop-down" in selector:
                continue
            for property_name in forbidden:
                assert property_name not in body, (
                    f"{name}: the disabled rule changes {property_name}, so the "
                    f"field resizes: {selector.strip()}"
                )


def test_the_disabled_drop_down_keeps_the_arrow_in_place() -> None:
    for name in THEME_FILES:
        text = _theme(name)
        assert "QComboBox:disabled::drop-down" in text, (
            f"{name}: without this the arrow resizes when the combo is disabled"
        )


def test_the_two_themes_stay_in_step() -> None:
    """A rule added to one theme and forgotten in the other is invisible in half
    the app."""
    selectors = {
        name: {
            match.group(1).strip()
            for match in re.finditer(r"([^\n{}]+)\{", _theme(name))
        }
        for name in THEME_FILES
    }
    light, dark = (selectors[name] for name in THEME_FILES)
    only_light = sorted(light - dark)
    only_dark = sorted(dark - light)
    assert not only_light, f"only in light.qss: {only_light}"
    assert not only_dark, f"only in dark.qss: {only_dark}"


# ---------- deleting a history entry has to ask ----------


def test_deleting_an_entry_asks_first() -> None:
    text = (ROOT / "app" / "ui" / "dialogs" / "history.py").read_text(encoding="utf-8")
    body = text[text.find("def _delete_selected") :][:1500]

    assert "QMessageBox" in body, "deleting must ask"
    assert "StandardButton.No" in body, "the default answer must be No"
    # The record is only removed after the answer is Yes.
    assert body.index("StandardButton.Yes") < body.index("self._history.delete"), (
        "the entry must not be deleted before the answer"
    )


def test_the_confirmation_names_what_will_be_lost() -> None:
    """The entry leaves the totals, so the dialog has to say so."""
    text = (ROOT / "app" / "ui" / "dialogs" / "history.py").read_text(encoding="utf-8")
    body = text[text.find("def _delete_selected") :][:1500]

    assert "record.cost_rub" in body, "the amount has to be shown"
    assert "totals" in body, "the dialog must say the cost stops counting"
    assert "file_paths" in body, "the dialog must say the files are not deleted"
    assert "undone" in body, "the dialog must say it cannot be undone"
