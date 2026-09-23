"""Prompt panel with the generate and stop controls."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class PromptPanel(QFrame):
    """Prompt input and the action buttons."""

    generateRequested = Signal()
    stopRequested = Signal()
    clearRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Describe the image you want to generate…")
        self.editor.setMinimumHeight(50)
        self.editor.setMaximumHeight(110)
        layout.addWidget(self.editor)

        actions = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clearRequested.emit)
        self.generate = QPushButton("Generate")
        self.generate.setObjectName("primary")
        self.generate.clicked.connect(self.generateRequested.emit)
        self.stop = QPushButton("Stop")
        self.stop.setObjectName("danger")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self.stopRequested.emit)
        actions.addWidget(clear)
        actions.addWidget(self.generate)
        actions.addWidget(self.stop)
        actions.addStretch(1)

        self.cost_hint = QLabel("")
        self.cost_hint.setObjectName("hint")
        actions.addWidget(self.cost_hint)
        layout.addLayout(actions)

    def prompt(self) -> str:
        """Current prompt text."""
        return self.editor.toPlainText().strip()

    def set_busy(self, busy: bool) -> None:
        """Toggle the generate/stop buttons for a running request."""
        self.generate.setEnabled(not busy)
        self.stop.setEnabled(busy)

    def set_cost_hint(self, text: str) -> None:
        """Update the price hint next to the buttons."""
        self.cost_hint.setText(text)
