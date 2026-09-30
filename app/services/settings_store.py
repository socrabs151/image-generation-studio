"""Persistent storage for application settings (``data/settings.json``).

The file is created automatically on first run (bootstrap) with defaults and empty
API keys. It is also the only place the API keys exist, so reading and writing it
is handled by :mod:`app.services.json_file`: a file that cannot be parsed is kept
aside instead of being overwritten, and writes are atomic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import (
    SETTINGS_FILE,
    SETTINGS_SCHEMA_VERSION,
)
from app.core.errors import ConfigError
from app.logging_setup import get_logger
from app.services.json_file import UnreadableFile, read_json, write_json_atomic

LOGGER = get_logger()

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
    # Models marked as favourites, as "provider_id:model_id" so that the same model
    # name at two aggregators stays two separate entries.
    favorite_models: list[str] = field(default_factory=list)
    # Models used lately, same key format, newest first.
    recent_models: list[str] = field(default_factory=list)
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

    def __init__(self, path: Path | None = None) -> None:
        # Resolved at call time, not as a default argument: a default is bound when
        # the module is imported, which makes the store impossible to retarget.
        self._path = path or SETTINGS_FILE
        # Set when the file on disk could not be read. While it is, saving is
        # refused: the keys the user typed are in that file, and overwriting it
        # with defaults would destroy them for good.
        self._damaged = False

    @property
    def path(self) -> Path:
        """Path of the settings file."""
        return self._path

    @property
    def damaged(self) -> bool:
        """Whether the file on disk was unreadable and must not be overwritten."""
        return self._damaged

    def load(self) -> Settings:
        """Load settings, bootstrapping the file when it does not exist.

        A file that does not parse is moved aside by :func:`read_json` and the
        app continues on a fresh one; a file that cannot be opened is left
        untouched and :meth:`save` refuses to write over it.
        """
        if not self._path.exists():
            settings = Settings()
            self.save(settings)
            return settings
        try:
            raw = read_json(self._path, "settings")
        except UnreadableFile as exc:
            self._damaged = True
            raise ConfigError(str(exc)) from exc
        self._damaged = False
        return self._from_dict(raw)

    def save(self, settings: Settings) -> None:
        """Write settings atomically.

        Refuses to write while the file cannot be opened, and says so out loud.
        The API keys live only in that file: replacing it with empty defaults
        would be silent and irreversible, which is worse than not saving.
        """
        if self._damaged:
            LOGGER.error(
                "Not overwriting the unreadable settings file %s. Move it aside to "
                "start from defaults.",
                self._path,
            )
            return
        write_json_atomic(self._path, settings.to_dict())

    @staticmethod
    def _from_dict(raw: dict) -> Settings:
        # The file is the only copy of the API keys, so nothing in it is taken
        # on trust: a wrong type or a null falls back to the default instead of
        # raising something the caller does not expect.
        if not isinstance(raw, dict):
            raise ConfigError("The settings file must contain a JSON object.")
        providers = _providers_from(raw.get("providers"))
        default = Settings()
        return Settings(
            schema_version=_as_int(raw.get("schema_version"), SETTINGS_SCHEMA_VERSION),
            default_provider=_as_str(raw.get("default_provider"), DEFAULT_PROVIDER),
            default_model=_as_str(raw.get("default_model"), DEFAULT_MODEL),
            theme=_as_str(raw.get("theme"), "light"),
            save_dir=_as_str(raw.get("save_dir"), DEFAULT_SAVE_DIR),
            auto_refresh_catalog=_as_bool(raw.get("auto_refresh_catalog"), True),
            history_limit=_as_int(raw.get("history_limit"), 200),
            confirm_threshold_rub=_as_float(raw.get("confirm_threshold_rub"), 50.0),
            session_limit_rub=_as_float(raw.get("session_limit_rub"), 0.0),
            generation_timeout=_as_int(raw.get("generation_timeout"), 180),
            favorite_models=_string_list(raw.get("favorite_models")),
            recent_models=_string_list(raw.get("recent_models")),
            providers=providers or default.providers,
        )



def _string_list(value: object) -> list[str]:
    """Read a list of strings from the settings file, ignoring a broken value."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _providers_from(value: object) -> dict[str, ProviderSettings]:
    """Read the provider block, keeping every key that is readable."""
    if not isinstance(value, dict):
        return {}
    providers: dict[str, ProviderSettings] = {}
    for provider_id, entry in value.items():
        if not isinstance(provider_id, str):
            continue
        api_key = entry.get("api_key") if isinstance(entry, dict) else None
        providers[provider_id] = ProviderSettings(
            api_key=api_key if isinstance(api_key, str) else ""
        )
    return providers


def _as_str(value: object, fallback: str) -> str:
    return value if isinstance(value, str) else fallback


def _as_bool(value: object, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _as_float(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
