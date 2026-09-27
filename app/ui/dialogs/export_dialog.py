"""Modal dialog for exporting the generation history.

The window asks for the format first and then for the file name, so the suffix and
the file filter always match the chosen format.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

FORMATS = {
    "csv": ("CSV (spreadsheet)", "CSV (*.csv);;All files (*)"),
    "json": ("JSON (full structure)", "JSON (*.json);;All files (*)"),
}


class ExportDialog(QDialog):
    """Choose the export format and the destination file."""

    def __init__(self, suggested_name: str = "history", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export history")
        self.setMinimumWidth(460)

        self.format_combo = QComboBox()
        for suffix, (label, _filter) in FORMATS.items():
            self.format_combo.addItem(label, suffix)
        self.format_combo.currentIndexChanged.connect(self._update_suffix)

        self.path_edit = QLineEdit(f"{suggested_name}.csv")
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.path_edit, stretch=1)
        row.addWidget(browse)

        note = QLabel("The export covers the entries currently shown by the filters.")
        note.setObjectName("hint")
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Format:", self.format_combo)
        form.addRow("Save to:", _wrap(row))
        form.addRow("", note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._update_suffix()

    @property
    def export_format(self) -> str:
        """Chosen format suffix, ``csv`` or ``json``."""
        return str(self.format_combo.currentData())

    def target(self) -> Path | None:
        """Chosen file, with the suffix of the format; ``None`` when unusable."""
        text = self.path_edit.text().strip()
        if not text or not Path(text).name:
            return None
        return self._with_suffix(Path(text))

    def _with_suffix(self, path: Path) -> Path:
        suffix = f".{self.export_format}"
        if path.suffix.lower() == suffix:
            return path
        return path.with_suffix(suffix)

    def _update_suffix(self) -> None:
        current = self.path_edit.text().strip()
        if current and Path(current).name:
            self.path_edit.setText(str(self._with_suffix(Path(current))))

    def _browse(self) -> None:
        _label, file_filter = FORMATS[self.export_format]
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export history",
            self.path_edit.text().strip(),
            file_filter,
        )
        if chosen:
            self.path_edit.setText(chosen)


def _wrap(layout) -> QWidget:
    container = QWidget()
    container.setLayout(layout)
    return container
