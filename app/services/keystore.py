"""Access to provider API keys.

Keys are stored in ``data/settings.json`` through :class:`SettingsStore`. This thin
abstraction isolates the rest of the application from the storage mechanism, so the
backing store can later be replaced (for example with the OS keyring) without
changing the UI.
"""

from __future__ import annotations

from app.core.errors import ConfigError
from app.logging_setup import get_logger
from app.services.settings_store import ProviderSettings, Settings, SettingsStore

LOGGER = get_logger()


class KeyStore:
    """Read and write provider API keys via the settings store."""

    def __init__(self, settings_store: SettingsStore) -> None:
        self._store = settings_store
        self._settings: Settings | None = None

    def load(self) -> None:
        """Load settings from disk, keeping the defaults if the file is unreadable.

        The main window already survives a damaged settings file by falling back to
        the defaults; the key store must not turn the same file into a startup
        failure, and an unreadable file simply means no keys are known yet.
        """
        try:
            self._settings = self._store.load()
        except ConfigError as exc:
            LOGGER.warning("API keys are unavailable: %s", exc)
            self._settings = Settings()

    def get(self, provider_id: str) -> str:
        """Return the API key for a provider (empty string when absent)."""
        settings = self._require_settings()
        provider = settings.providers.get(provider_id)
        return provider.api_key if provider else ""

    def set(self, provider_id: str, api_key: str) -> None:
        """Store the API key for a provider and persist settings."""
        settings = self._require_settings()
        existing = settings.providers.get(provider_id)
        if existing is None:
            settings.providers[provider_id] = ProviderSettings(api_key=api_key)
        else:
            existing.api_key = api_key
        self._store.save(settings)

    def _require_settings(self) -> Settings:
        if self._settings is None:
            self.load()
        assert self._settings is not None
        return self._settings
