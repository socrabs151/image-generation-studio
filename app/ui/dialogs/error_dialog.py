"""Modal dialog that shows a failed generation's error and lets it be copied.

Provider errors are the only place where the full reason is available, so the dialog
keeps the text selectable and offers a copy button: it is usually needed for a
support request or for a bug report.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class ErrorDialog(QDialog):
    """Read-only error text with a copy button."""

    def __init__(self, context: str, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation failed")
        self.resize(640, 360)
        self._message = message

        title = QLabel(context)
        title.setObjectName("docsTitle")
        title.setWordWrap(True)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(message)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = QPushButton("Copy")
        copy.setObjectName("primary")
        copy.clicked.connect(self._copy)
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.text)
        layout.addWidget(buttons)

    def _copy(self) -> None:
        """Put the whole message on the clipboard and close."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._message)
        self.accept()
