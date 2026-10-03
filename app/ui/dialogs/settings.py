"""Settings dialog: general, saving, providers and interface tabs.

The dialog edits a copy of :class:`Settings` and returns it on accept; persistence is
handled by the caller through :class:`SettingsStore`.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.providers import provider_choices
from app.services.file_names import (
    DEFAULT_FILENAME_TEMPLATE,
    PLACEHOLDERS,
    NameParts,
    render_filename,
    unknown_placeholders,
)
from app.services.settings_store import ProviderSettings, Settings


class SettingsDialog(QDialog):
    """Edit application settings."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        self._settings = settings
        self._key_fields: dict[str, QLineEdit] = {}

        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), "General")
        tabs.addTab(self._tab_spending(), "Spending")
        tabs.addTab(self._tab_saving(), "Saving")
        tabs.addTab(self._tab_providers(), "Providers")
        tabs.addTab(self._tab_interface(), "Interface")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ---------- tabs ----------
    def _tab_general(self) -> QWidget:
        self.provider = QComboBox()
        for provider_id, name in provider_choices():
            self.provider.addItem(name, provider_id)
        self._select_provider(self._settings.default_provider)
        self.model = QLineEdit(self._settings.default_model)
        self.auto_refresh = QCheckBox("Refresh the model catalog on startup")
        self.auto_refresh.setChecked(self._settings.auto_refresh_catalog)

        form = QFormLayout()
        form.addRow("Default aggregator:", self.provider)
        form.addRow("Default model:", self.model)
        form.addRow("", self.auto_refresh)
        return self._wrap(form)

    def _select_provider(self, provider_id: str) -> None:
        index = self.provider.findData(provider_id)
        self.provider.setCurrentIndex(index if index >= 0 else 0)

    def _tab_spending(self) -> QWidget:
        form = QFormLayout()
        self.confirm_threshold = QLineEdit(self._money(self._settings.confirm_threshold_rub))
        self.session_limit = QLineEdit(self._money(self._settings.session_limit_rub))
        self.generation_timeout = QLineEdit(str(self._settings.generation_timeout))

        form.addRow("Confirm when the estimate exceeds (₽, 0 = never):", self.confirm_threshold)
        form.addRow("Session spend limit (₽, 0 = no limit):", self.session_limit)
        form.addRow("Request timeout (s):", self.generation_timeout)

        hint = QLabel(
            "The estimate comes from the aggregator's catalog and equals its max price × n. "
            "The catalog calls those prices approximate: the real cost depends on the "
            "resolution and the amount of generated data, so it can be higher than the "
            "estimate. The exact amount is reported by the aggregator afterwards."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _tab_saving(self) -> QWidget:
        box_dir = QGroupBox("Image destination")
        dir_layout = QVBoxLayout(box_dir)
        row = QHBoxLayout()
        self.save_dir = QLineEdit(self._settings.save_dir)
        browse = QPushButton("…")
        browse.clicked.connect(self._pick_dir)
        row.addWidget(self.save_dir, stretch=1)
        row.addWidget(browse)
        dir_layout.addLayout(row)

        box_name = QGroupBox("File names")
        name_form = QFormLayout(box_name)
        self.filename_template = QLineEdit(self._settings.filename_template)
        self.filename_template.setPlaceholderText(DEFAULT_FILENAME_TEMPLATE)
        name_form.addRow("Template:", self.filename_template)
        hint = QLabel("Placeholders: " + ", ".join(PLACEHOLDERS))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        name_form.addRow("", hint)
        preview = QLabel("")
        preview.setObjectName("hint")
        preview.setWordWrap(True)
        self._name_preview = preview
        self.filename_template.textChanged.connect(self._update_preview)
        name_form.addRow("", preview)
        self._update_preview(self.filename_template.text())

        box_history = QGroupBox("History")
        history_form = QFormLayout(box_history)
        self.history_limit = QLineEdit(str(self._settings.history_limit))
        history_form.addRow("Maximum records:", self.history_limit)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(box_dir)
        layout.addWidget(box_name)
        layout.addWidget(box_history)
        layout.addStretch(1)
        return container

    def _tab_providers(self) -> QWidget:
        form = QFormLayout()
        for provider_id, name in provider_choices():
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(f"{name} API key")
            settings = self._settings.providers.get(provider_id)
            field.setText(settings.api_key if settings else "")
            self._key_fields[provider_id] = field
            form.addRow(f"{name}:", field)
        hint = QLabel("Keys are stored locally in data/settings.json and never committed.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _tab_interface(self) -> QWidget:
        self.theme = QComboBox()
        self.theme.addItems(["light", "dark"])
        self.theme.setCurrentText(self._settings.theme)
        self.notify_on_finish = QCheckBox("Notify when a generation finishes")
        self.notify_on_finish.setChecked(self._settings.notify_on_finish)
        self.notify_on_finish.setToolTip(
            "Only while the window is in the background: a notification next to the "
            "window you are already looking at is just noise."
        )
        form = QFormLayout()
        form.addRow("Theme:", self.theme)
        form.addRow("", self.notify_on_finish)
        return self._wrap(form)

    def _update_preview(self, template: str) -> None:
        """Show what the template would name right now."""
        unknown = unknown_placeholders(template)
        if unknown:
            self._name_preview.setText("Unknown: " + ", ".join(unknown))
            return
        sample = NameParts(
            model=self._selected_model_name() or "model-name",
            provider=self._settings.default_provider,
            prompt="prompt text",
            index=1,
            total=1,
        )
        try:
            self._name_preview.setText("Example: " + render_filename(template, sample) + ".png")
        except Exception:  # noqa: BLE001 - a preview must never break the dialog
            self._name_preview.setText("")

    def _selected_model_name(self) -> str:
        return self._settings.default_model

    # ---------- helpers ----------
    def _pick_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Image destination", self.save_dir.text()
        )
        if chosen:
            self.save_dir.setText(chosen)

    @staticmethod
    def _money(value: float) -> str:
        return f"{value:.2f}" if value else "0"

    @staticmethod
    def _wrap(form: QFormLayout) -> QWidget:
        container = QWidget()
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        container.setLayout(form)
        return container

    def result_settings(self) -> Settings:
        """Return a new settings object with the edited values applied."""
        providers = dict(self._settings.providers)
        for provider_id, field in self._key_fields.items():
            key = field.text().strip()
            existing = providers.get(provider_id)
            # A provider missing from the file must still get the key that was
            # just typed, otherwise it is saved and then reported as missing.
            if existing is not None:
                providers[provider_id] = replace(existing, api_key=key)
            else:
                providers[provider_id] = ProviderSettings(api_key=key)
        try:
            limit = max(1, int(self.history_limit.text()))
        except ValueError:
            limit = self._settings.history_limit
        return replace(
            self._settings,
            default_provider=self.provider.currentData(),
            default_model=self.model.text().strip(),
            auto_refresh_catalog=self.auto_refresh.isChecked(),
            save_dir=self.save_dir.text().strip(),
            filename_template=self.filename_template.text().strip(),
            notify_on_finish=self.notify_on_finish.isChecked(),
            history_limit=limit,
            theme=self.theme.currentText(),
            confirm_threshold_rub=self._parse_float(self.confirm_threshold, 50.0),
            session_limit_rub=self._parse_float(self.session_limit, 0.0),
            generation_timeout=self._parse_int(self.generation_timeout, 180),
            providers=providers,
        )

    @staticmethod
    def _parse_float(field: QLineEdit, default: float) -> float:
        try:
            return max(0.0, float(field.text().strip() or default))
        except ValueError:
            return default

    @staticmethod
    def _parse_int(field: QLineEdit, default: int) -> int:
        try:
            return max(1, int(field.text().strip() or default))
        except ValueError:
            return default
