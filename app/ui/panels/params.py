"""Model parameters panel.

Fields are populated from the selected model capabilities. Values that a model does
not support are hidden or disabled, so the user cannot send invalid parameters.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from app.core.models import ModelInfo
from app.ui.widgets.number_field import NumberField

_NONE = "auto"


class ParamsPanel(QFrame):
    """Panel with generation parameters."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("Parameters")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(8, 4, 8, 8)
        form.setSpacing(4)

        self.n_field = NumberField(1, 10, 1)
        self.quality = self._combo()
        self.resolution = self._combo()
        self.format = self._combo()
        self.seed = QLineEdit()
        self.seed.setPlaceholderText("random")
        self.background = self._combo()
        self._passthrough_fields: dict[str, QLineEdit] = {}

        form.addRow("Count", self.n_field)
        form.addRow("Quality", self.quality)
        form.addRow("Resolution", self.resolution)
        form.addRow("Format", self.format)
        form.addRow("Seed", self.seed)
        form.addRow("Background", self.background)
        layout.addLayout(form)

        self._passthrough_title = QLabel("Provider-specific parameters")
        self._passthrough_title.setObjectName("panelTitle")
        self._passthrough_title.setVisible(False)
        layout.addWidget(self._passthrough_title)

        self._passthrough_form = QFormLayout()
        self._passthrough_form.setContentsMargins(8, 4, 8, 4)
        self._passthrough_form.setSpacing(4)
        layout.addLayout(self._passthrough_form)

        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.set_model(None)

    @staticmethod
    def _combo() -> QComboBox:
        combo = QComboBox()
        combo.setEditable(False)
        return combo

    def set_model(self, model: ModelInfo | None) -> None:
        """Populate the fields from a model's capabilities."""
        self.n_field.setValue(1)
        self._clear_passthrough()
        if model is None:
            self.hint.setText("Select a model to see its parameters.")
            for widget in (self.quality, self.resolution, self.format, self.background):
                widget.clear()
                widget.setEnabled(False)
            return

        self.n_field.setValue(min(self.n_field.value(), model.max_n))
        self._fill(self.quality, model.qualities)
        self._fill(self.resolution, model.resolutions)
        self._fill(self.format, model.formats)
        self._fill(self.background, model.backgrounds)
        self._build_passthrough(model.allowed_passthrough)
        self.hint.setText(
            f"Model supports: n≤{model.max_n}, references≤{model.max_input_references}. "
            "Unsupported fields stay empty."
        )

    def _build_passthrough(self, names: list[str]) -> None:
        self._passthrough_title.setVisible(bool(names))
        for name in names:
            field = QLineEdit()
            field.setPlaceholderText("empty")
            self._passthrough_fields[name] = field
            self._passthrough_form.addRow(name, field)

    def _clear_passthrough(self) -> None:
        while self._passthrough_form.rowCount():
            self._passthrough_form.removeRow(0)
        self._passthrough_fields.clear()
        self._passthrough_title.setVisible(False)

    @staticmethod
    def _fill(combo: QComboBox, values: list[str]) -> None:
        combo.clear()
        if not values:
            combo.setEnabled(False)
            return
        combo.setEnabled(True)
        combo.addItem(_NONE)
        combo.addItems(values)

    # ---------- reading values ----------
    def selected_n(self) -> int:
        """Requested number of images."""
        return self.n_field.value()

    def selected_quality(self) -> str | None:
        """Selected quality, or ``None`` when auto/unset."""
        return self._value(self.quality)

    def selected_resolution(self) -> str | None:
        """Selected resolution, or ``None`` when auto/unset."""
        return self._value(self.resolution)

    def selected_format(self) -> str | None:
        """Selected output format, or ``None`` when auto/unset."""
        return self._value(self.format)

    def selected_background(self) -> str | None:
        """Selected background, or ``None`` when auto/unset."""
        return self._value(self.background)

    def selected_seed(self) -> int | None:
        """Parsed seed value, or ``None`` when empty/invalid."""
        text = self.seed.text().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    @staticmethod
    def _value(combo: QComboBox) -> str | None:
        if not combo.isEnabled():
            return None
        text = combo.currentText()
        return None if text in ("", _NONE) else text

    def selected_passthrough(self) -> dict:
        """Provider-specific parameters entered by the user (non-empty only)."""
        return {
            name: field.text().strip()
            for name, field in self._passthrough_fields.items()
            if field.text().strip()
        }
