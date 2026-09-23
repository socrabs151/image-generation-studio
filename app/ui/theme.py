"""Loading and applying application themes from ``resources/themes``."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.config import THEMES_DIR

AVAILABLE_THEMES = ("light", "dark")
DEFAULT_THEME = "light"


def theme_path(theme: str) -> str:
    """Return the QSS file path for a theme name."""
    name = theme if theme in AVAILABLE_THEMES else DEFAULT_THEME
    return str(THEMES_DIR / f"{name}.qss")


def apply_theme(app: QApplication, theme: str) -> str:
    """Apply a theme to the whole application and return the applied name."""
    name = theme if theme in AVAILABLE_THEMES else DEFAULT_THEME
    try:
        with open(theme_path(name), encoding="utf-8") as handle:
            app.setStyleSheet(handle.read())
    except OSError:
        app.setStyleSheet("")
    return name
