"""Rules about which widget owns the keyboard, kept free of Qt.

The decision itself is plain data, so it lives here and can be tested on a
machine without a display server: the test suite must never import PySide6,
because the CI runner has no ``libEGL``. The Qt-facing half stays in the UI
layer and only reports the class name and one flag; that half lives in
:mod:`app.ui.focus_widgets`.
"""

from __future__ import annotations

# Widgets that own a text paste: Ctrl+V has to stay theirs, otherwise pasting
# text into a field would not work.
TEXT_INPUT_CLASSES = frozenset(
    {
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QAbstractSpinBox",
        "QSpinBox",
        "QDoubleSpinBox",
        "QDateEdit",
        "QTimeEdit",
        "QDateTimeEdit",
        "QKeySequenceEdit",
    }
)


def is_text_input(class_name: str, *, editable_combo: bool = False) -> bool:
    """Whether a widget of ``class_name`` handles a text paste itself.

    A combo box counts only when it is editable, because that is when it holds a
    line edit; a plain combo does not take a text paste.
    """
    if class_name in TEXT_INPUT_CLASSES:
        return True
    return class_name == "QComboBox" and editable_combo
