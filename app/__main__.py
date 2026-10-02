"""Application entry point: ``python -m app``."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import APP_ICON_PATH, APP_NAME, DATA_DIR
from app.logging_setup import get_logger
from app.ui.single_instance import SingleInstanceGuard, server_name


def main() -> int:
    """Start the application and return an exit code."""
    logger = get_logger()
    logger.info("Starting %s", APP_NAME)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 9))
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    from app.ui.main_window import MainWindow

    guard = SingleInstanceGuard(server_name(DATA_DIR))
    if not guard.acquire():
        logger.info("Refused a second window: %s is already open", APP_NAME)
        QMessageBox.information(
            None,
            APP_NAME,
            f"{APP_NAME} уже открыт.\n\n"
            "Второе окно закрыто, чтобы не перезаписать историю и настройки.",
        )
        return 0

    window = MainWindow()
    guard.set_activation_callback(lambda: _raise_window(window))
    app.aboutToQuit.connect(guard.release)
    window.show()
    return app.exec()


def _raise_window(window: object) -> None:
    """Bring the existing window forward when a second launch asks for it."""
    show_normal = getattr(window, "showNormal", None)
    if callable(show_normal):
        if window.isMinimized():  # type: ignore[attr-defined]
            show_normal()
    window.show()  # type: ignore[attr-defined]
    window.raise_()  # type: ignore[attr-defined]
    window.activateWindow()  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())
