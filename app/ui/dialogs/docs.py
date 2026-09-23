"""Documentation window: a tree of aggregator reference files and a Markdown viewer.

The tree is built from ``docs/<provider>/*.md``. Markdown is rendered to HTML through
``markdown-it-py`` and shown in a ``QTextBrowser`` (no embedded browser required).
"""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import DOCS_DIR


class MarkdownView(QTextBrowser):
    """Markdown document rendered to HTML."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setMinimumHeight(200)
        self._md = MarkdownIt().enable("table").enable("strikethrough")

    def set_markdown(self, content: str) -> None:
        """Render Markdown text."""
        self.setHtml(self._md.render(content) if content else "(empty file)")


class DocsViewer(QWidget):
    """Tree of aggregators plus a Markdown viewer."""

    def __init__(self, docs_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._docs_dir = Path(docs_dir) if docs_dir else DOCS_DIR

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setMinimumWidth(220)
        splitter.addWidget(self.tree)

        self.viewer = MarkdownView()
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        header = QLabel("Aggregator documentation — select a file on the left")
        header.setObjectName("hint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(header)
        layout.addWidget(splitter, stretch=1)

        self._populate()
        self.tree.currentItemChanged.connect(self._show_selected)

    def _populate(self) -> None:
        self.tree.clear()
        if not self._docs_dir.is_dir():
            placeholder = QTreeWidgetItem()
            placeholder.setText(0, self._docs_dir.name)
            placeholder.setDisabled(True)
            self.tree.addTopLevelItem(placeholder)
            return
        for provider in sorted(p for p in self._docs_dir.iterdir() if p.is_dir()):
            provider_item = QTreeWidgetItem()
            provider_item.setText(0, provider.name)
            for file in sorted(p for p in provider.iterdir() if p.suffix.lower() == ".md"):
                item = QTreeWidgetItem()
                item.setText(0, file.stem)
                item.setData(0, Qt.ItemDataRole.UserRole, str(file))
                provider_item.addChild(item)
            self.tree.addTopLevelItem(provider_item)

    def _show_selected(self, current: QTreeWidgetItem | None, _previous) -> None:
        path = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.viewer.setPlainText(f"Cannot read file: {exc}")
            return
        self.viewer.set_markdown(content)


class DocsWindow(QMainWindow):
    """Standalone documentation window."""

    def __init__(self, docs_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aggregator documentation")
        self.resize(1100, 700)
        self.setCentralWidget(DocsViewer(docs_dir))
