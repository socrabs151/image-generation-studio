"""A standalone image viewer window: zoom, navigation, filmstrip and export.

Used to inspect a generated image (or a reference) at full size. The window keeps the
image centred, follows its own size in fit mode, zooms around the pointer and supports
the keyboard: arrows move between images, ``+``/``-`` zoom, ``0`` fits, ``1`` shows the
real size, ``F11`` toggles full screen, ``Esc`` closes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.focus_widgets import focus_is_text_input
from app.ui.widgets.result_viewer import ZoomableView

_FILM_THUMB = 56
_STATUS_MS = 2200
_FORMATS = "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp)"


def _format_for_filter(selected_filter: str) -> str:
    """Map the chosen file dialog filter to a format name for ``QPixmap.save``."""
    if "JPEG" in selected_filter:
        return "JPG"
    if "WebP" in selected_filter:
        return "WEBP"
    return "PNG"


def _format_name(pixmap: QPixmap) -> str:
    """A short name for the pixel format, for the information line."""
    try:
        return str(QImage.Format(int(pixmap.toImage().format().value)).name).removeprefix(
            "Format_"
        )
    except (ValueError, AttributeError):
        return ""


def _human_size(size: int) -> str:
    """A file size in units a person reads quickly."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class _Filmstrip(QScrollArea):
    """A row of small previews of the whole set, the current one highlighted."""

    picked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filmScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setFixedHeight(_FILM_THUMB + 24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._host = QWidget()
        self._row = QHBoxLayout(self._host)
        self._row.setContentsMargins(4, 4, 4, 4)
        self._row.setSpacing(6)
        self._row.addStretch(1)
        self.setWidget(self._host)
        self._buttons: list[QPushButton] = []

    def set_images(self, images: list[QPixmap], current: int) -> None:
        """Rebuild the strip for a new set of images."""
        for button in self._buttons:
            self._row.removeWidget(button)
            button.hide()
            button.deleteLater()
        self._buttons.clear()
        for index, pixmap in enumerate(images):
            button = QPushButton()
            button.setObjectName("filmThumb")
            button.setFixedSize(QSize(_FILM_THUMB, _FILM_THUMB))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Image {index + 1}")
            thumb = pixmap.scaled(
                _FILM_THUMB - 4,
                _FILM_THUMB - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            button.setIcon(thumb)
            button.setIconSize(thumb.size())
            button.clicked.connect(lambda _checked=False, i=index: self.picked.emit(i))
            self._row.insertWidget(self._row.count() - 1, button)
            self._buttons.append(button)
        self.set_current(current)

    def set_current(self, index: int) -> None:
        """Highlight the image in view."""
        for position, button in enumerate(self._buttons):
            button.setChecked(position == index)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._buttons:
            self.ensureWidgetVisible(self._buttons[0])


class ImageViewerWindow(QMainWindow):
    """A window showing a set of images with navigation, zoom and export."""

    def __init__(
        self,
        images: list[QPixmap],
        index: int = 0,
        paths: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = list(paths) if paths else []
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

        self.setWindowTitle("Image viewer")
        self.resize(1040, 780)
        self.setMinimumSize(560, 420)

        self.viewer = ZoomableView()
        self.viewer.set_images(images, index)
        self.viewer.scaleChanged.connect(self._on_scale_changed)

        self._build_top_bar()
        self._build_bottom_bar()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._top_bar)
        layout.addWidget(self.viewer, stretch=1)
        layout.addWidget(self._bottom_bar)
        self.setCentralWidget(container)
        self._update_state()

    # ---------- construction ----------
    def _build_top_bar(self) -> None:
        self._top_bar = QFrame()
        self._top_bar.setObjectName("viewerTopBar")

        self._previous = self._button("◀", self._go_previous, "Previous image (Left)")
        self._next = self._button("▶", self._go_next, "Next image (Right)")
        self._counter = QLabel("")
        self._counter.setObjectName("viewerCounter")
        self._info = QLabel("")
        self._info.setObjectName("hint")

        self._zoom_out = self._button("−", self.viewer.zoom_out, "Zoom out (−)")
        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("viewerZoom")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setMinimumWidth(56)
        self._zoom_in = self._button("+", self.viewer.zoom_in, "Zoom in (+)")
        self._fit = self._button("Fit", self.viewer.zoom_fit, "Fit to the window (0)")
        self._actual = self._button("1:1", self.viewer.zoom_actual, "Real size (1)")

        row = QHBoxLayout(self._top_bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(4)
        row.addWidget(self._previous)
        row.addWidget(self._next)
        row.addWidget(self._counter)
        row.addSpacing(12)
        row.addWidget(self._info, stretch=1)
        row.addWidget(self._zoom_out)
        row.addWidget(self._zoom_label)
        row.addWidget(self._zoom_in)
        row.addSpacing(8)
        row.addWidget(self._fit)
        row.addWidget(self._actual)

    def _build_bottom_bar(self) -> None:
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("viewerBottomBar")

        self.filmstrip = _Filmstrip()
        self.filmstrip.picked.connect(self._go_to)
        self.filmstrip.set_images(self.viewer.images(), self.viewer.index())

        self._status = QLabel("")
        self._status.setObjectName("hint")
        self._status.setVisible(False)

        self._open_folder = self._button(
            "Open folder", self._open_folder_action, "Show the file in its folder"
        )
        self._copy = self._button("Copy", self._copy_action, "Copy the image (Ctrl+C)")
        self._save = self._button("Save as…", self._save_as, "Save the image (Ctrl+S)")

        actions = QHBoxLayout()
        actions.setContentsMargins(8, 6, 8, 6)
        actions.setSpacing(6)
        actions.addWidget(self._status)
        actions.addStretch(1)
        actions.addWidget(self._open_folder)
        actions.addWidget(self._copy)
        actions.addWidget(self._save)

        layout = QVBoxLayout(self._bottom_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filmstrip)
        layout.addLayout(actions)
        self.filmstrip.setVisible(self.viewer.count() > 1)

    def _button(
        self, text: str, slot: Callable[[], None], tip: str = ""
    ) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip:
            button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    # ---------- state ----------
    def _update_state(self) -> None:
        """Refresh every label and button for the image in view."""
        pixmap = self.viewer.current_pixmap()
        count = self.viewer.count()
        index = self.viewer.index()
        has_image = pixmap is not None

        self._counter.setText(f"{index + 1} / {count}" if has_image else "")
        self._previous.setEnabled(has_image and count > 1)
        self._next.setEnabled(has_image and count > 1)
        toggles = (self._zoom_in, self._zoom_out, self._fit, self._actual)
        for button in toggles + (self._copy, self._save):
            button.setEnabled(has_image)
        self._open_folder.setEnabled(bool(self._current_path()))
        self.filmstrip.setVisible(count > 1)
        self.filmstrip.set_current(index)
        self._info.setText(self._describe(pixmap))
        self._update_title(pixmap)
        self._update_zoom_label()

    def _current_path(self) -> str:
        if 0 <= self.viewer.index() < len(self._paths):
            return self._paths[self.viewer.index()]
        return ""

    def _describe(self, pixmap: QPixmap | None) -> str:
        """Dimensions, format and file size of the image in view."""
        if pixmap is None or pixmap.isNull():
            return ""
        parts = [f"{pixmap.width()}×{pixmap.height()}"]
        name = _format_name(pixmap)
        if name:
            parts.append(name)
        path = self._current_path()
        if path:
            try:
                parts.append(_human_size(Path(path).stat().st_size))
            except OSError:
                pass
            parts.append(Path(path).name)
        return " · ".join(parts)

    def _update_title(self, pixmap: QPixmap | None) -> None:
        path = self._current_path()
        if path:
            self.setWindowTitle(f"{Path(path).name} — Image viewer")
        elif pixmap is not None:
            self.setWindowTitle(f"Image {self.viewer.index() + 1} — Image viewer")
        else:
            self.setWindowTitle("Image viewer")

    def _update_zoom_label(self) -> None:
        self._zoom_label.setText(f"{round(self.viewer.effective_scale() * 100):d}%")
        self._fit.setProperty("active", self.viewer.is_fit)
        self._actual.setProperty("active", not self.viewer.is_fit)
        for button in (self._fit, self._actual):
            button.style().unpolish(button)
            button.style().polish(button)

    def _on_scale_changed(self, _scale: float) -> None:
        self._update_zoom_label()

    def _set_status(self, text: str) -> None:
        """Show a short-lived confirmation in the bottom bar."""
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status_timer.start(_STATUS_MS)

    def _clear_status(self) -> None:
        self._status.clear()
        self._status.setVisible(False)

    # ---------- navigation ----------
    def _go_previous(self) -> None:
        if self.viewer.count() > 1:
            self._go_to(self.viewer.index() - 1)

    def _go_next(self) -> None:
        if self.viewer.count() > 1:
            self._go_to(self.viewer.index() + 1)

    def _go_to(self, index: int) -> None:
        count = self.viewer.count()
        if not count:
            return
        self.viewer.set_index(index % count)
        self._clear_status()
        self._update_state()

    # ---------- actions ----------
    def _save_as(self) -> None:
        pixmap = self.viewer.current_pixmap()
        if pixmap is None:
            return
        suggested = Path(self._current_path()).name or "image.png"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Save image", suggested, _FORMATS
        )
        if not path:
            return
        image_format = _format_for_filter(chosen)
        if not pixmap.save(path, image_format):
            QMessageBox.critical(
                self,
                "Cannot save the image",
                f"The image could not be written to:\n{path}\n\n"
                "Check that the folder exists and is writable.",
            )
            return
        self._set_status(f"Saved to {Path(path).name}")

    def _copy_action(self) -> None:
        pixmap = self.viewer.current_pixmap()
        if pixmap is None:
            return
        QGuiApplication.clipboard().setPixmap(pixmap)
        self._set_status("The image is in the clipboard")

    def _open_folder_action(self) -> None:
        path = self._current_path()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ---------- keyboard ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        key = event.key()
        modifiers = event.modifiers()
        control = modifiers & Qt.KeyboardModifier.ControlModifier

        if control and key == Qt.Key.Key_S:
            self._save_as()
        elif control and key == Qt.Key.Key_C and not focus_is_text_input(
            QApplication.focusWidget()
        ):
            self._copy_action()
        elif key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_F11:
            self._toggle_full_screen()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._go_previous()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space):
            self._go_next()
        elif key == Qt.Key.Key_Home:
            self._go_to(0)
        elif key == Qt.Key.Key_End:
            self._go_to(self.viewer.count() - 1)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.viewer.zoom_in()
            self._update_zoom_label()
        elif key == Qt.Key.Key_Minus:
            self.viewer.zoom_out()
            self._update_zoom_label()
        elif key == Qt.Key.Key_0:
            self.viewer.zoom_fit()
            self._update_state()
        elif key == Qt.Key.Key_1:
            self.viewer.zoom_actual()
            self._update_state()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
