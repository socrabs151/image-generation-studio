"""Workspace panel: reference images and the generation result.

The reference area holds a **list** of images: several files can be loaded at once,
dropped, or pasted one after another, because models accept up to sixteen references.
Clicking a thumbnail opens the whole set in a viewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.ui.widgets.result_viewer import ResultViewer

_THUMB = 96
_CLOSE = 20


@dataclass(slots=True)
class Reference:
    """One loaded reference image."""

    data: bytes
    pixmap: QPixmap
    source_path: str = ""


class ReferencePanel(QWidget):
    """Drop target and thumbnail strip holding every loaded reference image."""

    referenceActivated = Signal(int)
    fileRejected = Signal(str)
    dropped = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        # Focusable so that a dropped or pasted image is obvious as the current
        # target, and so the panel can be reached from the keyboard.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setToolTip(
            "Drop images here, or use Load and Paste. Ctrl+V adds the image from the "
            "clipboard whenever no text field has the focus."
        )
        self._items: list[Reference] = []

        self._empty = QLabel("Drop images here\nor use Load / Paste / Ctrl+V")
        self._empty.setObjectName("hint")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._strip_host = QWidget()
        self._strip_host.setObjectName("scrollViewport")
        self._strip = QHBoxLayout(self._strip_host)
        self._strip.setContentsMargins(0, 0, 0, 0)
        self._strip.setSpacing(6)
        # Keep the thumbnails at the top instead of floating in the middle.
        self._strip.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("thumbsScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(self._strip_host)
        self._scroll.setVisible(False)

        self._count = QLabel("")
        self._count.setObjectName("hint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self._empty, stretch=1)
        layout.addWidget(self._scroll, stretch=1)
        layout.addWidget(self._count)

    # ---------- contents ----------
    def has_reference(self) -> bool:
        """Whether at least one reference image is loaded."""
        return bool(self._items)

    def count(self) -> int:
        """Number of loaded reference images."""
        return len(self._items)

    def data_list(self) -> list[bytes]:
        """Raw bytes of every reference, ready for a request."""
        return [item.data for item in self._items]

    def pixmaps(self) -> list[QPixmap]:
        """Full-resolution pixmaps of every reference."""
        return [item.pixmap for item in self._items]

    def source_paths(self) -> list[str]:
        """Files the references were loaded from; pasted images contribute nothing."""
        return [item.source_path for item in self._items if item.source_path]

    def clear(self) -> None:
        """Forget every reference image."""
        if not self._items:
            return
        self._items.clear()
        self._rebuild()

    def add_from_file(self, path: str) -> bool:
        """Append the image at ``path``; report whether it was readable."""
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return False
        return self.add_from_bytes(data, source_path=str(path))

    def add_from_bytes(self, data: bytes, source_path: str = "") -> bool:
        """Append an image from raw bytes."""
        image = QImage.fromData(data)
        if image.isNull():
            return False
        self._items.append(
            Reference(data=data, pixmap=QPixmap.fromImage(image), source_path=source_path)
        )
        self._rebuild()
        return True

    def remove(self, index: int) -> None:
        """Drop one reference by index."""
        if 0 <= index < len(self._items):
            del self._items[index]
            self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the thumbnail strip and the counter."""
        while self._strip.count():
            item = self._strip.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Hide it, then delete: setParent(None) would turn the thumbnail
                # into a separate window for a moment, and leaving it visible
                # would leave a ghost until the event loop catches up.
                widget.hide()
                widget.deleteLater()
        for index in range(len(self._items)):
            self._strip.addWidget(self._build_thumb(index))
        self._strip.addStretch(1)

        has_items = bool(self._items)
        self._empty.setVisible(not has_items)
        self._scroll.setVisible(has_items)
        self._count.setText(
            "" if not has_items else f"{len(self._items)} reference image(s) loaded"
        )

    def _build_thumb(self, index: int) -> QWidget:
        """One thumbnail with a small remove button in the corner."""
        holder = QWidget()
        holder.setFixedSize(_THUMB, _THUMB)

        thumb = QPushButton(holder)
        thumb.setGeometry(0, 0, _THUMB, _THUMB)
        thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb.setToolTip(self._items[index].source_path or f"Reference {index + 1}")
        scaled = self._items[index].pixmap.scaled(
            _THUMB - 4,
            _THUMB - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        thumb.setIcon(scaled)
        thumb.setIconSize(scaled.size())
        thumb.clicked.connect(lambda _=False, i=index: self.referenceActivated.emit(i))

        close = QPushButton("×", holder)
        close.setGeometry(_THUMB - _CLOSE - 2, 2, _CLOSE, _CLOSE)
        close.setToolTip("Remove this reference")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(lambda _=False, i=index: self.remove(i))
        return holder

    # ---------- drag & drop ----------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt API
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path:
                    if not self.add_from_file(path):
                        # A folder, a text file or a corrupt image used to be
                        # dropped without a word.
                        self.fileRejected.emit(Path(path).name)
        elif mime.hasImage():
            # An image dragged from another application arrives as a QImage, not as
            # encoded PNG/JPEG bytes, so it has to be encoded before decoding it.
            image = mime.imageData()
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if image.save(buffer, "PNG"):
                    raw = bytes(buffer.data())  # type: ignore[call-overload]
                    self.add_from_bytes(raw)
        self.dropped.emit()
        event.acceptProposedAction()



class WorkspacePanel(QFrame):
    """Left column: reference image and a result view."""

    loadRequested = Signal()
    pasteRequested = Signal()
    clearRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Workspace")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        columns = QHBoxLayout()
        columns.setContentsMargins(8, 4, 8, 8)
        columns.setSpacing(8)
        columns.addWidget(self._build_reference(), stretch=1)
        columns.addWidget(self._build_result(), stretch=2)
        layout.addLayout(columns)

    def _build_reference(self) -> QWidget:
        box = QFrame()
        box.setObjectName("subPanel")
        column = QVBoxLayout(box)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)

        label = QLabel("Reference images")
        label.setObjectName("panelTitle")
        column.addWidget(label)

        self.reference = ReferencePanel()
        column.addWidget(self.reference, stretch=1)

        buttons = QHBoxLayout()
        load = QPushButton("Load")
        load.setToolTip("One or several images can be selected at once")
        load.clicked.connect(self.loadRequested.emit)
        paste = QPushButton("Paste")
        paste.setToolTip("Add the image copied to the clipboard (or Ctrl+V)")
        paste.clicked.connect(self.pasteRequested.emit)
        clear = QPushButton("Clear all")
        clear.setToolTip("Remove every reference image")
        clear.clicked.connect(self.clearRequested.emit)
        buttons.addWidget(load)
        buttons.addWidget(paste)
        buttons.addWidget(clear)
        column.addLayout(buttons)
        return box

    def _build_result(self) -> QWidget:
        box = QFrame()
        box.setObjectName("subPanel")
        column = QVBoxLayout(box)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)

        label = QLabel("Result")
        label.setObjectName("panelTitle")
        column.addWidget(label)

        self.result_viewer = ResultViewer()
        column.addWidget(self.result_viewer, stretch=1)
        return box

    def show_images(self, images: list[QPixmap], paths: list[str] | None = None) -> None:
        """Show the generated images in the result viewer."""
        self.result_viewer.set_images(images, paths)

    def show_error(self, message: str) -> None:
        """Show an error message in the result area."""
        self.result_viewer.set_error(message)

    @staticmethod
    def bytes_to_pixmap(data: bytes) -> QPixmap:
        """Decode raw image bytes into a pixmap (raises :class:`AppError`)."""
        image = QImage.fromData(data)
        if image.isNull():
            raise AppError("Unsupported image format.")
        return QPixmap.fromImage(image)
