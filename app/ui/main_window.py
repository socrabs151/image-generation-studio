"""Main application window.

Wires panels, background workers and services together. Network and file operations
run through :class:`FunctionWorker` on a thread pool, so the interface stays
responsive. Generation is never retried automatically.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QIODevice,
    QObject,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_ICON_PATH, SETTINGS_FILE
from app.core.errors import AppError, ConfigError
from app.core.models import AccountInfo, GenerationRequest, ModelInfo
from app.core.pricing import format_money, format_price, reserved_amount
from app.logging_setup import get_logger
from app.providers import create_provider, display_name, provider_choices
from app.services.catalog_service import CatalogResult, CatalogService
from app.services.generation_service import GenerationOutcome, GenerationService
from app.services.history_store import HistoryRecord, HistoryStore, request_snapshot
from app.services.keystore import KeyStore
from app.services.settings_store import Settings, SettingsStore
from app.ui.dialogs.docs import DocsWindow
from app.ui.dialogs.history import HistoryWindow, repeat_request
from app.ui.dialogs.image_viewer import ImageViewerWindow
from app.ui.dialogs.settings import SettingsDialog
from app.ui.focus_widgets import focus_is_text_input
from app.ui.icons import BUTTON_ICON_SIZE, LIST_ICON_SIZE, favourite_icon
from app.ui.model_list import (
    combo_label,
    favourite_key,
    is_favourite,
    recent_models,
    remember_model,
    visible_models,
)
from app.ui.panels.log import LogPanel
from app.ui.panels.params import ParamsPanel
from app.ui.panels.prompt import PromptPanel
from app.ui.panels.workspace import WorkspacePanel
from app.ui.request_rules import WorkerSlot, save_folder_problem
from app.ui.theme import AVAILABLE_THEMES, apply_theme
from app.workers import FunctionWorker

LOGGER = get_logger()



def _save_png(image: QImage, buffer: QBuffer) -> bool:
    """Write an image into an open buffer as PNG.

    PySide6 takes a QBuffer at runtime, but the stubs only describe a file name
    or a device plus a format, so the cast is stated once here instead of at
    every call site.
    """
    return bool(image.save(buffer, "PNG"))  # type: ignore[call-overload]


MODEL_COMBO_TOOLTIP = (
    "The model that will generate the image. Favourites are marked with a star and "
    "sit at the top; the parameters below follow the selected model."
)

PLACEHOLDER_NO_MODELS = (
    "No models: the catalog did not load. Press Refresh catalog, and check the API "
    "key in Settings."
)


class MainWindow(QMainWindow):
    """Application main window."""

    #: Emitted after every entry is written to the history, so an open history
    #: window can refresh itself instead of waiting to be closed and reopened.
    history_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Image Generation Studio")
        self.resize(1150, 720)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))

        self._pool = QThreadPool.globalInstance()
        self._worker: FunctionWorker | None = None
        # One slot for the catalog, the balance and a generation: see WorkerSlot.
        self._slot = WorkerSlot()
        self._models: list[ModelInfo] = []
        self._visible: list[ModelInfo] = []
        self._pending_restore: GenerationRequest | None = None
        self._pending_recent: str | None = None
        self._docs_window: DocsWindow | None = None
        self._history_window: HistoryWindow | None = None
        self._theme_actions: dict[str, QAction] = {}
        self._session_spend = 0.0

        self._settings_store = SettingsStore()
        # A damaged settings file must not stop the application from starting: the
        # defaults are loaded instead and the problem is reported in the log panel.
        self._settings, self._settings_problem = self._load_settings()
        self._keystore = KeyStore(self._settings_store)
        self._keystore.load()
        self._history = HistoryStore()
        self._catalog = CatalogService()
        self._generation = GenerationService(self._history)

        self._build_ui()
        self._build_menu()
        self._install_shortcuts()
        self._apply_theme(self._settings.theme)

        if self._settings_problem:
            self.log.error(self._settings_problem)

        if self._settings.auto_refresh_catalog:
            self.refresh_catalog()

    def _load_settings(self) -> tuple[Settings, str]:
        """Load the settings, falling back to defaults when the file is unusable."""
        try:
            return self._settings_store.load(), ""
        except ConfigError as exc:
            message = (
                f"Settings could not be read ({exc}). The application started with "
                "default settings. To recover, close the application and rename "
                f"{SETTINGS_FILE.name} in the data folder, then start it again."
            )
            LOGGER.error("%s", message)
            return Settings(), message

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
        self.log.install_logging_bridge()
        self.params.changed.connect(self._update_cost_hint)
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

        # The star icon needs the model combo, so the button gets its first
        # icon only after the whole bar exists.
        self._update_fav_button()

        self.workspace.loadRequested.connect(self._load_reference)
        self.workspace.pasteRequested.connect(self._paste_reference)
        self.workspace.clearRequested.connect(self.workspace.reference.clear)
        self.workspace.reference.referenceActivated.connect(self._open_reference_viewer)
        self.workspace.reference.fileRejected.connect(
            lambda name: self.log.error(f"Cannot read the image: {name}")
        )
        self.workspace.reference.dropped.connect(self._warn_if_too_many_references)
        self.workspace.result_viewer.imageActivated.connect(self._open_result_viewer)
        self.prompt.generateRequested.connect(self.generate)
        self.prompt.stopRequested.connect(self._cancel_generation)
        self.prompt.clearRequested.connect(self._clear_prompt)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        row.addWidget(QLabel("Aggregator:"))
        self._provider_combo = QComboBox()
        for provider_id, name in provider_choices():
            self._provider_combo.addItem(name, provider_id)
        # The names are short but the combo collapses to nothing without a floor:
        # it was laid out 46 px wide and cut "AITUNNEL" in half. Measured from the
        # font, with room for the arrow.
        self._provider_combo.setMinimumWidth(self._text_width() + 34)
        self._select_provider(self._settings.default_provider)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_combo.setToolTip(
            "Aggregator used for the catalog, the balance and generation."
        )
        row.addWidget(self._provider_combo)

        row.addWidget(QLabel("Balance:"))
        self._balance_label = QLabel("—")
        self._balance_label.setToolTip(
            "The last known balance. It is refreshed before a generation with a "
            "price in the catalog; press Check balance to ask at any other moment."
        )
        row.addWidget(self._balance_label)
        row.addWidget(
            self._link_button(
                "Check balance", self.check_balance, "Ask the aggregator for the balance"
            )
        )
        row.addStretch(1)
        row.addWidget(
            self._link_button(
                "Refresh catalog",
                self.refresh_catalog,
                "Download the model list again. The list is cached on disk, so this is "
                "only needed after the aggregator adds or removes a model.",
            )
        )
        row.addWidget(
            self._plain_button(
                "Settings",
                self.open_settings,
                "API keys, the default model, the save folder and the limits",
            )
        )
        row.addWidget(
            self._plain_button(
                "History",
                self.open_history,
                "Past generations with their cost, parameters and results",
            )
        )
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
            self.log.warning("Wait for the current task before switching the aggregator.")
            self._select_provider(self._settings.default_provider)
            return
        self._settings.default_provider = str(provider_id)
        self._settings_store.save(self._settings)
        self.log.info(f"Aggregator switched to {display_name(str(provider_id))}.")

        self._models = []
        self._visible = []
        self._rebuild_model_list()
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

        self._model_search = QLineEdit()
        self._model_search.setObjectName("modelSearch")
        self._model_search.setPlaceholderText("Search: name, description, aggregator")
        self._model_search.setClearButtonEnabled(True)
        self._model_search.setToolTip(
            "Type to narrow the list below. Matches the model id, its description "
            "and the aggregator."
        )
        self._model_search.setMaximumWidth(320)
        self._model_search.textChanged.connect(self._apply_model_filter)
        row.addWidget(self._model_search)

        self._fav_button = QPushButton()
        self._fav_button.setObjectName("favButton")
        self._fav_button.setCheckable(True)
        self._fav_button.setFixedWidth(34)
        self._fav_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fav_button.setToolTip(
            "Mark the selected model as a favourite. Favourites go to the top of the "
            "list and are marked with a star."
        )
        self._fav_button.toggled.connect(self._on_favourite_toggled)
        row.addWidget(self._fav_button)

        # No "▾" in the text: a button with a menu already gets the platform's own
        # drop-down arrow, and two of them sit side by side.
        self._recent_button = QPushButton("Recent")
        self._recent_button.setObjectName("recentButton")
        self._recent_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recent_button.setToolTip(
            "Models used lately, newest first. Picking one switches the aggregator "
            "and selects it."
        )
        self._recent_menu = QMenu(self._recent_button)
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._recent_button.setMenu(self._recent_menu)
        row.addWidget(self._recent_button)

        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(420)
        self._model_combo.setToolTip(MODEL_COMBO_TOOLTIP)
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
    @staticmethod
    def _plain_button(text: str, slot: Callable[[], None], tool_tip: str) -> QPushButton:
        """A button with a tooltip.

        The keyword form (``QPushButton(text, clicked=..., toolTip=...)``) works
        at runtime but is not in the stubs, and the explicit calls read the same.
        """
        button = QPushButton(text)
        button.setToolTip(tool_tip)
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _link_button(
        text: str, slot: Callable[[], None], tool_tip: str = ""
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("link")
        button.setFlat(True)
        button.setToolTip(tool_tip)
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
        # «Return» is the numeric keypad, «Enter» the main block; bind both so the
        # documented Ctrl+Enter works on an ordinary keyboard.
        for sequence in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(sequence), self, self.generate)
        # Ctrl+V is handled as a key event rather than a window shortcut: a shortcut
        # would either lose the text fields or never fire, while the owner wants the
        # image to go into the references whenever no text field has the focus.
        instance = QApplication.instance()
        if instance is not None:
            instance.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        # The base class takes any QEvent, so the narrowing happens here rather
        # than in the signature.
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_V
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self._paste_applies(obj)
        ):
            self._paste_reference()
            return True
        return super().eventFilter(obj, event)

    def _paste_applies(self, obj: object) -> bool:
        """Whether this Ctrl+V belongs to the workspace rather than to a text field."""
        if not isinstance(obj, QWidget) or not self.isAncestorOf(obj):
            return False
        return not focus_is_text_input(QApplication.focusWidget())

    # ---------- actions ----------
    def refresh_catalog(self) -> None:
        """Load the model catalog (network first, cache as a fallback)."""
        if not self._background_free("Load the catalog"):
            return
        self.log.info("Loading model catalog…")
        provider_id = self._settings.default_provider
        self._run(
            self._catalog.load,
            provider_id,
            api_key=self._keystore.get(provider_id),
            on_done=self._on_catalog_loaded,
            on_fail=self._on_catalog_failed,
            is_generation=False,
        )

    def check_balance(self) -> None:
        """Query the provider for the current balance."""
        if not self._background_free("Check the balance"):
            return
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
            is_generation=False,
        )

    def generate(self) -> None:
        """Validate and run a generation request in the background."""
        if not self._slot.may_start():
            return
        if not self._can_save_to(self._settings.save_dir):
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

        request = GenerationRequest(
            provider_id=provider_id,
            model=model.id,
            prompt=self.prompt.prompt(),
            n=self.params.selected_n(),
            quality=self.params.selected_quality(),
            resolution=self.params.selected_resolution(),
            aspect_ratio=self.params.selected_aspect_ratio(),
            output_format=self.params.selected_format(),
            background=self.params.selected_background(),
            seed=self.params.selected_seed(),
            input_references=self._collect_references(),
            reference_paths=self._reference_paths(),
            passthrough=self.params.selected_passthrough(),
        )
        try:
            self._generation.validate(request, model)
        except AppError as exc:
            self.log.error(str(exc))
            QMessageBox.warning(self, "Invalid request", str(exc))
            return

        reserved = reserved_amount(model.max_price, request.n)
        # The limit is judged against the request, so the check waits until the
        # catalog estimate is known.
        if not self._can_spend(reserved):
            return
        if reserved is not None:
            self.log.info(
                f"Estimate by catalog: {format_money(reserved)} ₽ (max×n). "
                "The provider reports the real cost afterwards, and it can be higher."
            )
            if not self._confirm_if_expensive(reserved):
                return

        self.prompt.set_busy(True)
        self._remember_recent_model(model)
        self.log.info(f"Generating with {model.id}…")
        self._run(
            self._generation.generate,
            request,
            model,
            Path(self._settings.save_dir),
            api_key,
            self._settings.history_limit,
            self._settings.generation_timeout,
            check_balance_first=reserved is not None,
            on_done=self._on_generated,
            on_fail=self._on_generation_failed,
            is_generation=True,
        )

    def _cancel_generation(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.log.warning("Cancellation requested.")

    def _clear_prompt(self) -> None:
        """Empty the prompt editor."""
        self.prompt.set_prompt("")
        self.prompt.editor.setFocus()

    def _load_reference(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select reference images", "", "Images (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if not paths:
            return
        added = 0
        for path in paths:
            if self.workspace.reference.add_from_file(path):
                added += 1
            else:
                self.log.error(f"Cannot read the image: {Path(path).name}")
        if added:
            self.log.info(f"Reference images loaded: {added}.")
        self._warn_if_too_many_references()

    def _paste_reference(self) -> None:
        """Add the clipboard image, or the copied image file, to the references.

        The clipboard holds different things depending on what was copied: bitmap
        data when an image is copied, but a file list when the file itself is copied
        in the explorer. Both are accepted; anything else is reported in the log
        instead of doing nothing quietly.
        """
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.ReadWrite)
            _save_png(image, buffer)
            data = bytes(buffer.data())  # type: ignore[call-overload]
            if self.workspace.reference.add_from_bytes(data):
                self.log.info("Reference pasted from the clipboard.")
            self._warn_if_too_many_references()
            return

        mime = clipboard.mimeData()
        if mime is None:
            # An empty or locked clipboard reports nothing at all, which is a
            # normal state and not a reason to raise.
            self.log.warning(
                "The clipboard is empty or held by another program. Copy an image "
                "or an image file first."
            )
            return
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        paths = [path for path in paths if path]
        if not paths:
            self.log.warning(
                "The clipboard holds no image. Copy an image itself or an image file "
                "first."
            )
            return
        added = 0
        for path in paths:
            if self.workspace.reference.add_from_file(path):
                added += 1
            else:
                self.log.error(f"Cannot read the image: {Path(path).name}")
        if added:
            self.log.info(f"Reference pasted from the clipboard: {added} file(s).")
        self._warn_if_too_many_references()

    def _warn_if_too_many_references(self) -> None:
        """Tell the user early when the current model accepts fewer references."""
        model = self._selected_model()
        references = self.workspace.reference
        if model is None or not references.has_reference():
            return
        limit = model.max_input_references
        if limit and references.count() > limit:
            self.log.warning(
                f"{model.id} accepts at most {limit} reference image(s), but "
                f"{references.count()} are loaded. The request will be rejected "
                "before anything is charged."
            )

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
            self._rebuild_model_list()
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
            self._history_window = HistoryWindow(
                self._history,
                on_use=self._history_use_prompt,
                on_repeat=self._history_repeat,
                parent=self,
            )
            self.history_changed.connect(self._history_window.reload)
        else:
            self._history_window.reload()
        self._history_window.show()
        self._history_window.raise_()

    def _history_use_prompt(self, record: HistoryRecord) -> None:
        """Put the prompt of a history entry into the editor."""
        self.prompt.set_prompt(record.prompt)
        self.log.info(f"Prompt taken from the history: {record.timestamp}")

    def _history_repeat(self, record: HistoryRecord) -> None:
        """Fill the form with a past request without generating anything."""
        request = repeat_request(record)
        if not record.has_request_snapshot:
            self.log.warning(
                "This entry predates parameter recording: only the prompt and the "
                "model were restored."
            )
        self.prompt.set_prompt(request.prompt)
        self._pending_restore = request

        if request.provider_id != self._settings.default_provider:
            index = self._provider_combo.findData(request.provider_id)
            if index < 0:
                self.log.warning(f"Unknown aggregator in the entry: {request.provider_id}")
                self._pending_restore = None
                return
            # Switching the provider reloads its catalog; the model can only be
            # picked afterwards, so the rest of the restore waits for that.
            self._provider_combo.setCurrentIndex(index)
            return
        self._apply_pending_restore()

    def _apply_pending_restore(self) -> None:
        """Select the recorded model and restore its parameters."""
        request = self._pending_restore
        if request is None:
            return
        self._pending_restore = None

        if not self._select_model(request.model):
            self.log.warning(
                f'Model "{request.model}" is not in the current catalog, so it was not '
                "selected; the remaining parameters are filled in."
            )
            return
        unknown = self.params.apply_values(request_snapshot(request))
        if unknown:
            self.log.warning("No longer supported by the model: " + ", ".join(unknown))
        self.workspace.reference.clear()
        restored = 0
        for path in request.reference_paths:
            if self.workspace.reference.add_from_file(path):
                restored += 1
        if restored:
            self.log.info(f"Reference images restored: {restored}.")
        elif request.reference_paths:
            self.log.warning("The referenced images are no longer readable.")
        self.log.info(
            "Parameters restored from the history. Nothing was generated — press "
            "Generate when the request looks right."
        )

    # ---------- worker plumbing ----------
    def _can_save_to(self, folder: str) -> bool:
        """Check that the save folder works, before the request is paid for.

        The folder used to be touched only after the aggregator answered, so a
        wrong path or a full disk was discovered when the money was already
        gone. A write probe is cheap and the only honest check for a full disk.
        """
        problem = save_folder_problem(folder)
        if problem is None:
            return True
        self.log.error(f"Cannot save the results: {problem}")
        QMessageBox.warning(
            self,
            "Save folder unavailable",
            f"{problem}\n\nChange the save folder in Settings before generating.",
        )
        return False

    def _background_free(self, what: str) -> bool:
        """Whether a short background task may start right now.

        All three kinds of work share one worker slot, so starting a balance
        check during a generation replaced the reference to it. When the short
        task finished first, it cleared the slot and the Generate button came
        back while the generation was still running: a second press started a
        second paid request. Refusing to start is the honest answer, because
        nothing in the interface suggests the two compete for one slot.
        """
        if not self._slot.may_start():
            self.log.warning(
                f"Cannot {what.lower()}: a background task is still running. "
                "Wait for it to finish."
            )
            return False
        return True

    def _run(
        self,
        function: Callable[..., object],
        *args: object,
        on_done: Callable[[Any], None],
        on_fail: Callable[[str], None],
        is_generation: bool = False,
        **kwargs: object,
    ) -> None:
        """Start one background task, taking the shared worker slot."""
        worker = FunctionWorker(function, *args, **kwargs)
        worker.setAutoDelete(False)
        worker.signals.finished.connect(on_done)
        worker.signals.failed.connect(on_fail)
        worker.signals.finished.connect(self._clear_worker)
        worker.signals.failed.connect(self._clear_worker)
        self._slot.start(is_generation)
        self._worker = worker
        self._pool.start(worker)

    def _clear_worker(self, *_args: object) -> None:
        """Release the worker slot after a task.

        Only a finished or failed generation re-enables Generate. A helper
        finishing must never do it: the user could press Generate again and
        start a second paid request.
        """
        self._worker = None
        if self._slot.finish():
            self.prompt.set_busy(False)

    # ---------- worker callbacks ----------
    def _on_catalog_loaded(self, result: CatalogResult) -> None:
        self._models = result.models
        source = "cache" if result.from_cache else "network"
        self.log.info(f"Catalog loaded: {len(self._models)} models ({source}).")
        if self._models:
            wanted = self._pending_restore.model if self._pending_restore else None
            wanted = wanted or self._pending_recent or self._settings.default_model
            self._pending_recent = None
            if not self._select_model(wanted, quiet=True):
                self._select_model(self._models[0].id, quiet=True)
            # The list is real again, so the placeholder and the failure hint from
            # an earlier attempt go away.
            self._model_combo.setToolTip(MODEL_COMBO_TOOLTIP)
        else:
            self._show_model_combo_message(
                "No models in the catalog of this aggregator yet. Press "
                "Refresh catalog."
            )
            self._status_model.setText("Model: — (empty catalog)")
            self._sync_generate_state()
        # A Repeat across providers waits here: the model only exists now.
        self._apply_pending_restore()

    # ---------- model list, search and favourites ----------
    def _rebuild_model_list(self, keep: str = "") -> None:
        """Refill the combo from the filtered list, keeping ``keep`` selected."""
        favourites = self._settings.favorite_models
        theme = self._settings.theme
        self._visible = visible_models(self._models, self._model_search.text(), favourites)
        star = favourite_icon(True, theme)
        self._model_combo.blockSignals(True)
        # A failed load leaves a disabled placeholder behind; a real catalog puts
        # the list back in working order.
        self._model_combo.setEnabled(True)
        self._model_combo.clear()
        for model in self._visible:
            # Every row gets an icon slot, so the names stay in one column and
            # a favourite is visible without reading the order.
            self._model_combo.addItem(
                star if is_favourite(model, favourites) else QIcon(),
                combo_label(model),
            )
        self._model_combo.setIconSize(QSize(LIST_ICON_SIZE, LIST_ICON_SIZE))
        self._model_combo.blockSignals(False)
        if keep:
            for index, model in enumerate(self._visible):
                if model.id == keep:
                    self._model_combo.setCurrentIndex(index)
                    break
        self._sync_selected_model()

    def _sync_selected_model(self) -> None:
        """Bring the parameters and the status bar in line with the selection.

        The combo is refilled with its signals blocked, and setting the index
        it already has says nothing, so ``_on_model_changed`` does not fire on
        its own. Without this call the first model of a freshly loaded catalog
        stays unselected everywhere else: no parameters, no price, "Model: —"
        in the status bar.
        """
        self._on_model_changed(self._model_combo.currentIndex())

    def _refresh_model_icons(self) -> None:
        """Repaint the favourite marks without refilling the list."""
        favourites = self._settings.favorite_models
        star = favourite_icon(True, self._settings.theme)
        for index, model in enumerate(self._visible):
            self._model_combo.setItemIcon(
                index, star if is_favourite(model, favourites) else QIcon()
            )

    def _apply_model_filter(self, _text: str = "") -> None:
        """Apply the search text to the model list."""
        previous = self._selected_model()
        self._rebuild_model_list(previous.id if previous is not None else "")
        if not self._visible and self._models:
            self._status_model.setText("Model: —")
            self.prompt.set_cost_hint("")
            self.log.warning(
                f"No model matches «{self._model_search.text().strip()}»."
            )
        elif previous is None and self._visible:
            self._on_model_changed(self._model_combo.currentIndex())

    def _update_fav_button(self) -> None:
        """Show whether the selected model is a favourite."""
        model = self._selected_model()
        favourite = is_favourite(model, self._settings.favorite_models)
        self._fav_button.blockSignals(True)
        self._fav_button.setChecked(favourite)
        self._fav_button.setIcon(favourite_icon(favourite, self._settings.theme))
        self._fav_button.setIconSize(QSize(BUTTON_ICON_SIZE, BUTTON_ICON_SIZE))
        self._fav_button.setEnabled(model is not None)
        self._fav_button.blockSignals(False)

    def _on_favourite_toggled(self, checked: bool) -> None:
        """Add or remove the selected model from the favourites list."""
        model = self._selected_model()
        if model is None:
            return
        key = favourite_key(model)
        favorites = [
            item for item in self._settings.favorite_models if item != key
        ]
        if checked:
            favorites.append(key)
            self.log.info(f"Favourite: {model.id}.")
        elif key in self._settings.favorite_models:
            self.log.info(f"Favourite removed: {model.id}.")
        self._settings.favorite_models = favorites
        self._settings_store.save(self._settings)
        # Favourites move to the top, so the list has to be rebuilt.
        self._rebuild_model_list(model.id)

    def _remember_recent_model(self, model: ModelInfo) -> None:
        """Put a used model at the head of the lately used list."""
        recents = remember_model(self._settings.recent_models, model)
        if recents == self._settings.recent_models:
            return
        self._settings.recent_models = recents
        self._settings_store.save(self._settings)

    def _rebuild_recent_menu(self) -> None:
        """Fill the lately used menu right before it opens."""
        self._recent_menu.clear()
        recents = recent_models(self._models, self._settings.recent_models)
        self._recent_button.setEnabled(bool(recents))
        self._recent_button.setToolTip(
            "Models used lately, newest first. Picking one switches the aggregator "
            "and selects it."
            if recents
            else "No model has been used yet."
        )
        if not recents:
            action = self._recent_menu.addAction("Nothing here yet")
            action.setEnabled(False)
            return
        star = favourite_icon(True, self._settings.theme)
        for model, in_catalog in recents:
            if not in_catalog:
                # The aggregator dropped the model: show it, but do not offer it.
                # Its price and limits are unknown now, so no full label.
                action = self._recent_menu.addAction(
                    f"{model.id} ({model.provider_id}) — not in the catalog"
                )
                action.setEnabled(False)
                continue
            marked = is_favourite(model, self._settings.favorite_models)
            action = self._recent_menu.addAction(
                star if marked else QIcon(), model.display_name()
            )
            action.triggered.connect(
                lambda _checked=False, target=model: self._use_recent(target)
            )
        self._recent_menu.addSeparator()
        self._recent_menu.addAction("Clear the list").triggered.connect(
            self._clear_recent_models
        )

    def _use_recent(self, model: ModelInfo) -> None:
        """Select a lately used model, switching the aggregator if needed."""
        if model.provider_id != self._settings.default_provider:
            index = self._provider_combo.findData(model.provider_id)
            if index < 0:
                self.log.warning(
                    f"Unknown aggregator in the lately used list: {model.provider_id}"
                )
                return
            # Switching reloads the catalog, so the model is picked afterwards.
            self._pending_recent = model.id
            self._provider_combo.setCurrentIndex(index)
            return
        self._select_model(model.id)

    def _clear_recent_models(self) -> None:
        """Forget every lately used model."""
        self._settings.recent_models = []
        self._settings_store.save(self._settings)
        self.log.info("The list of lately used models is cleared.")

    @staticmethod
    def _text_width() -> int:
        """Width of the widest aggregator name in the interface font."""
        metrics = QFontMetrics(QApplication.font())
        return max(metrics.horizontalAdvance(name) for _, name in provider_choices())

    def _show_model_combo_message(self, message: str) -> None:
        """Put a sentence into the model list itself.

        An empty drop-down in the middle of the window looks broken, and the user
        has no way to tell "no models yet" from "the catalog failed to load". One
        disabled row is read without being clicked.

        The visible list is cleared as well: it is what the selection is resolved
        against, and a stale entry there would let the app believe a model is
        still chosen and enable Generate.
        """
        self._visible = []
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        if message:
            self._model_combo.addItem(message)
            self._model_combo.setEnabled(False)
        else:
            self._model_combo.setEnabled(True)
        self._model_combo.blockSignals(False)

    def _sync_generate_state(self) -> None:
        """Enable the Generate button only when a model is selected.

        Without a model there is nothing to send, so the button must say so
        instead of accepting the press and reporting the refusal afterwards.
        """
        self.prompt.generate.setEnabled(self._selected_model() is not None)

    def _on_catalog_failed(self, message: str) -> None:
        self.log.error(f"Catalog load failed: {message}")
        # An empty combo in the middle of the top bar explains nothing on its
        # own, and the log panel is easy to miss. The list itself has to say what
        # happened and what to do, because that is where the user is looking.
        self._status_model.setText("Model: — (catalog failed)")
        self._model_combo.setToolTip(
            f"The catalog could not be loaded: {message}\n"
            "Check the API key in Settings and press Refresh catalog."
        )
        self._show_model_combo_message(PLACEHOLDER_NO_MODELS)
        self._sync_generate_state()

    def _on_account(self, account: AccountInfo) -> None:
        self._show_account(account)

    def _show_account(self, account: AccountInfo) -> None:
        """Put the balance and budget into the top bar and the log."""
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
        self.workspace.show_images(pixmaps, list(outcome.file_paths))
        cost = format_money(outcome.result.cost_rub)
        self._update_session_spend(outcome.result.cost_rub)
        # The pre-flight check has just asked the aggregator, so the label can be
        # corrected instead of staying as it was before a paid request.
        if outcome.account is not None:
            self._show_account(outcome.account)
        self.log.info(f"Done. Cost: {cost} ₽. Files saved: {len(outcome.file_paths)}.")
        self.history_changed.emit()

    def _on_generation_failed(self, message: str) -> None:
        # A failed or cancelled request still leaves a history entry, so the
        # open window has to hear about it too.
        self.history_changed.emit()
        if "cancelled" in message.lower():
            self.log.info("Generation cancelled.")
            return
        self.workspace.show_error(message)
        self.log.error(f"Generation failed: {message}")

    # ---------- helpers ----------
    def _selected_model(self) -> ModelInfo | None:
        index = self._model_combo.currentIndex()
        if 0 <= index < len(self._visible):
            return self._visible[index]
        return None

    def _select_model(self, model_id: str, quiet: bool = False) -> bool:
        """Select a model by id, dropping the search when it hides the model."""
        if model_id and not any(model.id == model_id for model in self._visible):
            # A model recorded earlier can be filtered out by the current search.
            self._model_search.blockSignals(True)
            self._model_search.clear()
            self._model_search.blockSignals(False)
            self._rebuild_model_list()
        for index, model in enumerate(self._visible):
            if model.id == model_id:
                self._model_combo.setCurrentIndex(index)
                if not quiet:
                    self.log.info(f"Model selected: {model_id}.")
                return True
        return False

    def _on_model_changed(self, _index: int) -> None:
        model = self._selected_model()
        self.params.set_model(model)
        self._update_fav_button()
        self._sync_generate_state()
        if model is None:
            self._status_model.setText("Model: —")
            self.prompt.set_cost_hint("")
            return
        self._status_model.setText(f"Model: {model.id}")
        self._update_cost_hint()

    def _update_cost_hint(self) -> None:
        """Show what the current settings would cost.

        Called on a model change and on every parameter change, because the
        estimate is ``max price × n``: leaving it showing the figure for n = 1
        after the user asked for six is a wrong number on the screen at the
        moment the decision to pay is made.
        """
        model = self._selected_model()
        if model is None:
            self.prompt.set_cost_hint("")
            return
        reserved = reserved_amount(model.max_price, self.params.selected_n())
        self.prompt.set_cost_hint(
            f"Catalog: {format_price(model.min_price, model.max_price)} ₽ · "
            f"estimate ~{format_money(reserved)} ₽"
        )

    def _collect_references(self) -> list[bytes]:
        return self.workspace.reference.data_list()

    def _reference_paths(self) -> list[str]:
        """Where the current references came from; pasted images contribute nothing."""
        return self.workspace.reference.source_paths()

    def _can_spend(self, reserved: float | None = None) -> bool:
        """Whether the session spend limit allows this request.

        The limit has to cover the request itself, not only what has already
        been spent: with 50 ₽ left of the limit a 425 ₽ request must not go
        through unchecked. ``reserved`` is the catalog estimate for the request
        being started; without it only the exhausted case can be judged.
        """
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
        if reserved is None:
            return True
        if reserved > remaining:
            self.log.error(
                f"The request needs about {format_money(reserved)} ₽, but only "
                f"{format_money(remaining)} ₽ is left of the session limit of "
                f"{format_money(limit)} ₽. Nothing was sent."
            )
            QMessageBox.warning(
                self,
                "Session limit",
                f"This request needs about {format_money(reserved)} ₽.\n\n"
                f"Only {format_money(remaining)} ₽ is left of the session limit, "
                "so it was not started.\n\n"
                "Raise the limit in Settings → Spending, or generate fewer images.",
            )
            return False
        if remaining < reserved + 1:
            self.log.warning(
                f"Session spend remaining: {format_money(remaining)} ₽, "
                f"the request needs about {format_money(reserved)} ₽."
            )
        return True

    def _confirm_if_expensive(self, reserved: float) -> bool:
        """Ask for confirmation when the catalog estimate exceeds the threshold."""
        threshold = self._settings.confirm_threshold_rub
        if threshold <= 0 or reserved <= threshold:
            return True
        answer = QMessageBox.question(
            self,
            "Confirm generation",
            f"The catalog estimate is {format_money(reserved)} ₽, which exceeds "
            f"the confirmation threshold of {format_money(threshold)} ₽.\n"
            "The real cost is only known after the response and can be higher.\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log.warning("Generation cancelled by the user.")
            return False
        return True

    def _open_reference_viewer(self, index: int = 0) -> None:
        pixmaps = self.workspace.reference.pixmaps()
        if not pixmaps:
            return
        window = ImageViewerWindow(
            pixmaps,
            min(index, len(pixmaps) - 1),
            self.workspace.reference.source_paths(),
            parent=self,
        )
        window.show()
        window.raise_()

    def _open_result_viewer(self, index: int) -> None:
        # The full-size images are read from disk here, on purpose: the grid keeps
        # only reduced copies, so six 4K results do not sit in memory all day.
        images = self.workspace.result_viewer.full_images()
        if not images:
            return
        window = ImageViewerWindow(
            images, index, self.workspace.result_viewer.paths(), parent=self
        )
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
        # QGuiApplication.instance() is typed as QCoreApplication, but the
        # application object is the QApplication created in main().
        instance = QGuiApplication.instance()
        applied = apply_theme(instance, theme) if isinstance(instance, QApplication) else theme
        self._settings.theme = applied
        # The star icons are coloured per theme, so they have to be reloaded.
        # Only the marks are repainted: refilling the list would rebuild the
        # parameter panel and lose the fields the user has already set.
        self._update_fav_button()
        self._refresh_model_icons()
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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        # Cancel the running task and wait for the pool, so no signal is delivered
        # to this window after it is destroyed.
        if self._worker is not None:
            self._worker.cancel()
        self._pool.waitForDone(5000)
        super().closeEvent(event)
