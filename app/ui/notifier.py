"""Desktop notifications, shown only when the window is in the background."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from app.logging_setup import get_logger

LOGGER = get_logger()

# Keep the icon alive: a tray icon that goes out of scope stops delivering.
ICON_TEXT = "🖼"


class Notifier:
    """Show a desktop notification when the user is not looking at the window.

    A notification next to a window you are already watching is noise, so this
    stays quiet while the window is active. Everything is guarded: on a system
    without a tray the call does nothing rather than breaking a paid request
    that has already succeeded.
    """

    def __init__(self, window: QWidget, icon: QIcon | None = None) -> None:
        self._window = window
        self._icon = icon
        self._tray: QSystemTrayIcon | None = None

    @property
    def available(self) -> bool:
        """Whether the system can show notifications at all."""
        return bool(QSystemTrayIcon.isSystemTrayAvailable())

    def _ensure_tray(self) -> QSystemTrayIcon | None:
        if not self.available:
            return None
        if self._tray is None:
            tray = QSystemTrayIcon()
            if self._icon is not None:
                tray.setIcon(self._icon)
            tray.show()
            self._tray = tray
        return self._tray

    def notify_finished(self, title: str, message: str) -> bool:
        """Show a notification unless the window is in front. Report if shown."""
        if self._window.isActiveWindow() and not self._window.isMinimized():
            return False
        tray = self._ensure_tray()
        if tray is None:
            LOGGER.info("No system tray, so no notification: %s", title)
            return False
        try:
            tray.showMessage(title, message)
        except Exception as exc:  # noqa: BLE001 - never fail a finished request
            LOGGER.warning("Could not show a notification: %s", exc)
            return False
        return True

    def dispose(self) -> None:
        """Hide the tray icon."""
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
