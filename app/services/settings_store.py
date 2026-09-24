"""Persistent storage for application settings (``data/settings.json``).

The file is created automatically on first run (bootstrap) with defaults and empty
API keys. Writes are atomic: content is written to a temporary file and then moved
over the target with :func:`os.replace`.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import (
    DATA_DIR,
    SETTINGS_FILE,
    SETTINGS_SCHEMA_VERSION,
)
from app.core.errors import ConfigError

DEFAULT_SAVE_DIR = str(Path.home() / "Pictures" / "ImageGenerationStudio")
DEFAULT_PROVIDER = "aitunnel"
DEFAULT_MODEL = "gpt-image-1"


@dataclass(slots=True)
class ProviderSettings:
    """Per-provider settings (currently just the API key)."""

    api_key: str = ""


@dataclass(slots=True)
class Settings:
    """Application settings model."""

    schema_version: int = SETTINGS_SCHEMA_VERSION
    default_provider: str = DEFAULT_PROVIDER
    default_model: str = DEFAULT_MODEL
    theme: str = "light"
    save_dir: str = DEFAULT_SAVE_DIR
    auto_refresh_catalog: bool = True
    history_limit: int = 200
    # Confirmation threshold: when the reserved amount exceeds this, the user is
    # asked to confirm before generation. 0 disables the confirmation.
    confirm_threshold_rub: float = 50.0
    # Maximum spend per session in rubles; 0 disables the limit.
    session_limit_rub: float = 0.0
    # Provider request timeout in seconds.
    generation_timeout: int = 180
    providers: dict[str, ProviderSettings] = field(
        default_factory=lambda: {
            "aitunnel": ProviderSettings(),
            "polza": ProviderSettings(),
        }
    )

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        data = asdict(self)
        return data


class SettingsStore:
    """Load and save :class:`Settings`, creating the file when missing."""

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Path of the settings file."""
        return self._path

    def load(self) -> Settings:
        """Load settings, bootstrapping the file when it does not exist."""
        if not self._path.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read settings file: {exc}") from exc
        return self._from_dict(raw)

    def save(self, settings: Settings) -> None:
        """Write settings atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self._path, json.dumps(settings.to_dict(), ensure_ascii=False, indent=2))

    @staticmethod
    def _from_dict(raw: dict) -> Settings:
        providers_raw = raw.get("providers") or {}
        providers = {
            provider_id: ProviderSettings(api_key=(value or {}).get("api_key", ""))
            for provider_id, value in providers_raw.items()
        }
        if not providers:
            providers = Settings().providers
        return Settings(
            schema_version=int(raw.get("schema_version", SETTINGS_SCHEMA_VERSION)),
            default_provider=raw.get("default_provider", DEFAULT_PROVIDER),
            default_model=raw.get("default_model", DEFAULT_MODEL),
            theme=raw.get("theme", "light"),
            save_dir=raw.get("save_dir", DEFAULT_SAVE_DIR),
            auto_refresh_catalog=bool(raw.get("auto_refresh_catalog", True)),
            history_limit=int(raw.get("history_limit", 200)),
            confirm_threshold_rub=float(raw.get("confirm_threshold_rub", 50.0)),
            session_limit_rub=float(raw.get("session_limit_rub", 0.0)),
            generation_timeout=int(raw.get("generation_timeout", 180)),
            providers=providers,
        )

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """Write text to ``path`` atomically (temp file + replace)."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        )
        try:
            with handle:
                handle.write(text)
            os.replace(handle.name, path)
        except OSError:
            Path(handle.name).unlink(missing_ok=True)
            raise
