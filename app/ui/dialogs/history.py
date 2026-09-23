"""Generation history window: a table of past attempts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.history_store import HistoryRecord, HistoryStore


class HistoryWindow(QMainWindow):
    """Standalone window listing generation history."""

    def __init__(self, history: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation history")
        self.resize(900, 520)
        self._history = history

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Provider", "Model", "Images", "Cost, RUB", "Status"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._open_file)

        clear = QPushButton("Clear history")
        clear.clicked.connect(self._clear)

        controls = QHBoxLayout()
        controls.addWidget(clear)
        controls.addStretch(1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        self.setCentralWidget(container)

        self.reload()

    def reload(self) -> None:
        """Rebuild the table from the history store."""
        records = self._history.records()
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            for column, text in enumerate(self._row_values(record)):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.file_paths)
                self.table.setItem(row, column, item)

    @staticmethod
    def _row_values(record: HistoryRecord) -> list[str]:
        cost = "—" if record.cost_rub is None else f"{record.cost_rub:.2f}"
        return [
            record.timestamp,
            record.provider_id,
            record.model,
            str(record.n),
            cost,
            record.status,
        ]

    def _open_file(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        paths = item.data(Qt.ItemDataRole.UserRole) or []
        if paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(paths[0]))))

    def _clear(self) -> None:
        self._history.clear()
        self.reload()
