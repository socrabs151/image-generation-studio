"""Workspace panel: reference image input and generation result.

The reference area accepts a drag-and-dropped image or a pasted image and exposes
the loaded bytes. The result area shows one image or a grid when several were
generated.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import AppError
from app.ui.widgets.result_viewer import ResultViewer


class ReferenceArea(QLabel):
    """Drop target for a reference image."""

    referenceChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(140)
        self.setAcceptDrops(True)
        self._data: bytes | None = None
        self._reset_text()

    def has_reference(self) -> bool:
        """Whether a reference image is loaded."""
        return self._data is not None

    def data(self) -> bytes | None:
        """Raw bytes of the reference image, if any."""
        return self._data

    def clear(self) -> None:
        """Forget the current reference image."""
        self._data = None
        self.setPixmap(QPixmap())
        self._reset_text()
        self.referenceChanged.emit()

    def set_from_file(self, path: str) -> None:
        """Load a reference image from a file path."""
        try:
            with open(path, "rb") as handle:
                self._set_data(handle.read())
        except OSError as exc:
            self.setText(f"Cannot read image: {exc}")

    def set_from_bytes(self, data: bytes) -> None:
        """Set the reference image from raw bytes."""
        self._set_data(data)

    def _set_data(self, data: bytes) -> None:
        image = QImage.fromData(data)
        if image.isNull():
            self.setText("Unsupported image format")
            return
        self._data = data
        self._update_pixmap(image)
        self.referenceChanged.emit()

    def _update_pixmap(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image).scaled(
            self.width() or 260,
            self.minimumHeight(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)

    def _reset_text(self) -> None:
        self.setText("Drop an image here\nor click «Load»")

    # ---------- drag & drop ----------
    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        mime = event.mimeData()
        if mime.hasUrls():
            path = mime.urls()[0].toLocalFile()
            if path:
                self.set_from_file(path)
        elif mime.hasImage():
            image = QImage(mime.imageData())
            if not image.isNull():
                self.set_from_bytes(bytes(QPixmap.fromImage(image).toImage().bits()))
        event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Ctrl+V support is handled by the parent window; clicking does nothing.
        super().mousePressEvent(event)


class WorkspacePanel(QFrame):
    """Left column: reference image and a result view."""

    loadRequested = Signal()
    clearRequested = Signal()

    def __init__(self, parent=None) -> None:
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

        label = QLabel("Reference image")
        label.setObjectName("panelTitle")
        column.addWidget(label)

        self.reference = ReferenceArea()
        column.addWidget(self.reference, stretch=1)

        buttons = QHBoxLayout()
        load = QPushButton("Load")
        load.clicked.connect(self.loadRequested.emit)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clearRequested.emit)
        buttons.addWidget(load)
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

    def show_images(self, images: list[QPixmap]) -> None:
        """Show the generated images in the result viewer."""
        self.result_viewer.set_images(images)

    def show_error(self, message: str) -> None:
        """Show an error message in the result area."""
        self.result_viewer.set_images([])
        placeholder = QLabel(message)
        placeholder.setObjectName("dropArea")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # ResultViewer exposes its view label for transient messages.
        self.result_viewer._view.setText(message)
        placeholder.deleteLater()

    @staticmethod
    def bytes_to_pixmap(data: bytes) -> QPixmap:
        """Decode raw image bytes into a pixmap (raises :class:`AppError`)."""
        image = QImage.fromData(data)
        if image.isNull():
            raise AppError("Unsupported image format.")
        return QPixmap.fromImage(image)
