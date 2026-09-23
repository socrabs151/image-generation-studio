"""Access to provider API keys.

Keys are stored in ``data/settings.json`` through :class:`SettingsStore`. This thin
abstraction isolates the rest of the application from the storage mechanism, so the
backing store can later be replaced (for example with the OS keyring) without
changing the UI.
"""

from __future__ import annotations

from app.services.settings_store import Settings, SettingsStore


class KeyStore:
    """Read and write provider API keys via the settings store."""

    def __init__(self, settings_store: SettingsStore) -> None:
        self._store = settings_store
        self._settings: Settings | None = None

    def load(self) -> None:
        """Load settings from disk."""
        self._settings = self._store.load()

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
            from app.services.settings_store import ProviderSettings

            settings.providers[provider_id] = ProviderSettings(api_key=api_key)
        else:
            existing.api_key = api_key
        self._store.save(settings)

    def _require_settings(self) -> Settings:
        if self._settings is None:
            self.load()
        assert self._settings is not None
        return self._settings
