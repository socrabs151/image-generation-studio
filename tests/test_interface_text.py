"""Tests for the text of the interface.

The labels, placeholders and tooltips are the only part of the app the user
reads, and nothing else checks them: a button that promises a shortcut it does
not have, or an empty tooltip, is invisible to every other test.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, so a test
that imports Qt fails at collection. The checks are therefore made on the source
text, not on live widgets.
"""

from __future__ import annotations

import pathlib
import re

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# Every button a user presses to start or stop paid work, and the file it lives in.
MAIN_ACTIONS = {
    "app/ui/panels/prompt.py": ("Generate", "Stop", "Clear"),
    "app/ui/main_window.py": ("Settings", "History", "Check balance", "Refresh catalog"),
}


def _source(relative: str) -> str:
    return (APP_DIR.parent / relative).read_text(encoding="utf-8")


def _button_block(text: str, label: str) -> str:
    """The lines that build one button, from its label to the next statement."""
    start = text.find(f'"{label}"')
    assert start >= 0, f"{label} not found"
    # A tooltip may be set before or after the click connection; look a little
    # around the label rather than at one exact line.
    return text[max(0, start - 300) : start + 400]


def test_every_main_button_has_a_tooltip() -> None:
    missing: list[str] = []
    for relative, labels in MAIN_ACTIONS.items():
        text = _source(relative)
        for label in labels:
            block = _button_block(text, label)
            if "setToolTip" not in block and "toolTip=" not in block:
                missing.append(f"{relative}: {label}")
    assert not missing, f"buttons without a tooltip: {missing}"


def test_the_stop_tooltip_does_not_promise_an_impossible_cancel() -> None:
    """Stopping does not cancel the request at the aggregator: the work keeps
    running and stays paid for. The tooltip has to say so."""
    text = _source("app/ui/panels/prompt.py")
    stop = text[text.find('"Stop"') : text.find('"Stop"') + 400]
    assert "Stop" in stop
    lowered = stop.lower()
    assert "paid" in lowered or "keep" in lowered, (
        "the Stop tooltip must say the request keeps running and stays paid for"
    )


def test_the_generate_tooltip_says_the_estimate_is_not_the_real_cost() -> None:
    """The number on screen is the catalog maximum. Saying otherwise would make
    the user trust a figure the aggregator will not honour."""
    text = _source("app/ui/panels/prompt.py")
    generate = text[text.find('"Generate"') : text.find('"Generate"') + 400]
    assert "not the real cost" in generate.lower()


def test_every_parameter_field_has_a_tooltip() -> None:
    text = _source("app/ui/panels/params.py")
    fields = (
        "self.n_field",
        "self.quality",
        "self.resolution",
        "self.aspect_ratio",
        "self.format",
        "self.seed",
        "self.background",
    )
    missing = [
        field
        for field in fields
        if not re.search(
            rf"{re.escape(field)}\.setToolTip\(", text
        )
    ]
    assert not missing, f"parameter fields without a tooltip: {missing}"


def test_the_seed_tooltip_mentions_the_repeat_promise() -> None:
    """A seed exists so a result can be reproduced. The placeholder says
    "random", the tooltip has to explain what happens with a fixed one."""
    text = _source("app/ui/panels/params.py")
    seed = text[text.find("self.seed.setToolTip") :][:300]
    assert "seed" in seed.lower()
    assert "random" in seed.lower()


def test_the_model_list_explains_the_star() -> None:
    text = _source("app/ui/main_window.py")
    # The text lives in a constant, so check that it is defined and used.
    assert "MODEL_COMBO_TOOLTIP = (" in text, "the model list tooltip must be defined"
    start = text.index("MODEL_COMBO_TOOLTIP = (")
    end = text.index(")", start)
    tooltip = text[start:end].lower()
    assert "star" in tooltip, "the combo tooltip must say what the star means"
    assert "self._model_combo.setToolTip(MODEL_COMBO_TOOLTIP)" in text, (
        "the tooltip must be applied to the combo"
    )


def test_the_balance_label_says_it_is_not_live() -> None:
    """The balance is only refreshed by a button, and it does not change after a
    paid generation. Saying so is the difference between a number and a trap."""
    text = _source("app/ui/main_window.py")
    balance = text[text.find("self._balance_label.setToolTip") :][:400]
    assert "refresh" in balance.lower()
    assert "check balance" in balance.lower()


def test_the_viewer_handles_ctrl_s() -> None:
    """The tooltip on the Save button promises Ctrl+S, so the shortcut has to be
    there. It was removed once already because a report said it was missing; the
    report was wrong, and the check was skipped."""
    text = _source("app/ui/dialogs/image_viewer.py")
    # The whole branch, not just the constant: Key_S also occurs in Key_Space.
    assert re.search(
        r"if control and key == Qt\.Key\.Key_S:\s*\n\s*self\._save_as\(\)",
        text,
    ), "Ctrl+S must call _save_as in the viewer"
    assert "Ctrl+S" in text, "the Save button promises Ctrl+S"


def test_a_shortcut_promised_in_a_tooltip_is_handled() -> None:
    """Cross-check: every Ctrl+X named in a user-visible string of the image
    viewer has a matching key handler, so a tooltip cannot promise a shortcut
    that does not exist."""
    text = _source("app/ui/dialogs/image_viewer.py")
    promised = set(re.findall(r"Ctrl\+([A-Z])", text))
    assert promised, "no shortcut is named in the viewer tooltips"
    missing = [
        key
        for key in promised
        if not re.search(rf"key == Qt\.Key\.Key_{key}\b", text)
    ]
    assert not missing, (
        f"the viewer promises Ctrl+{', Ctrl+'.join(missing)} but has no handler"
    )
