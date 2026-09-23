"""Log panel showing application messages."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

_LEVEL_PREFIX = {
    "info": "",
    "warning": "WARNING: ",
    "error": "ERROR: ",
}


class LogPanel(QFrame):
    """Read-only message log with a clear button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("Log")
        title.setObjectName("panelTitle")
        head.addWidget(title)
        head.addStretch(1)
        clear = QPushButton("Clear")
        clear.setObjectName("link")
        clear.setFlat(True)
        clear.clicked.connect(self.clear)
        head.addWidget(clear)
        layout.addLayout(head)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(130)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.view)

    def info(self, message: str) -> None:
        """Log an informational message."""
        self._append("info", message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self._append("warning", message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self._append("error", message)

    def clear(self) -> None:
        """Clear the log."""
        self.view.clear()

    def _append(self, level: str, message: str) -> None:
        prefix = _LEVEL_PREFIX.get(level, "")
        self.view.appendPlainText(f"{prefix}{message}")
        self.view.moveCursor(QTextCursor.MoveOperation.End)
