"""Log panel showing application messages."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.logging_setup import add_handler

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

    def append(self, level: str, message: str) -> None:
        """Add a line with an explicit level."""
        self._append(level, message)

    def install_logging_bridge(self) -> None:
        """Show what the services log in this panel.

        Without it every ``logging`` warning, including the ones about money and
        broken files, lands in ``data/app.log`` only, where a user who started
        the app from a shortcut never looks.
        """
        add_handler(_PanelLogHandler(self))


class _PanelLogHandler(logging.Handler):
    """Forwards log records to the panel, always in the GUI thread.

    A handler can be called from a worker thread and a widget may not be, so
    the line is handed to the event loop instead of appended right away.
    """

    def __init__(self, panel: LogPanel) -> None:
        super().__init__(level=logging.INFO)
        self._panel = panel

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            level = "error"
        elif record.levelno >= logging.WARNING:
            level = "warning"
        else:
            level = "info"
        message = record.getMessage()
        QTimer.singleShot(0, lambda: self._panel.append(level, message))
