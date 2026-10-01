"""Result viewer: a thumbnail grid plus a zoomable pop-up viewer.

The result area shows all generated images as a grid of thumbnails; clicking one
opens a separate :class:`ZoomableView` window where the image can be inspected at
full size with zoom and navigation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QScrollArea,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

from app.ui.thumb_budget import THUMB_SIZE, retained_size

_THUMB_SIZE = THUMB_SIZE
_THUMB_PADDING = 6
_CELL = _THUMB_SIZE + 2 * _THUMB_PADDING
_CELL_SPACING = 8


class ZoomableView(QWidget):
    """A scrollable, zoomable image display.

    Three zoom modes: fit to the window, an explicit scale, and 100% meaning one
    image pixel per screen pixel (also correct on a high-DPI screen). The image can be
    panned by dragging, zoomed with the wheel around the pointer, and the window can be
    resized freely: the canvas grows instead of being pinned to a fixed size.
    """

    # Zoom bounds, as a fraction of the original image size.
    MIN_SCALE = 0.02
    MAX_SCALE = 16.0
    STEP = 1.25

    scaleChanged = Signal(float)  # effective scale, 1.0 == 100%
    panningChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._images: list[QPixmap] = []
        self._index = 0
        self._scale: float | None = None  # None means "fit to the window"
        self._drag_at: QPoint | None = None
        self._drag_scroll: QPoint | None = None

        self._canvas = QLabel("No image")
        self._canvas.setObjectName("canvas")
        self._canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The canvas is the deepest widget under the pointer, and QLabel accepts
        # a wheel event it does not use, which stops it from ever reaching the
        # zoom handler above. Forwarding it here is what makes the wheel work.
        self._canvas.installEventFilter(self)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("resultScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._canvas)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._scroll)

    # ---------- content ----------
    def set_images(self, images: list[QPixmap], index: int = 0) -> None:
        """Show a set of images, starting at ``index``."""
        self._images = list(images)
        if not self._images:
            self._index = 0
            self._canvas.setText("No image")
            self._canvas.setPixmap(QPixmap())
            self._canvas.setMinimumSize(0, 0)
            self.scaleChanged.emit(1.0)
            return
        self._index = max(0, min(index, len(self._images) - 1))
        self._render()

    def current_pixmap(self) -> QPixmap | None:
        """The currently displayed pixmap, if any."""
        if 0 <= self._index < len(self._images):
            return self._images[self._index]
        return None

    def images(self) -> list[QPixmap]:
        """The whole set of images."""
        return list(self._images)

    def set_index(self, index: int) -> None:
        """Show another image of the set."""
        if not self._images or not 0 <= index < len(self._images):
            return
        self._index = index
        self._render()
        # A new image starts at its top-left corner, not where the previous one was.
        self._scroll.horizontalScrollBar().setValue(0)
        self._scroll.verticalScrollBar().setValue(0)

    def index(self) -> int:
        """Index of the displayed image."""
        return self._index

    def count(self) -> int:
        """Number of images in the set."""
        return len(self._images)

    # ---------- zoom ----------
    @property
    def is_fit(self) -> bool:
        """Whether the image is scaled to the window."""
        return self._scale is None

    def _device_scale(self) -> float:
        """Screen pixels per logical pixel, so 100% stays true on a high-DPI screen."""
        screen = QApplication.primaryScreen()
        return screen.devicePixelRatio() if screen is not None else 1.0

    def _fit_scale(self) -> float:
        """The scale that makes the image fit the visible area.

        Capped at ``MAX_SCALE``: a tiny image stretched to a large window would
        otherwise report a zoom of thousands of percent and scale a
        window-sized buffer for a handful of pixels.
        """
        pixmap = self.current_pixmap()
        if pixmap is None:
            return 1.0
        viewport = self._scroll.viewport().size()
        if pixmap.isNull() or viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0
        return min(
            self.MAX_SCALE,
            min(
                viewport.width() / pixmap.width(),
                viewport.height() / pixmap.height(),
            ),
        )

    def effective_scale(self) -> float:
        """Scale relative to the screen, so 1.0 means one image pixel per screen pixel."""
        scale = self._fit_scale() if self.is_fit else float(self._scale or 1.0)
        return scale * self._device_scale()

    def zoom_in(self) -> None:
        """Magnify around the centre of the view."""
        self._zoom_by(self.STEP)

    def zoom_out(self) -> None:
        """Shrink around the centre of the view."""
        self._zoom_by(1 / self.STEP)

    def zoom_fit(self) -> None:
        """Scale the image to the window."""
        if self.is_fit:
            return
        self._scale = None
        self._render()

    def zoom_actual(self) -> None:
        """Show the image at its real pixel size."""
        self._zoom_to(1.0)

    def _zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:
        """Change the scale by a factor, keeping the pointed-at place in place."""
        self._zoom_to(self.effective_scale() * factor, anchor)

    def _zoom_to(self, target: float, anchor: QPoint | None = None) -> None:
        """Move to an absolute scale, keeping the pointed-at place of the image still."""
        target = min(self.MAX_SCALE, max(self.MIN_SCALE, target))
        current = self.effective_scale()
        if abs(target - current) < 1e-6:
            return
        # The anchor is a point in canvas coordinates inside the visible area.
        point = anchor if anchor is not None else self._visible_center()
        before = self._point_in_image(point)
        self._scale = target / self._device_scale()
        self._render()
        after = self._image_point_in_canvas(before)
        self._scroll_to(self._scroll.horizontalScrollBar(), int(after.x() - point.x()))
        self._scroll_to(self._scroll.verticalScrollBar(), int(after.y() - point.y()))

    def _visible_center(self) -> QPoint:
        return self._canvas.rect().center()

    def _point_in_image(self, point: QPoint) -> QPointF:
        """Where a canvas point sits in the original image."""
        pixmap = self.current_pixmap()
        if pixmap is None or pixmap.isNull():
            return QPointF(0, 0)
        scaled = self._scaled()
        offset = QPointF(
            (self._canvas.width() - scaled.width()) / 2,
            (self._canvas.height() - scaled.height()) / 2,
        )
        relative = QPointF(point) - offset
        scale = self.effective_scale() or 1.0
        return QPointF(relative.x() / scale, relative.y() / scale)

    def _image_point_in_canvas(self, point: QPointF) -> QPointF:
        """Where a point of the original image sits in canvas coordinates."""
        pixmap = self.current_pixmap()
        if pixmap is None:
            return QPointF(0, 0)
        scaled = self._scaled()
        offset = QPointF(
            (self._canvas.width() - scaled.width()) / 2,
            (self._canvas.height() - scaled.height()) / 2,
        )
        scale = self.effective_scale() or 1.0
        return QPointF(point.x() * scale + offset.x(), point.y() * scale + offset.y())

    @staticmethod
    def _scroll_to(bar: QScrollBar, delta: int) -> None:
        bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + delta)))

    def _scaled(self) -> QPixmap:
        """The pixmap at the current scale."""
        pixmap = self.current_pixmap()
        if pixmap is None or pixmap.isNull():
            return QPixmap()
        scale = self.effective_scale()
        size = QSize(
            max(1, round(pixmap.width() * scale)),
            max(1, round(pixmap.height() * scale)),
        )
        if size == pixmap.size():
            return pixmap
        return pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _render(self) -> None:
        """Repaint the canvas and report the new scale."""
        scaled = self._scaled()
        if scaled.isNull():
            self._canvas.setPixmap(QPixmap())
            self._canvas.setMinimumSize(0, 0)
            return
        self._canvas.setPixmap(scaled)
        # A minimum size, not a fixed one: the scroll area keeps the canvas at least
        # as large as the image, and lets it grow to fill the window when it fits.
        self._canvas.setMinimumSize(scaled.size())
        self._canvas.resize(scaled.size())
        self._update_scroll_mode()
        self.scaleChanged.emit(self.effective_scale())

    def _update_scroll_mode(self) -> None:
        """Scrollbars only when the image is larger than the window."""
        scaled = self._scaled()
        scrollable = scaled.width() > self._scroll.viewport().width() + 2 or (
            scaled.height() > self._scroll.viewport().height() + 2
        )
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if scrollable
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setHorizontalScrollBarPolicy(policy)
        self._scroll.setVerticalScrollBarPolicy(policy)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # In fit mode the image follows the window size.
        if self.is_fit and self.current_pixmap() is not None:
            self._render()

    # ---------- interaction ----------
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.current_pixmap() is None:
            return
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        factor = self.STEP**steps
        # The pointer position arrives in this widget's coordinates and has to
        # be mapped onto the canvas, which is a child on a scroll area.
        anchor = self._canvas.mapFrom(self, event.position().toPoint())
        self._zoom_by(factor, anchor)
        event.accept()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self._canvas and event.type() == QEvent.Type.Wheel:
            self.wheelEvent(event)
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_at = event.position().toPoint()
            self._drag_scroll = QPoint(
                self._scroll.horizontalScrollBar().value(),
                self._scroll.verticalScrollBar().value(),
            )
            self._canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.panningChanged.emit(True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_at is None or self._drag_scroll is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position().toPoint() - self._drag_at
        self._scroll.horizontalScrollBar().setValue(self._drag_scroll.x() - delta.x())
        self._scroll.verticalScrollBar().setValue(self._drag_scroll.y() - delta.y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_at is not None:
            self._drag_at = None
            self._drag_scroll = None
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
            self.panningChanged.emit(False)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Double click is the usual shortcut between "fit" and "real size".
        if self.is_fit:
            self.zoom_actual()
        else:
            self.zoom_fit()


def _retained(pixmap: QPixmap) -> QPixmap:
    """A copy of ``pixmap`` reduced to the size the grid keeps.

    An image already small enough is kept as it is: scaling it up would cost
    memory and blur the thumbnail.
    """
    if pixmap.isNull():
        return pixmap
    width, height = retained_size(pixmap.width(), pixmap.height())
    if (width, height) == (pixmap.width(), pixmap.height()):
        return pixmap
    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


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
        self._paths: list[str] = []
        self._columns = 0

        self._placeholder = QLabel("Generated images will appear here")
        self._placeholder.setObjectName("resultEmpty")
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

    def set_images(self, images: list[QPixmap], paths: list[str] | None = None) -> None:
        """Replace the grid with thumbnails of the given images.

        ``paths`` are the files behind the images, when known: the viewer shows the
        file name, the size on disk and offers to open the folder.

        The grid draws 180 px thumbnails, so the full-size pictures are dropped
        right away and only reduced copies are kept. Six 4K results were about
        384 MiB of resident memory for a grid that never shows more than 180 px.
        The full-size images are read back from ``paths`` when the viewer window
        opens, which is the one place that needs them.
        """
        self._images = [_retained(pixmap) for pixmap in images]
        self._paths = list(paths) if paths else []
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
        """The currently displayed images, at grid resolution."""
        return list(self._images)

    def full_images(self) -> list[QPixmap]:
        """The images at full size, read back from disk where possible.

        Opening the viewer needs the real pixels, so they are loaded here, on
        purpose, instead of being held in memory from the moment of generation. A
        file that has gone missing falls back to the reduced copy, so the window
        opens either way.
        """
        full: list[QPixmap] = []
        for index, reduced in enumerate(self._images):
            path = self.path_at(index)
            loaded = QPixmap(path) if path and Path(path).exists() else QPixmap()
            full.append(loaded if not loaded.isNull() else reduced)
        return full

    def paths(self) -> list[str]:
        """The files behind the images, when known."""
        return list(self._paths)

    def path_at(self, index: int) -> str:
        """The file behind one image, empty when it is unknown."""
        if 0 <= index < len(self._paths):
            return self._paths[index]
        return ""

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
                # Hide it, then delete: setParent(None) would turn the widget into
                # a separate window for a moment, and leaving it visible would
                # leave a ghost until the event loop catches up.
                widget.hide()
                widget.deleteLater()

    def _activate(self, index: int) -> None:
        self.imageActivated.emit(index)
