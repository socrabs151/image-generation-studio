"""Tests for the keyboard ownership rule, and a guard for the CI constraint.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, so a test
that imports Qt fails at collection. :func:`test_no_test_module_imports_qt`
enforces that for the whole suite.
"""

from __future__ import annotations

import pathlib
import re

from app.ui.focus_rules import TEXT_INPUT_CLASSES, is_text_input

TESTS_DIR = pathlib.Path(__file__).resolve().parent
_QT_IMPORT = re.compile(r"^\s*(?:from|import)\s+PySide6", re.MULTILINE)


def test_line_edits_own_their_paste() -> None:
    assert is_text_input("QLineEdit") is True
    assert is_text_input("QTextEdit") is True
    assert is_text_input("QPlainTextEdit") is True


def test_spin_boxes_own_their_paste() -> None:
    # NumberField in the params panel is a QLineEdit; a raw spin box counts too.
    assert is_text_input("QDoubleSpinBox") is True
    assert is_text_input("QDateTimeEdit") is True


def test_plain_combo_box_does_not_own_the_paste() -> None:
    # A combo without a line edit takes no text, so Ctrl+V is ours.
    assert is_text_input("QComboBox") is False


def test_editable_combo_box_owns_the_paste() -> None:
    assert is_text_input("QComboBox", editable_combo=True) is True


def test_everything_else_is_ours() -> None:
    assert is_text_input("ReferencePanel") is False
    assert is_text_input("ResultViewer") is False
    assert is_text_input("MarkdownView") is False
    assert is_text_input("QLabel") is False


def test_no_unknown_spin_box_class_is_missing() -> None:
    # A guard on the data itself: every QAbstractSpinBox subclass Qt ships with
    # has to be listed, or Ctrl+V would be stolen from a numeric field.
    for name in ("QSpinBox", "QDoubleSpinBox", "QDateEdit", "QTimeEdit", "QDateTimeEdit"):
        assert name in TEXT_INPUT_CLASSES


def test_no_test_module_imports_qt() -> None:
    offenders = [
        path.name
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if _QT_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"{offenders} import PySide6. The CI runner has no libEGL, so a Qt import "
        "fails at collection. Move the logic under test into a Qt-free module, as "
        "app/ui/markdown.py and app/ui/focus_rules.py do."
    )
