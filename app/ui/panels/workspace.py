"""Workspace panel: reference images and the generation result.

The reference area holds a **list** of images: several files can be loaded at once,
dropped, or pasted one after another, because models accept up to sixteen references.
Clicking a thumbnail opens the whole set in a viewer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, QThreadPool, Signal
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
from app.workers import FunctionWorker

_THUMB = 96
_CLOSE = 20


@dataclass(frozen=True, slots=True)
class ReferenceSource:
    """Where a reference image comes from: a file to read, or bytes in hand.

    ``data`` is what the clipboard and a drag from another program hand over
    already; ``path`` is what a file dialog and the explorer give.
    """

    path: str = ""
    data: bytes | None = None


@dataclass(slots=True)
class DecodedReference:
    """An image decoded off the GUI thread, waiting for a thumbnail."""

    data: bytes
    image: QImage
    source_path: str


def read_and_decode(sources: list[ReferenceSource]) -> tuple[list[DecodedReference], list[str]]:
    """Read and decode every source; report the ones that failed by name.

    This runs in a worker thread on purpose. Reading sixteen 15 MB files and
    decoding them takes seconds, and on the GUI thread the window is simply dead
    for those seconds — the user cannot even move the mouse.

    Only decoding happens here. Building a ``QPixmap`` stays on the GUI thread,
    because Qt forbids painting resources from anywhere else.
    """
    decoded: list[DecodedReference] = []
    failed: list[str] = []
    for source in sources:
        name = Path(source.path).name if source.path else "pasted image"
        data = source.data
        if data is None:
            try:
                with open(source.path, "rb") as handle:
                    data = handle.read()
            except OSError:
                failed.append(name)
                continue
        image = QImage.fromData(data)
        if image.isNull():
            failed.append(name)
            continue
        decoded.append(DecodedReference(data=data, image=image, source_path=source.path))
    return decoded, failed


@dataclass(slots=True)
class Reference:
    """One loaded reference image.

    The raw bytes are the reference; ``thumbnail`` is all the strip ever draws.
    A full-resolution pixmap is deliberately not kept: sixteen 4K references would
    hold hundreds of megabytes until the panel is cleared, and nothing on screen
    is bigger than one thumbnail.
    """

    data: bytes
    thumbnail: QPixmap
    source_path: str = ""


class ReferencePanel(QWidget):
    """Drop target and thumbnail strip holding every loaded reference image."""

    referenceActivated = Signal(int)
    fileRejected = Signal(str)
    referencesLoaded = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        # Focusable so that a dropped or pasted image is obvious as the current
        # target, and so the panel can be reached from the keyboard.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Reading and decoding happen here, not on the GUI thread.
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        # A worker is kept alive only by Qt; without a reference of our own the
        # Python object can be collected mid-run.
        self._workers: set[FunctionWorker] = set()
        self._pending = 0
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

    def full_pixmaps(self) -> list[QPixmap]:
        """Full-resolution pixmaps, built on demand for the image viewer.

        Nothing keeps these: the viewer asks for them when it opens and drops them
        when it closes, so the memory is spent only while a reference is actually
        being looked at.
        """
        return [QPixmap.fromImage(QImage.fromData(item.data)) for item in self._items]

    def source_paths(self) -> list[str]:
        """Files the references were loaded from; pasted images contribute nothing."""
        return [item.source_path for item in self._items if item.source_path]

    def clear(self) -> None:
        """Forget every reference image."""
        if not self._items:
            return
        self._items.clear()
        self._rebuild()

    def add_files(self, paths: Sequence[str]) -> None:
        """Load the images at ``paths`` in the background."""
        self._load_async([ReferenceSource(path=path) for path in paths if path])

    def add_data(self, blobs: Sequence[bytes]) -> None:
        """Load images the clipboard or another application already gave as bytes."""
        self._load_async([ReferenceSource(data=blob) for blob in blobs])

    def loading(self) -> bool:
        """Whether references are still being read."""
        return self._pending > 0

    def _load_async(self, sources: list[ReferenceSource]) -> None:
        """Read and decode off the GUI thread, then add the results here."""
        if not sources:
            return
        self._pending += 1
        self._update_count()
        worker = FunctionWorker(read_and_decode, sources)
        worker.signals.finished.connect(self._on_decoded)
        worker.signals.failed.connect(self._on_failed)
        self._workers.add(worker)
        self._pool.start(worker)

    def _on_failed(self, message: str) -> None:
        """A worker that could not even report which files failed."""
        self._pending = max(0, self._pending - 1)
        self._workers.clear()
        self._update_count()
        self.fileRejected.emit("selected images")

    def _on_decoded(self, outcome: tuple[list[DecodedReference], list[str]]) -> None:
        """Add what was decoded. Runs on the GUI thread, where pixmaps are legal."""
        decoded, failed = outcome
        for item in decoded:
            # Scale the QImage before it becomes a pixmap: the full-size pixmap
            # would cost 32 MB for a 4K picture and is never drawn.
            self._items.append(
                Reference(
                    data=item.data,
                    thumbnail=QPixmap.fromImage(
                        item.image.scaled(
                            _THUMB - 4,
                            _THUMB - 4,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    ),
                    source_path=item.source_path,
                )
            )
        if decoded:
            # One rebuild for the whole batch: sixteen files used to rebuild the
            # strip sixteen times.
            self._rebuild()
        for name in failed:
            self.fileRejected.emit(name)
        if decoded:
            self.referencesLoaded.emit(len(decoded))
        self._pending = max(0, self._pending - 1)
        self._workers.clear()
        self._update_count()

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

        self._update_count()

    def _update_count(self) -> None:
        """Refresh the strip visibility and the counter, progress included."""
        has_items = bool(self._items)
        self._empty.setVisible(not has_items and not self.loading())
        self._scroll.setVisible(has_items)
        if self.loading():
            self._count.setText("Reading reference image(s)...")
            return
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
        scaled = self._items[index].thumbnail
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
            sources = [ReferenceSource(path=url.toLocalFile()) for url in mime.urls()]
            self._load_async([source for source in sources if source.path])
        elif mime.hasImage():
            # An image dragged from another application arrives as a QImage, not as
            # encoded PNG/JPEG bytes, so it has to be encoded before decoding it.
            image = mime.imageData()
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if image.save(buffer, "PNG"):
                    raw = bytes(buffer.data())  # type: ignore[call-overload]
                    self.add_data([raw])
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
