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

from app.providers import provider_ids
from app.services.settings_store import Settings


class SettingsDialog(QDialog):
    """Edit application settings."""

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        self._settings = settings
        self._key_fields: dict[str, QLineEdit] = {}

        tabs = QTabWidget()
        tabs.addTab(self._tab_general(), "General")
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
        self.provider.addItems(provider_ids())
        self.provider.setCurrentText(self._settings.default_provider)
        self.model = QLineEdit(self._settings.default_model)
        self.auto_refresh = QCheckBox("Refresh the model catalog on startup")
        self.auto_refresh.setChecked(self._settings.auto_refresh_catalog)

        form = QFormLayout()
        form.addRow("Default provider:", self.provider)
        form.addRow("Default model:", self.model)
        form.addRow("", self.auto_refresh)
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

        box_history = QGroupBox("History")
        history_form = QFormLayout(box_history)
        self.history_limit = QLineEdit(str(self._settings.history_limit))
        history_form.addRow("Maximum records:", self.history_limit)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(box_dir)
        layout.addWidget(box_history)
        layout.addStretch(1)
        return container

    def _tab_providers(self) -> QWidget:
        form = QFormLayout()
        for provider_id in provider_ids():
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            settings = self._settings.providers.get(provider_id)
            field.setText(settings.api_key if settings else "")
            self._key_fields[provider_id] = field
            form.addRow(f"{provider_id} API key:", field)
        hint = QLabel("Keys are stored locally in data/settings.json and never committed.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return self._wrap(form)

    def _tab_interface(self) -> QWidget:
        self.theme = QComboBox()
        self.theme.addItems(["light", "dark"])
        self.theme.setCurrentText(self._settings.theme)
        form = QFormLayout()
        form.addRow("Theme:", self.theme)
        return self._wrap(form)

    # ---------- helpers ----------
    def _pick_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Image destination", self.save_dir.text()
        )
        if chosen:
            self.save_dir.setText(chosen)

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
            if existing is not None:
                providers[provider_id] = replace(existing, api_key=key)
        try:
            limit = max(1, int(self.history_limit.text()))
        except ValueError:
            limit = self._settings.history_limit
        return replace(
            self._settings,
            default_provider=self.provider.currentText(),
            default_model=self.model.text().strip(),
            auto_refresh_catalog=self.auto_refresh.isChecked(),
            save_dir=self.save_dir.text().strip(),
            history_limit=limit,
            theme=self.theme.currentText(),
            providers=providers,
        )
