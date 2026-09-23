# -*- coding: utf-8 -*-
"""Пути и константы приложения (см. specs.md §15).

Единая точка правды для расположения данных, ресурсов и версий схемы JSON.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "Image Generation Studio"
APP_ID = "image-generation-studio"

# Корень проекта — папка, содержащая app/ и resources/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources"
THEMES_DIR = RESOURCES_DIR / "themes"
ICONS_DIR = RESOURCES_DIR / "icons"
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = PROJECT_ROOT / "data"

# Файлы данных (в рабочей директории, см. .gitignore).
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
CATALOG_CACHE_FILE = DATA_DIR / "catalog_cache.json"

# Версия схемы файлов настроек/истории — для миграций.
SETTINGS_SCHEMA_VERSION = 1
HISTORY_SCHEMA_VERSION = 1

# Ограничения запроса (specs.md §8).
MAX_REFERENCE_BYTES = 25 * 1024 * 1024  # 25 МБ
REFERENCE_FORMATS = ("png", "jpeg", "webp", "gif")