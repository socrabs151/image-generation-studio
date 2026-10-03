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
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.models import GenerationRequest
from app.core.pricing import format_money
from app.services.history_stats import (
    filter_options,
    filter_records,
    summarize,
    to_csv,
    to_json,
    totals_by_model,
)
from app.services.history_store import HistoryRecord, HistoryStore
from app.ui.dialogs.export_dialog import ExportDialog

PROMPT_ROLE = Qt.ItemDataRole.UserRole
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
_RECORD_ROLE = Qt.ItemDataRole.UserRole + 2

_PROMPT_PREVIEW = 60
_ANY = "All"
_MAX_THUMBNAILS = 12
_THUMB_SIZE = QSize(88, 88)


class HistoryWindow(QMainWindow):
    """Standalone window listing generation history."""

    def __init__(
        self,
        history: HistoryStore,
        on_use: Callable[[HistoryRecord], None] | None = None,
        on_repeat: Callable[[HistoryRecord], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generation history")
        self.resize(1080, 680)
        self._history = history
        self._on_use = on_use
        self._on_repeat = on_repeat
        self._all_records: list[HistoryRecord] = []
        self._records: list[HistoryRecord] = []

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Aggregator", "Model", "Prompt", "Images", "Cost, RUB", "Status"]
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

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search prompts…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        self.provider_filter = self._combo()
        self.model_filter = self._combo()
        self.status_filter = self._combo()
        for combo in (self.provider_filter, self.model_filter, self.status_filter):
            combo.currentIndexChanged.connect(self._apply_filters)

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
        self.export_button = QPushButton("Export…")
        self.export_button.clicked.connect(self.export)

        # A failed attempt shows its error under the table, where the thumbnails of a
        # successful one appear, so that the reason is always in front of the user.
        self._error_text = QTextEdit()
        self._error_text.setReadOnly(True)
        self._error_text.setObjectName("errorText")
        self._error_copy = QPushButton("Copy")
        self._error_copy.setToolTip("Copy the error text to the clipboard")
        self._error_copy.clicked.connect(self._copy_error)
        self._error_box = QFrame()
        error_layout = QHBoxLayout(self._error_box)
        error_layout.setContentsMargins(8, 8, 8, 8)
        error_layout.setSpacing(8)
        error_layout.addWidget(self._error_text, stretch=1)
        error_layout.addWidget(self._error_copy, alignment=Qt.AlignmentFlag.AlignTop)
        self._error_box.setFixedHeight(120)
        self._error_box.setVisible(False)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("docsTitle")
        self.breakdown_label = QLabel("")
        self.breakdown_label.setObjectName("hint")
        self.breakdown_label.setWordWrap(True)

        controls = QHBoxLayout()
        controls.addWidget(self.use_button)
        controls.addWidget(self.repeat_button)
        controls.addWidget(self.open_button)
        controls.addWidget(self.delete_button)
        controls.addStretch(1)
        controls.addWidget(self.export_button)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        filters.addWidget(self.search, stretch=1)
        self._add_facet(filters, "Aggregator", self.provider_filter, 140)
        self._add_facet(filters, "Model", self.model_filter, 300)
        self._add_facet(filters, "Status", self.status_filter, 110)
        layout.addLayout(filters)
        layout.addWidget(self.totals_label)
        layout.addWidget(self.breakdown_label)
        layout.addLayout(controls)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self._details)
        layout.addWidget(self._thumbs_scroll)
        layout.addWidget(self._error_box)
        self.setCentralWidget(container)

        self.reload()

    # ---------- data ----------
    def reload(self) -> None:
        """Rebuild the table from the history store, keeping the filters."""
        self._all_records = self._history.records()
        providers, models, statuses = filter_options(self._all_records)
        self._fill_facet(self.provider_filter, providers)
        self._fill_facet(self.model_filter, models)
        self._fill_facet(self.status_filter, statuses)
        self._apply_filters()

    @staticmethod
    def _fill_facet(combo: QComboBox, values: list[str]) -> None:
        """Refresh the values of a filter without losing the chosen one."""
        chosen = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_ANY, "")
        for value in values:
            combo.addItem(value, value)
        index = combo.findData(chosen)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _apply_filters(self) -> None:
        """Show the records that match the search phrase and the chosen facets."""
        self._records = filter_records(
            self._all_records,
            query=self.search.text(),
            provider=self.provider_filter.currentData() or "",
            model=self.model_filter.currentData() or "",
            status=self.status_filter.currentData() or "",
        )
        self._fill_table()
        self._show_totals()

    def visible_records(self) -> list[HistoryRecord]:
        """The records currently shown, i.e. after the filters."""
        return list(self._records)

    def _show_totals(self) -> None:
        """Refresh the totals line and the per-model breakdown."""
        records = self._records
        self.totals_label.setText(summarize(records).summary())
        groups = totals_by_model(records)[:5]
        if not groups:
            self.breakdown_label.setText("Nothing to show for these filters.")
            return
        parts = [
            f"{group.name} — {group.spent_rub:.2f} ₽ ({group.images} img)"
            for group in groups
        ]
        self.breakdown_label.setText("Top models: " + "; ".join(parts))

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

    # ---------- helpers ----------
    @staticmethod
    def _combo() -> QComboBox:
        """A filter combo; its label is a separate widget so it never gets replaced."""
        combo = QComboBox()
        combo.addItem(_ANY, "")
        return combo

    @staticmethod
    def _add_facet(row: QHBoxLayout, label: str, combo: QComboBox, width: int) -> None:
        """Add a labelled filter combo to the filter row."""
        caption = QLabel(label)
        caption.setObjectName("hint")
        combo.setMaximumWidth(width)
        row.addWidget(caption)
        row.addWidget(combo)

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
        if record is None:
            self._details.setText("Select an entry to see its parameters.")
            self._clear_thumbnails()
            self._clear_error()
            self._sync_buttons(None)
            return
        self._details.setText(self._describe(record))
        self._show_thumbnails(record)
        self._show_error(record)
        self._sync_buttons(record)

    def _copy_error(self) -> None:
        """Put the error of the selected entry into the clipboard."""
        text = self._error_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _clear_error(self) -> None:
        self._error_text.clear()
        self._error_box.setVisible(False)

    def _show_error(self, record: HistoryRecord) -> None:
        """Show the error of a failed entry in place of the thumbnails."""
        self._clear_error()
        if not record.error:
            return
        self._error_text.setPlainText(record.error)
        self._error_box.setVisible(True)

    @staticmethod
    def _describe(record: HistoryRecord) -> str:
        parts = [f"Status: {record.status}"]
        if record.error:
            parts.append("failed — see the error below")
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
            names = [Path(path).name or path for path in references]
            shown = names[:3] + ([f"+{len(names) - 3}"] if len(names) > 3 else [])
            parts.append("reference: " + ", ".join(shown))
        return " · ".join(parts)

    def _clear_thumbnails(self) -> None:
        while self._thumbs_row.count() > 1:
            item = self._thumbs_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                # Hide it, then delete: setParent(None) would turn the widget into
                # a separate window for a moment, and leaving it visible would
                # leave a ghost until the event loop catches up.
                widget.hide()
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
            # Keep the aspect ratio: a stretched thumbnail misrepresents the result.
            thumb = pixmap.scaled(
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            button.setIcon(thumb)
            button.setIconSize(thumb.size())
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
        self._thumbs_scroll.setVisible(bool(record.file_paths) and not record.error)

    # ---------- actions ----------
    def _sync_buttons(self, record: HistoryRecord | None = None) -> None:
        """Enable the actions that make sense for the given entry.

        The record is passed in because the selection signal can arrive before
        ``currentItem()`` reports the new row.
        """
        if record is None:
            record = self.selected_record()
        has_record = record is not None
        self.use_button.setEnabled(has_record)
        self.repeat_button.setEnabled(has_record)
        self.delete_button.setEnabled(has_record)
        self.open_button.setEnabled(bool(record and record.file_paths))

    def _emit_use(self) -> None:
        record = self.selected_record()
        if record is not None and self._on_use is not None:
            self._on_use(record)

    def _emit_repeat(self) -> None:
        record = self.selected_record()
        if record is not None and self._on_repeat is not None:
            self._on_repeat(record)

    def _open_file(self, *_args: object) -> None:
        record = self.selected_record()
        if record is None or not record.file_paths:
            return
        self._open_path(record.file_paths[0])

    @staticmethod
    def _open_path(path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path))))

    def _delete_selected(self) -> None:
        """Delete the selected entry after asking, and say what is lost with it.

        The entry also leaves the totals, so the cost stops counting. That is not
        something a single press should do by surprise: the dialog names the
        model, the prompt and the amount.
        """
        record = self.selected_record()
        if record is None:
            return
        cost = format_money(record.cost_rub)
        detail = (
            f"{record.timestamp}\n"
            f"{record.provider_id} · {record.model}\n\n"
            f"Prompt: {record.prompt[:200]}"
        )
        if len(record.prompt) > 200:
            detail += "…"
        if record.cost_rub is not None:
            detail += f"\n\nCost: {cost} ₽. It will stop counting in the totals."
        if record.file_paths:
            detail += "\n\nThe saved files stay on disk and are not removed."
        answer = QMessageBox.warning(
            self,
            "Delete this entry?",
            f"{detail}\n\nThis cannot be undone. Export the history first if you may"
            " need it later.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._history.delete(record.id)
        self.reload()

    def export(self) -> None:
        """Ask for a format and write the entries currently shown."""
        records = self.visible_records()
        if not records:
            QMessageBox.information(self, "Nothing to export", "No entries match the filters.")
            return
        dialog = ExportDialog(parent=self)
        if not dialog.exec():
            return
        target = dialog.target()
        if target is None:
            return
        try:
            if dialog.export_format == "json":
                target.write_text(to_json(records), encoding="utf-8")
            else:
                target.write_text(to_csv(records), encoding="utf-8", newline="")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(
            self, "Exported", f"{len(records)} entries written to {target.name}."
        )


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
