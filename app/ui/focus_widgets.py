"""Qt-facing half of the focus rules.

:mod:`app.ui.focus_rules` holds the decision as plain data so it can be tested
without a display server; this module is the part that looks at a real widget.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QWidget

from app.ui.focus_rules import is_text_input


def focus_is_text_input(widget: QWidget | None) -> bool:
    """Whether ``widget`` handles a text paste itself.

    Passing a widget to :func:`~app.ui.focus_rules.is_text_input` instead would
    always answer False, because a widget is never one of those strings — and
    the guard would quietly stop guarding.
    """
    if widget is None:
        return False
    editable_combo = isinstance(widget, QComboBox) and widget.isEditable()
    return is_text_input(type(widget).__name__, editable_combo=editable_combo)
