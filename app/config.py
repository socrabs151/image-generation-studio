"""Application paths and constants.

Single source of truth for data locations, resources and JSON schema versions.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "Image Generation Studio"
APP_ID = "image-generation-studio"

# Project root: the folder that contains app/ and resources/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources"
THEMES_DIR = RESOURCES_DIR / "themes"
ICONS_DIR = RESOURCES_DIR / "icons"
STAR_ICON_DIR = ICONS_DIR / "star"
APP_ICON_PATH = ICONS_DIR / "chernichka.png"
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = PROJECT_ROOT / "data"

# Application data files.
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
CATALOG_CACHE_FILE = DATA_DIR / "catalog_cache.json"

# Schema versions of the settings and history files (used for migrations).
SETTINGS_SCHEMA_VERSION = 1
# Version 2 added the per-request snapshot, the reference paths and the duration.
HISTORY_SCHEMA_VERSION = 2

# Input limits.
MAX_REFERENCE_BYTES = 25 * 1024 * 1024
REFERENCE_FORMATS = ("png", "jpeg", "webp", "gif")
