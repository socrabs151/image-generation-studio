"""Tests for the clipboard routing helpers.

The behaviour itself needs a window, but the decision logic is plain Python: which
widget owns a text paste, and what is in the clipboard.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QTextEdit

from app.ui.main_window import _is_text_input

application = QApplication.instance() or QApplication([])


def test_line_edit_owns_its_paste() -> None:
    assert _is_text_input(QLineEdit()) is True


def test_text_edit_owns_its_paste() -> None:
    assert _is_text_input(QTextEdit()) is True


def test_plain_combo_box_does_not() -> None:
    # A non-editable combo has no line edit, so Ctrl+V is ours.
    assert _is_text_input(QComboBox()) is False


def test_editable_combo_box_does() -> None:
    combo = QComboBox()
    combo.setEditable(True)
    assert _is_text_input(combo) is True


def test_nothing_focused_is_ours() -> None:
    assert _is_text_input(None) is False
