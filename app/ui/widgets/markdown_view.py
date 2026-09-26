"""Widget that displays a rendered Markdown document.

The rendering itself lives in :mod:`app.ui.markdown`, which does not need Qt.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

from app.ui.markdown import ERROR_COLOR, LIGHT_COLORS, THEME_COLORS, render_markdown


class MarkdownView(QTextBrowser):
    """Markdown document rendered as themed rich text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setMinimumHeight(220)
        self._theme = "light"
        self._content = ""
        self.document().setDefaultStyleSheet(LIGHT_COLORS.stylesheet())
        self.anchorClicked.connect(self._open_link)

    def theme(self) -> str:
        """The theme the document is currently rendered with."""
        return self._theme

    def set_theme(self, theme: str) -> None:
        """Switch the palette and re-render the document that is on screen."""
        theme = theme if theme in THEME_COLORS else "light"
        if theme == self._theme:
            return
        self._theme = theme
        self.set_markdown(self._content)

    def set_markdown(self, content: str) -> None:
        """Render Markdown text and return the view to the top."""
        self._content = content
        colors = THEME_COLORS[self._theme]
        self.setHtml(render_markdown(content, self._theme))
        self.document().setDefaultStyleSheet(colors.stylesheet())
        self.verticalScrollBar().setValue(0)

    def show_placeholder(self, message: str) -> None:
        """Show a muted hint while no document is selected."""
        self._content = ""
        colors = THEME_COLORS[self._theme]
        self.setHtml(
            f"<p style='color:{colors.muted}; margin: 40px; text-align:center;'>"
            f"{html.escape(message)}</p>"
        )

    def set_error(self, message: str) -> None:
        """Show a failure message instead of a document."""
        self._content = ""
        error_color = ERROR_COLOR[self._theme]
        self.setHtml(
            f"<p style='color:{error_color}; margin: 16px;'>{html.escape(message)}</p>"
        )

    @staticmethod
    def _open_link(url) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
