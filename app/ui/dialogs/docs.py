"""Documentation window: a tree of aggregator reference files and a Markdown viewer.

The tree is built from ``docs/<provider>/*.md``. Markdown is rendered by
:mod:`app.ui.widgets.markdown_view`, which highlights code and follows the
application theme.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import DOCS_DIR
from app.providers import display_name
from app.ui.widgets.markdown_view import MarkdownView

_PATH_ROLE = Qt.ItemDataRole.UserRole


class DocsViewer(QWidget):
    """Tree of aggregators plus a Markdown viewer."""

    def __init__(self, docs_dir: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._docs_dir = Path(docs_dir) if docs_dir else DOCS_DIR

        self._title = QLabel("Select a document on the left")
        self._title.setObjectName("docsTitle")
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("hint")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.tree = QTreeWidget()
        self.tree.setObjectName("docsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.setMinimumWidth(230)
        splitter.addWidget(self.tree)

        self.viewer = MarkdownView()
        self.viewer.setObjectName("docsViewer")
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 840])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self._title)
        header.addStretch(1)
        layout.addLayout(header)
        layout.addWidget(self._subtitle)
        layout.addWidget(splitter, stretch=1)

        self._populate()
        self.tree.currentItemChanged.connect(self._show_selected)
        self.tree.itemActivated.connect(self._show_selected)
        self.tree.itemClicked.connect(self._toggle_group)
        if not self._docs_dir.is_dir():
            self._title.setText("No documents")
        else:
            self.viewer.show_placeholder("Select a document to read it")

    # ---------- tree ----------
    def _populate(self) -> None:
        self.tree.clear()
        if not self._docs_dir.is_dir():
            placeholder = QTreeWidgetItem()
            placeholder.setText(0, self._docs_dir.name)
            placeholder.setDisabled(True)
            self.tree.addTopLevelItem(placeholder)
            self._subtitle.setText(f"Folder not found: {self._docs_dir}")
            return
        bold = QFont()
        bold.setBold(True)
        for provider in sorted(p for p in self._docs_dir.iterdir() if p.is_dir()):
            provider_item = QTreeWidgetItem()
            name = display_name(provider.name) or provider.name
            files = sorted(p for p in provider.iterdir() if p.suffix.lower() == ".md")
            provider_item.setText(0, f"{name}  ·  {len(files)}")
            provider_item.setToolTip(0, f"{provider.name} — {len(files)} files")
            provider_item.setFont(0, bold)
            provider_item.setData(0, _PATH_ROLE, str(provider))
            for file in files:
                item = QTreeWidgetItem()
                item.setText(0, file.stem)
                item.setData(0, _PATH_ROLE, str(file))
                provider_item.addChild(item)
            # Start collapsed: the list of aggregators is the entry point, and an
            # expanded group would also select a document the user did not ask for.
            provider_item.setExpanded(False)
            self.tree.addTopLevelItem(provider_item)

    def _toggle_group(self, item: QTreeWidgetItem, _column: int) -> None:
        """Expand or collapse an aggregator row when it is clicked."""
        if item.childCount():
            item.setExpanded(not item.isExpanded())

    def set_theme(self, theme: str) -> None:
        """Forward a theme change to the viewer."""
        self.viewer.set_theme(theme)

    # ---------- viewer ----------
    def _show_selected(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        raw = current.data(0, _PATH_ROLE) if current else None
        if not raw:
            return
        path = Path(raw)
        if path.is_dir():
            return
        self._title.setText(path.stem)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._subtitle.setText(path.as_posix())
            self.viewer.set_error(f"Cannot read file: {exc}")
            return
        lines = text.count("\n") + 1 if text else 0
        self._subtitle.setText(f"{path.as_posix()}  ·  {lines} lines")
        self.viewer.set_markdown(text)


class DocsWindow(QMainWindow):
    """Standalone documentation window."""

    def __init__(self, docs_dir: Path | None = None, theme: str = "light", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aggregator documentation")
        self.resize(1150, 760)
        self.viewer = DocsViewer(docs_dir, parent=self)
        self.setCentralWidget(self.viewer)
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        """Re-render the open document in the given theme."""
        self.viewer.set_theme(theme)
