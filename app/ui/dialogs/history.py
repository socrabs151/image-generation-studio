"""Generation history window: past attempts, their prompts and the saved images.

The table lists one row per attempt. Selecting a row shows the parameters that were
used and, below, the images the run produced. ``Use prompt`` and ``Repeat`` hand the
values back to the main window; ``Repeat`` only fills the form and never starts a
generation, because a generation spends money.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import GenerationRequest
from app.services.history_store import HistoryRecord, HistoryStore

PROMPT_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_RECORD_ROLE = Qt.ItemDataRole.UserRole + 2

_PROMPT_PREVIEW = 60
_MAX_THUMBNAILS = 12
_THUMB_SIZE = QSize(88, 88)


class HistoryWindow(QMainWindow):
    """Standalone window listing generation history."""

    def __init__(
        self,
        history: HistoryStore,
        on_use: Callable[[HistoryRecord], None] | None = None,
        on_repeat: Callable[[HistoryRecord], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation history")
        self.resize(1080, 680)
        self._history = history
        self._on_use = on_use
        self._on_repeat = on_repeat
        self._records: list[HistoryRecord] = []

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Provider", "Model", "Prompt", "Images", "Cost, RUB", "Status"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.cellDoubleClicked.connect(self._open_file)

        self._details = QLabel("Select an entry to see its parameters.")
        self._details.setObjectName("hint")
        self._details.setWordWrap(True)

        self._thumbs_host = QWidget()
        self._thumbs_row = QHBoxLayout(self._thumbs_host)
        self._thumbs_row.setContentsMargins(0, 0, 0, 0)
        self._thumbs_row.setSpacing(6)
        self._thumbs_row.addStretch(1)
        self._thumbs_scroll = QScrollArea()
        self._thumbs_scroll.setObjectName("thumbsScroll")
        self._thumbs_scroll.setWidgetResizable(True)
        self._thumbs_scroll.setWidget(self._thumbs_host)
        self._thumbs_scroll.setFixedHeight(120)
        self._thumbs_scroll.setVisible(False)

        self.use_button = QPushButton("Use prompt")
        self.use_button.clicked.connect(self._emit_use)
        self.repeat_button = QPushButton("Repeat")
        self.repeat_button.setToolTip(
            "Fill the parameters panel with this request. Nothing is generated."
        )
        self.repeat_button.clicked.connect(self._emit_repeat)
        self.open_button = QPushButton("Open image")
        self.open_button.clicked.connect(self._open_file)
        self.delete_button = QPushButton("Delete entry")
        self.delete_button.clicked.connect(self._delete_selected)

        controls = QHBoxLayout()
        controls.addWidget(self.use_button)
        controls.addWidget(self.repeat_button)
        controls.addWidget(self.open_button)
        controls.addWidget(self.delete_button)
        controls.addStretch(1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(controls)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self._details)
        layout.addWidget(self._thumbs_scroll)
        self.setCentralWidget(container)

        self.reload()

    # ---------- data ----------
    def reload(self) -> None:
        """Rebuild the table from the history store."""
        self._records = self._history.records()
        self._fill_table()

    def _fill_table(self) -> None:
        selected = self.selected_id()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            for column, text in enumerate(self._row_values(record)):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setToolTip(record.prompt or "—")
                if column == 6 and record.status != "ok":
                    item.setToolTip(record.error)
                self.table.setItem(row, column, item)
            self._attach_record(row, record)
            self._decorate_row(row, record)
        self.table.setSortingEnabled(True)
        self._select_id(selected)
        self._sync_buttons()

    def _attach_record(self, row: int, record: HistoryRecord) -> None:
        """Attach the record id and object to the row so lookups stay stable."""
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is not None:
                item.setData(_ID_ROLE, record.id)
                item.setData(_RECORD_ROLE, record)

    def _decorate_row(self, row: int, record: HistoryRecord) -> None:
        """Mark a failed attempt in red."""
        if record.status == "ok":
            return
        status = self.table.item(row, 6)
        if status is not None:
            status.setForeground(Qt.GlobalColor.red)

    @staticmethod
    def _row_values(record: HistoryRecord) -> list[str]:
        cost = "—" if record.cost_rub is None else f"{record.cost_rub:.2f}"
        prompt = " ".join((record.prompt or "").split())
        if len(prompt) > _PROMPT_PREVIEW:
            prompt = prompt[: _PROMPT_PREVIEW - 1] + "…"
        return [
            record.timestamp.replace("T", " "),
            record.provider_id,
            record.model,
            prompt or "—",
            str(len(record.file_paths) or record.n),
            cost,
            record.status,
        ]

    def _store_record(self, row: int) -> None:
        """Attach the record id and object to the row so lookups stay stable."""
        record = self._records[row]
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is not None:
                item.setData(_ID_ROLE, record.id)
                item.setData(_RECORD_ROLE, record)

    def selected_record(self) -> HistoryRecord | None:
        """The record of the selected row, if any."""
        item = self.table.currentItem()
        if item is None:
            return None
        record = item.data(_RECORD_ROLE)
        return record if isinstance(record, HistoryRecord) else None

    def selected_id(self) -> str:
        """The id of the selected record, empty when nothing is selected."""
        item = self.table.currentItem()
        return str(item.data(_ID_ROLE)) if item is not None and item.data(_ID_ROLE) else ""

    def _select_id(self, record_id: str) -> None:
        if not record_id:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(_ID_ROLE) == record_id:
                self.table.selectRow(row)
                return

    # ---------- details ----------
    def _show_selected(self) -> None:
        record = self.selected_record()
        self._sync_buttons()
        if record is None:
            self._details.setText("Select an entry to see its parameters.")
            self._clear_thumbnails()
            return
        self._details.setText(self._describe(record))
        self._show_thumbnails(record)

    @staticmethod
    def _describe(record: HistoryRecord) -> str:
        parts = [f"Status: {record.status}"]
        if record.error:
            parts.append(f"error: {record.error}")
        if record.duration_seconds is not None:
            parts.append(f"took {record.duration_seconds:.1f} s")
        if record.has_request_snapshot:
            snapshot = record.request
            shown = [
                f"{key}={value}"
                for key, value in snapshot.items()
                if value not in (None, "", {}, []) and key != "reference_paths"
            ]
            parts.append("request: " + (", ".join(shown) or "defaults"))
        else:
            parts.append("request: not recorded (entry predates the change)")
        references = record.request.get("reference_paths") if record.request else None
        if references:
            parts.append("reference: " + ", ".join(references))
        return " · ".join(parts)

    def _clear_thumbnails(self) -> None:
        while self._thumbs_row.count() > 1:
            item = self._thumbs_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._thumbs_scroll.setVisible(False)

    def _show_thumbnails(self, record: HistoryRecord) -> None:
        """Load the images of the record from disk; missing files are reported."""
        self._clear_thumbnails()
        shown = 0
        for path in record.file_paths:
            if shown >= _MAX_THUMBNAILS:
                break
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue
            button = QPushButton()
            button.setFixedSize(_THUMB_SIZE)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(pixmap.scaled(_THUMB_SIZE))
            button.setIconSize(_THUMB_SIZE)
            button.setToolTip(path)
            button.clicked.connect(lambda _=False, p=path: self._open_path(p))
            self._thumbs_row.insertWidget(self._thumbs_row.count() - 1, button)
            shown += 1
        extra = len(record.file_paths) - shown
        if extra > 0:
            self._thumbs_row.insertWidget(
                self._thumbs_row.count() - 1, QLabel(f"+{extra}")
            )
        if record.file_paths and shown == 0:
            self._thumbs_row.insertWidget(
                self._thumbs_row.count() - 1, QLabel("files not found on disk")
            )
        self._thumbs_scroll.setVisible(bool(record.file_paths))

    # ---------- actions ----------
    def _sync_buttons(self) -> None:
        has_record = self.selected_record() is not None
        for button in (self.use_button, self.repeat_button, self.delete_button):
            button.setEnabled(has_record)
        record = self.selected_record()
        self.open_button.setEnabled(bool(record and record.file_paths))

    def _emit_use(self) -> None:
        record = self.selected_record()
        if record is not None and self._on_use is not None:
            self._on_use(record)

    def _emit_repeat(self) -> None:
        record = self.selected_record()
        if record is not None and self._on_repeat is not None:
            self._on_repeat(record)

    def _open_file(self, *_args) -> None:
        record = self.selected_record()
        if record and record.file_paths:
            self._open_path(record.file_paths[0])

    @staticmethod
    def _open_path(path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))

    def _delete_selected(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        self._history.delete(record.id)
        self.reload()


def repeat_request(record: HistoryRecord) -> GenerationRequest:
    """Rebuild a request from a history entry.

    Entries written before the snapshot existed yield a request with the prompt and
    the model only, which is still useful.
    """
    snapshot = record.request or {}
    return GenerationRequest(
        provider_id=record.provider_id,
        model=record.model,
        prompt=record.prompt,
        n=int(snapshot.get("n") or record.n or 1),
        quality=snapshot.get("quality"),
        resolution=snapshot.get("resolution"),
        aspect_ratio=snapshot.get("aspect_ratio"),
        size=snapshot.get("size"),
        output_format=snapshot.get("output_format"),
        background=snapshot.get("background"),
        seed=snapshot.get("seed"),
        passthrough=dict(snapshot.get("passthrough") or {}),
        reference_paths=list(snapshot.get("reference_paths") or []),
    )
