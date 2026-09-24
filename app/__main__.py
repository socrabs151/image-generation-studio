"""Application entry point: ``python -m app``."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app.config import APP_ICON_PATH, APP_NAME
from app.logging_setup import get_logger


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

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
