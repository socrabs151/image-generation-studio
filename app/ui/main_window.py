"""Main application window.

Wires panels, background workers and services together. Network and file operations
run through :class:`FunctionWorker` on a thread pool, so the interface stays
responsive. Generation is never retried automatically.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, QThreadPool
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_ICON_PATH
from app.core.errors import AppError
from app.core.models import AccountInfo, GenerationRequest, ModelInfo
from app.core.pricing import format_money, format_price, reserved_amount
from app.logging_setup import get_logger
from app.providers import create_provider, display_name, provider_choices
from app.services.catalog_service import CatalogResult, CatalogService
from app.services.generation_service import GenerationOutcome, GenerationService
from app.services.history_store import HistoryStore
from app.services.keystore import KeyStore
from app.services.settings_store import SettingsStore
from app.ui.dialogs.docs import DocsWindow
from app.ui.dialogs.history import HistoryWindow
from app.ui.dialogs.image_viewer import ImageViewerWindow
from app.ui.dialogs.settings import SettingsDialog
from app.ui.panels.log import LogPanel
from app.ui.panels.params import ParamsPanel
from app.ui.panels.prompt import PromptPanel
from app.ui.panels.workspace import WorkspacePanel
from app.ui.theme import AVAILABLE_THEMES, apply_theme
from app.workers import FunctionWorker

LOGGER = get_logger()


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image Generation Studio")
        self.resize(1150, 720)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))

        self._pool = QThreadPool.globalInstance()
        self._worker: FunctionWorker | None = None
        self._models: list[ModelInfo] = []
        self._docs_window: DocsWindow | None = None
        self._history_window: HistoryWindow | None = None
        self._theme_actions: dict[str, QAction] = {}
        self._session_spend = 0.0

        self._settings_store = SettingsStore()
        self._settings = self._settings_store.load()
        self._keystore = KeyStore(self._settings_store)
        self._keystore.load()
        self._history = HistoryStore()
        self._catalog = CatalogService()
        self._generation = GenerationService(self._history)

        self._build_ui()
        self._build_menu()
        self._install_shortcuts()
        self._apply_theme(self._settings.theme)

        if self._settings.auto_refresh_catalog:
            self.refresh_catalog()

    # ---------- UI construction ----------
    def _build_ui(self) -> None:
        root = QVBoxLayout()
        root.setContentsMargins(8, 6, 8, 4)
        root.setSpacing(6)
        root.addWidget(self._build_topbar())
        root.addWidget(self._build_model_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.workspace = WorkspacePanel()
        self.params = ParamsPanel()
        splitter.addWidget(self.workspace)
        splitter.addWidget(self.params)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root.addWidget(splitter, stretch=1)

        self.prompt = PromptPanel()
        self.log = LogPanel()
        root.addWidget(self.prompt)
        root.addWidget(self.log)

        self.status = QStatusBar()
        self._status_model = QLabel("Model: —")
        self._status_cost = QLabel("Last generation: —")
        self.status.addWidget(QLabel("Ready"))
        self.status.addPermanentWidget(self._status_model)
        self.status.addPermanentWidget(self._status_cost)
        self.setStatusBar(self.status)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        self.workspace.loadRequested.connect(self._load_reference)
        self.workspace.clearRequested.connect(self.workspace.reference.clear)
        self.workspace.reference.referenceActivated.connect(self._open_reference_viewer)
        self.workspace.result_viewer.imageActivated.connect(self._open_result_viewer)
        self.prompt.generateRequested.connect(self.generate)
        self.prompt.stopRequested.connect(self._cancel_generation)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        row.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        for provider_id, name in provider_choices():
            self._provider_combo.addItem(name, provider_id)
        self._select_provider(self._settings.default_provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_combo.setToolTip(
            "Aggregator used for the catalog, the balance and generation."
        )
        row.addWidget(self._provider_combo)

        row.addWidget(QLabel("Balance:"))
        self._balance_label = QLabel("—")
        row.addWidget(self._balance_label)
        row.addWidget(self._link_button("Check balance", self.check_balance))
        row.addStretch(1)
        row.addWidget(self._link_button("Refresh catalog", self.refresh_catalog))
        row.addWidget(QPushButton("Settings", clicked=self.open_settings))
        row.addWidget(QPushButton("History", clicked=self.open_history))
        return bar

    def _select_provider(self, provider_id: str) -> None:
        """Point the provider combo at ``provider_id`` without notifying listeners."""
        self._provider_combo.blockSignals(True)
        index = self._provider_combo.findData(provider_id)
        self._provider_combo.setCurrentIndex(index if index >= 0 else 0)
        self._provider_combo.blockSignals(False)

    def _on_provider_changed(self, _index: int) -> None:
        """Switch the active aggregator and reload its catalog."""
        provider_id = self._provider_combo.currentData()
        if not provider_id or provider_id == self._settings.default_provider:
            return
        if self._worker is not None:
            self.log.warning("Wait for the current task before switching the provider.")
            self._select_provider(self._settings.default_provider)
            return
        self._settings.default_provider = str(provider_id)
        self._settings_store.save(self._settings)
        self.log.info(f"Provider switched to {display_name(str(provider_id))}.")

        self._models = []
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.blockSignals(False)
        self.params.set_model(None)
        self._status_model.setText("Model: —")
        self.prompt.set_cost_hint("")
        self._balance_label.setText("—")
        self.refresh_catalog()

    def _build_model_bar(self) -> QWidget:
        bar = QWidget()
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(420)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        row.addWidget(self._model_combo, stretch=1)

        help_label = QLabel("ⓘ")
        help_label.setObjectName("hint")
        help_label.setCursor(Qt.CursorShape.WhatsThisCursor)
        help_label.setToolTip(ModelInfo.capabilities_legend())
        row.addWidget(help_label)
        outer.addLayout(row)

        legend = QLabel(
            "refs — reference images for editing · n — images per request · "
            "price — per image"
        )
        legend.setObjectName("hint")
        outer.addWidget(legend)
        return bar

    @staticmethod
    def _link_button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("link")
        button.setFlat(True)
        button.clicked.connect(slot)
        return button

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = bar.addMenu("&View")
        for theme in AVAILABLE_THEMES:
            action = QAction(f"{theme.capitalize()} theme", self, checkable=True)
            action.triggered.connect(lambda _=False, name=theme: self._set_theme(name))
            self._theme_actions[theme] = action
            view_menu.addAction(action)

        docs_menu = bar.addMenu("&Documentation")
        docs_action = QAction("Open documentation", self)
        docs_action.triggered.connect(self.open_docs)
        docs_menu.addAction(docs_action)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(QAction("About", self))

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Return"), self, self.generate)
        QShortcut(QKeySequence("Ctrl+V"), self, self._paste_reference)
        QShortcut(QKeySequence("Delete"), self, self.workspace.reference.clear)

    # ---------- actions ----------
    def refresh_catalog(self) -> None:
        """Load the model catalog (network first, cache as a fallback)."""
        self.log.info("Loading model catalog…")
        provider_id = self._settings.default_provider
        self._run(
            self._catalog.load,
            provider_id,
            api_key=self._keystore.get(provider_id),
            on_done=self._on_catalog_loaded,
            on_fail=self._on_catalog_failed,
        )

    def check_balance(self) -> None:
        """Query the provider for the current balance."""
        provider_id = self._settings.default_provider
        api_key = self._keystore.get(provider_id)
        if not api_key:
            self._warn_no_key()
            return
        self.log.info("Checking balance…")
        self._run(
            create_provider(provider_id, api_key).check_account,
            on_done=self._on_account,
            on_fail=lambda message: self.log.error(f"Balance check failed: {message}"),
        )

    def generate(self) -> None:
        """Validate and run a generation request in the background."""
        if self._worker is not None:
            return
        model = self._selected_model()
        if model is None:
            self.log.warning("Select a model first.")
            return
        provider_id = self._settings.default_provider
        api_key = self._keystore.get(provider_id)
        if not api_key:
            self._warn_no_key()
            return
        if not self._can_spend():
            return

        request = GenerationRequest(
            provider_id=provider_id,
            model=model.id,
            prompt=self.prompt.prompt(),
            n=self.params.selected_n(),
            quality=self.params.selected_quality(),
            resolution=self.params.selected_resolution(),
            output_format=self.params.selected_format(),
            background=self.params.selected_background(),
            seed=self.params.selected_seed(),
            input_references=self._collect_references(),
            passthrough=self.params.selected_passthrough(),
        )
        try:
            self._generation.validate(request, model)
        except AppError as exc:
            self.log.error(str(exc))
            QMessageBox.warning(self, "Invalid request", str(exc))
            return

        reserved = reserved_amount(model.max_price, request.n)
        if reserved is not None:
            self.log.info(
                f"Reserved amount: {format_money(reserved)} ₽ "
                "(max×n, refunded after the response)."
            )
            if not self._confirm_if_expensive(reserved):
                return

        self.prompt.set_busy(True)
        self.log.info(f"Generating with {model.id}…")
        self._run(
            self._generation.generate,
            request,
            model,
            Path(self._settings.save_dir),
            api_key,
            self._settings.history_limit,
            self._settings.generation_timeout,
            on_done=self._on_generated,
            on_fail=self._on_generation_failed,
        )

    def _cancel_generation(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.log.warning("Cancellation requested.")

    def _load_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select reference image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if path:
            self.workspace.reference.set_from_file(path)
            self.log.info(f"Reference loaded: {Path(path).name}")

    def _paste_reference(self) -> None:
        clipboard_image = QGuiApplication.clipboard().image()
        if clipboard_image.isNull():
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        clipboard_image.save(buffer, "PNG")
        self.workspace.reference.set_from_bytes(bytes(buffer.data()))
        self.log.info("Reference pasted from the clipboard.")

    def open_settings(self) -> None:
        """Open the settings dialog and persist changes."""
        dialog = SettingsDialog(self._settings, parent=self)
        if not dialog.exec():
            return
        updated = dialog.result_settings()
        provider_changed = updated.default_provider != self._provider_combo.currentData()
        self._settings = updated
        self._settings_store.save(self._settings)
        self._keystore.load()
        self._apply_theme(self._settings.theme)
        if provider_changed:
            self._select_provider(self._settings.default_provider)
            self._models = []
            self._model_combo.clear()
            self.params.set_model(None)
            self._balance_label.setText("—")
            self.refresh_catalog()
        self.log.info("Settings saved.")

    def open_docs(self) -> None:
        """Open the documentation window."""
        if self._docs_window is None:
            self._docs_window = DocsWindow(theme=self._settings.theme, parent=self)
        self._docs_window.show()
        self._docs_window.raise_()

    def open_history(self) -> None:
        """Open the history window."""
        if self._history_window is None:
            self._history_window = HistoryWindow(self._history, parent=self)
        else:
            self._history_window.reload()
        self._history_window.show()
        self._history_window.raise_()

    # ---------- worker plumbing ----------
    def _run(self, function, *args, on_done, on_fail, **kwargs) -> None:
        worker = FunctionWorker(function, *args, **kwargs)
        worker.setAutoDelete(False)
        worker.signals.finished.connect(on_done)
        worker.signals.failed.connect(on_fail)
        worker.signals.finished.connect(self._clear_worker)
        worker.signals.failed.connect(self._clear_worker)
        self._worker = worker
        self._pool.start(worker)

    def _clear_worker(self, *_args) -> None:
        self._worker = None
        self.prompt.set_busy(False)

    # ---------- worker callbacks ----------
    def _on_catalog_loaded(self, result: CatalogResult) -> None:
        self._models = result.models
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in self._models:
            self._model_combo.addItem(model.display_name())
        self._model_combo.blockSignals(False)
        source = "cache" if result.from_cache else "network"
        self.log.info(f"Catalog loaded: {len(self._models)} models ({source}).")
        if self._models:
            self._model_combo.setCurrentIndex(0)
            self._on_model_changed(0)

    def _on_catalog_failed(self, message: str) -> None:
        self.log.error(f"Catalog load failed: {message}")

    def _on_account(self, account: AccountInfo) -> None:
        balance = f"{format_money(account.balance)} ₽"
        parts = [f"Balance: {balance}"]
        if account.budget_remaining is not None:
            budget = f"{format_money(account.budget_remaining)} ₽"
            if account.budget_initial is not None:
                budget += f" of {format_money(account.budget_initial)} ₽"
            parts.append(f"budget left: {budget}")
        self._balance_label.setText(" · ".join(parts))
        self.log.info(", ".join(parts) + ".")

    def _on_generated(self, outcome: GenerationOutcome) -> None:
        pixmaps = [WorkspacePanel.bytes_to_pixmap(image.data) for image in outcome.result.images]
        self.workspace.show_images(pixmaps)
        cost = format_money(outcome.result.cost_rub)
        self._update_session_spend(outcome.result.cost_rub)
        self.log.info(f"Done. Cost: {cost} ₽. Files saved: {len(outcome.file_paths)}.")

    def _on_generation_failed(self, message: str) -> None:
        if "cancelled" in message.lower():
            self.log.info("Generation cancelled.")
            return
        self.workspace.show_error(message)
        self.log.error(f"Generation failed: {message}")

    # ---------- helpers ----------
    def _selected_model(self) -> ModelInfo | None:
        index = self._model_combo.currentIndex()
        if 0 <= index < len(self._models):
            return self._models[index]
        return None

    def _on_model_changed(self, _index: int) -> None:
        model = self._selected_model()
        self.params.set_model(model)
        if model is None:
            self._status_model.setText("Model: —")
            self.prompt.set_cost_hint("")
            return
        self._status_model.setText(f"Model: {model.id}")
        reserved = reserved_amount(model.max_price, self.params.selected_n())
        self.prompt.set_cost_hint(
            f"Range: {format_price(model.min_price, model.max_price)} ₽ · "
            f"reserved ~{format_money(reserved)} ₽"
        )

    def _collect_references(self) -> list[bytes]:
        reference = self.workspace.reference
        data = reference.data()
        return [data] if reference.has_reference() and data else []

    def _can_spend(self) -> bool:
        """Whether the session spend limit allows another request."""
        limit = self._settings.session_limit_rub
        if limit <= 0:
            return True
        remaining = limit - self._session_spend
        if remaining <= 0:
            self.log.error(
                f"Session spend limit reached: {format_money(self._session_spend)} ₽ "
                f"of {format_money(limit)} ₽."
            )
            QMessageBox.warning(self, "Session limit", "The session spend limit is reached.")
            return False
        if remaining < self._session_spend + 1:
            self.log.warning(f"Session spend remaining: {format_money(remaining)} ₽.")
        return True

    def _confirm_if_expensive(self, reserved: float) -> bool:
        """Ask for confirmation when the reserved amount exceeds the threshold."""
        threshold = self._settings.confirm_threshold_rub
        if threshold <= 0 or reserved <= threshold:
            return True
        answer = QMessageBox.question(
            self,
            "Confirm generation",
            f"The reserved amount is {format_money(reserved)} ₽, which exceeds "
            f"the confirmation threshold of {format_money(threshold)} ₽.\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log.warning("Generation cancelled by the user.")
            return False
        return True

    def _open_reference_viewer(self) -> None:
        pixmap = self.workspace.reference.pixmap()
        if pixmap is None:
            return
        window = ImageViewerWindow([pixmap], parent=self)
        window.show()
        window.raise_()

    def _open_result_viewer(self, index: int) -> None:
        images = self.workspace.result_viewer.images()
        if not images:
            return
        window = ImageViewerWindow(images, index, parent=self)
        window.show()
        window.raise_()

    def _update_session_spend(self, cost_rub: float | None) -> None:
        if cost_rub is not None:
            self._session_spend += cost_rub
        self._status_cost.setText(
            f"Last generation: {format_money(cost_rub)} ₽ · "
            f"session spend: {format_money(self._session_spend)} ₽"
        )

    def _apply_theme(self, theme: str) -> None:
        applied = apply_theme(QGuiApplication.instance(), theme)
        self._settings.theme = applied
        if self._docs_window is not None:
            self._docs_window.set_theme(applied)
        for name, action in self._theme_actions.items():
            action.setChecked(name == applied)

    def _set_theme(self, theme: str) -> None:
        """Apply a theme chosen by the user and persist the choice."""
        self._apply_theme(theme)
        self._settings_store.save(self._settings)

    def _warn_no_key(self) -> None:
        self.log.warning("No API key set. Open Settings and add a key.")
        QMessageBox.information(self, "API key required", "Add an API key in Settings.")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # Cancel the running task and wait for the pool, so no signal is delivered
        # to this window after it is destroyed.
        if self._worker is not None:
            self._worker.cancel()
        self._pool.waitForDone(5000)
        super().closeEvent(event)
