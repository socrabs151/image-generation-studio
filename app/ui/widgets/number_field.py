"""Numeric input field with increment and decrement buttons.

A custom widget is used instead of ``QSpinBox``: under a global style sheet the
``QSpinBox`` subcontrol layout breaks, so its input field overlaps the upper button
and clicks on that button select the text instead of incrementing the value.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_FIELD_HEIGHT = 24
_BUTTON_WIDTH = 16
_BUTTON_HEIGHT = 11


class NumberField(QFrame):
    """Integer field with ▲/▼ stepper buttons."""

    valueChanged = Signal(int)

    def __init__(
        self, minimum: int = 1, maximum: int = 10, value: int = 1, parent=None
    ) -> None:
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self.setObjectName("numberField")
        self.setFixedHeight(_FIELD_HEIGHT)

        row = QHBoxLayout(self)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(0)

        self.edit = QLineEdit(str(value))
        self.edit.setObjectName("numberEdit")
        self.edit.setValidator(QIntValidator(minimum, maximum, self))
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setFrame(False)
        self.edit.editingFinished.connect(self._commit)
        row.addWidget(self.edit, stretch=1)

        stepper = QWidget()
        column = QVBoxLayout(stepper)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for label, delta in (("▲", +1), ("▼", -1)):
            button = QToolButton()
            button.setText(label)
            button.setObjectName("numberBtn")
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.setAutoRepeat(True)
            button.setFixedSize(_BUTTON_WIDTH, _BUTTON_HEIGHT)
            button.clicked.connect(lambda _=False, step=delta: self._step(step))
            column.addWidget(button)
        row.addWidget(stepper)

    def value(self) -> int:
        """Return the current clamped value."""
        try:
            return self._clamp(int(self.edit.text()))
        except ValueError:
            return self._min

    def setValue(self, value: int) -> None:
        """Set the value, clamped to the allowed range."""
        self.edit.setText(str(self._clamp(value)))

    def setMaximum(self, maximum: int) -> None:  # noqa: N802 - Qt API
        """Lower the upper bound, for example to the limit of the selected model."""
        self._max = max(self._min, maximum)
        self.edit.setValidator(QIntValidator(self._min, self._max, self))
        self.setValue(self.value())

    def maximum(self) -> int:
        """The current upper bound."""
        return self._max

    def _step(self, delta: int) -> None:
        new_value = self._clamp(self.value() + delta)
        if new_value != self.value():
            self.edit.setText(str(new_value))
            self.valueChanged.emit(new_value)

    def _commit(self) -> None:
        self.edit.setText(str(self.value()))
        self.valueChanged.emit(self.value())

    def _clamp(self, value: int) -> int:
        return max(self._min, min(self._max, value))
