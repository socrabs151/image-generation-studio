"""Result viewer: zoomable image display with navigation and export.

Shows the currently selected generated image with controls for zoom (fit, 100%,
in, out), navigation between multiple results and export to file or clipboard.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_FIT = 0.0
_STEP = 1.25


class ResultViewer(QWidget):
    """Display and navigate generated images with zoom and export."""

    saveRequested = Signal()
    copyRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._images: list[QPixmap] = []
        self._index = 0
        self._scale = _FIT

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.addWidget(self._button("Fit", self._fit))
        toolbar.addWidget(self._button("100%", self._zoom_100))
        toolbar.addWidget(self._button("−", self._zoom_out))
        toolbar.addWidget(self._button("+", self._zoom_in))
        toolbar.addStretch(1)
        self._nav = self._button("◀ 1/1 ▶", self._next)
        self._nav.setVisible(False)
        toolbar.addWidget(self._nav)
        toolbar.addStretch(1)
        toolbar.addWidget(self._button("Save as…", self.saveRequested.emit))
        toolbar.addWidget(self._button("Copy", self.copyRequested.emit))

        self._view = QLabel("No result")
        self._view.setObjectName("dropArea")
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setObjectName("resultScroll")
        self._scroll.setWidget(self._view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(toolbar)
        layout.addWidget(self._scroll, stretch=1)

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def set_images(self, images: list[QPixmap]) -> None:
        """Show a set of images, starting from the first one."""
        self._images = list(images)
        self._index = 0
        self._scale = _FIT
        if not self._images:
            self._view.setText("No result")
            self._nav.setVisible(False)
            return
        self._update()

    def current_pixmap(self) -> QPixmap | None:
        """The currently displayed pixmap, if any."""
        if 0 <= self._index < len(self._images):
            return self._images[self._index]
        return None

    def _update(self) -> None:
        if not self._images:
            return
        pixmap = self._images[self._index]
        scaled = self._scaled(pixmap)
        self._view.setPixmap(scaled)
        self._view.setFixedSize(scaled.size())
        count = len(self._images)
        self._nav.setText(f"◀ {self._index + 1}/{count} ▶")
        self._nav.setVisible(count > 1)

    def _scaled(self, pixmap: QPixmap) -> QPixmap:
        if self._scale == _FIT:
            viewport = self._scroll.viewport().size()
            if viewport.width() <= 0 or viewport.height() <= 0:
                return pixmap
            scaled = pixmap.scaled(
                viewport,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            return scaled
        return pixmap.scaled(
            pixmap.width() * self._scale,
            pixmap.height() * self._scale,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _fit(self) -> None:
        self._scale = _FIT
        self._update()

    def _zoom_100(self) -> None:
        self._scale = 1.0
        self._update()

    def _zoom_in(self) -> None:
        self._scale = _STEP if self._scale == _FIT else self._scale * _STEP
        self._update()

    def _zoom_out(self) -> None:
        self._scale = 1.0 / _STEP if self._scale == _FIT else self._scale / _STEP
        self._update()

    def _next(self) -> None:
        if len(self._images) > 1:
            self._index = (self._index + 1) % len(self._images)
            self._update()
