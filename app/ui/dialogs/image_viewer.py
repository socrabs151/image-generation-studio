"""A standalone image viewer window with zoom, navigation and export.

Used to inspect a generated image (or a reference) at full size. Supports zoom
(fit, 100%, in, out), navigation across multiple images and saving or copying the
currently shown one.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMainWindow, QPushButton

from app.ui.widgets.result_viewer import ZoomableView


class ImageViewerWindow(QMainWindow):
    """Separate window showing a set of images with zoom and export."""

    def __init__(self, images: list[QPixmap], index: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Image viewer")
        self.resize(900, 700)

        self.viewer = ZoomableView()
        self.viewer.set_images(images, index)
        self.setCentralWidget(self.viewer)

        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        toolbar.addWidget(self._button("Save as…", self._save_as))
        toolbar.addWidget(self._button("Copy", self._copy))
        toolbar.addStretch(1)
        self.viewer.layout().insertLayout(1, toolbar)

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _save_as(self) -> None:
        pixmap = self.viewer.current_pixmap()
        if pixmap is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save image", "", "PNG (*.png)")
        if path:
            pixmap.save(path)

    def _copy(self) -> None:
        pixmap = self.viewer.current_pixmap()
        if pixmap is None:
            return
        QGuiApplication.clipboard().setPixmap(pixmap)
