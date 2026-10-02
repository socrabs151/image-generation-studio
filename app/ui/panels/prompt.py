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
    QWidget,
)


class PromptPanel(QFrame):
    """Prompt input and the action buttons."""

    generateRequested = Signal()
    stopRequested = Signal()
    clearRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
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
        clear.setToolTip("Empty the prompt field")
        clear.clicked.connect(self.clearRequested.emit)
        self.generate = QPushButton("Generate")
        self.generate.setObjectName("primary")
        self.generate.setToolTip(
            "Send the request to the aggregator. The estimate on the right is the "
            "catalog maximum for the number of images, not the real cost."
        )
        self.generate.clicked.connect(self.generateRequested.emit)
        self.stop = QPushButton("Stop")
        self.stop.setObjectName("danger")
        self.stop.setEnabled(False)
        self.stop.setToolTip(
            "Stop waiting for the result. This does not cancel the request at the "
            "aggregator: the work keeps running and stays paid for. The images that "
            "already arrived are still saved."
        )
        self.stop.clicked.connect(self.stopRequested.emit)
        actions.addWidget(clear)
        actions.addWidget(self.generate)
        actions.addWidget(self.stop)
        actions.addStretch(1)

        self.cost_hint = QLabel("")
        self.cost_hint.setObjectName("hint")
        self.cost_hint.setToolTip(
            "Catalog prices for one image, and the estimate for the whole request "
            "(the catalog maximum times the number of images). The aggregator "
            "reports the real cost afterwards, and it can be higher."
        )
        actions.addWidget(self.cost_hint)
        layout.addLayout(actions)

    def prompt(self) -> str:
        """Current prompt text."""
        return self.editor.toPlainText().strip()

    def set_prompt(self, text: str) -> None:
        """Replace the prompt text."""
        self.editor.setPlainText(text)

    def set_busy(self, busy: bool) -> None:
        """Toggle the generate/stop buttons for a running request."""
        self.generate.setEnabled(not busy)
        self.stop.setEnabled(busy)

    def set_cost_hint(self, text: str) -> None:
        """Update the price hint next to the buttons."""
        self.cost_hint.setText(text)
