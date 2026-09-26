"""Result viewer: a thumbnail grid plus a zoomable pop-up viewer.

The result area shows all generated images as a grid of thumbnails; clicking one
opens a separate :class:`ZoomableView` window where the image can be inspected at
full size with zoom and navigation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_FIT = 0.0
_STEP = 1.25
_THUMB_SIZE = 180
_THUMB_PADDING = 6
_CELL = _THUMB_SIZE + 2 * _THUMB_PADDING
_CELL_SPACING = 8


class ZoomableView(QWidget):
    """Zoomable image display: fit, 100%, zoom in/out and navigation."""

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

        self._view = QLabel("No image")
        self._view.setObjectName("canvas")
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

    def set_images(self, images: list[QPixmap], index: int = 0) -> None:
        """Show a set of images, starting at ``index``."""
        self._images = list(images)
        self._index = min(index, max(0, len(self._images) - 1)) if self._images else 0
        self._scale = _FIT
        if not self._images:
            self._view.setText("No image")
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
            return pixmap.scaled(
                viewport,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
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


class Thumbnail(QLabel):
    """A clickable result thumbnail."""

    activated = Signal(int)

    def __init__(self, index: int, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self._index = index
        self.setObjectName("resultThumb")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to open the image viewer")
        self.setFixedSize(_CELL, _CELL)
        self.setPixmap(
            pixmap.scaled(
                _THUMB_SIZE,
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._index)
        super().mousePressEvent(event)


class ResultViewer(QWidget):
    """Grid of generated thumbnails; clicking one opens a zoomable viewer."""

    imageActivated = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._images: list[QPixmap] = []
        self._columns = 0

        self._placeholder = QLabel("Generated images will appear here")
        self._placeholder.setObjectName("dropArea")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)

        self._message = QLabel()
        self._message.setObjectName("resultError")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        self._message.setVisible(False)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("resultScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setObjectName("scrollViewport")

        self._grid_host = QWidget()
        self._grid_host.setObjectName("scrollViewport")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(_CELL_SPACING, _CELL_SPACING, _CELL_SPACING, _CELL_SPACING)
        self._grid.setSpacing(_CELL_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._grid_host)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._message)
        layout.addWidget(self._scroll, stretch=1)
        self._scroll.setVisible(False)

    def set_images(self, images: list[QPixmap]) -> None:
        """Replace the grid with thumbnails of the given images."""
        self._images = list(images)
        self._message.setVisible(False)
        self._message.clear()
        self._placeholder.setVisible(not self._images)
        self._scroll.setVisible(bool(self._images))
        if self._images:
            self._columns = self._columns_for_width(self._scroll.viewport().width())
            self._rebuild()
        else:
            self._columns = 0
            self._clear()

    def set_error(self, message: str) -> None:
        """Show an error message instead of results."""
        self.set_images([])
        self._message.setText(message)
        self._message.setVisible(True)
        self._placeholder.setVisible(False)

    def images(self) -> list[QPixmap]:
        """The currently displayed images."""
        return list(self._images)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._sync_columns()

    def _columns_for_width(self, width: int) -> int:
        usable = max(0, width - 2 * _CELL_SPACING)
        return max(1, (usable + _CELL_SPACING) // (_CELL + _CELL_SPACING))

    def _sync_columns(self) -> None:
        columns = self._columns_for_width(self._scroll.viewport().width())
        if columns != self._columns:
            self._columns = columns
            if self._images:
                self._rebuild()

    def _rebuild(self) -> None:
        self._clear()
        columns = max(1, self._columns)
        for index, pixmap in enumerate(self._images):
            thumb = Thumbnail(index, pixmap)
            thumb.activated.connect(self._activate)
            self._grid.addWidget(thumb, index // columns, index % columns)
        self._scroll.verticalScrollBar().setValue(0)

    def _clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _activate(self, index: int) -> None:
        self.imageActivated.emit(index)
