"""Application logging setup.

Configures a root logger with a rotating file handler. Secrets (API keys and the
``Authorization`` header) must never be logged.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import DATA_DIR

LOG_FILE = DATA_DIR / "app.log"
_LOGGER_NAME = "image_generation_studio"
_configured = False


def get_logger() -> logging.Logger:
    """Return the application logger, configuring it on first use."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        _configure(logger)
        _configured = True
    return logger


def _configure(logger: logging.Logger) -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
