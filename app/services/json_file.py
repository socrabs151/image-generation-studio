"""Reading and writing the small JSON files the app keeps in ``data/``.

Three stores need the same two things: never lose a file that cannot be parsed,
and never leave half a file behind. Both live here so the three stores behave
the same way.

The important rule is about a file that cannot be read. For the settings file
that file is the only copy of the API keys, so replacing it with defaults would
destroy them silently. A file that does not parse is therefore moved aside
under a new name and the app continues on a fresh one; a file that cannot even
be opened (locked by another program, read-only directory) is left alone and
marked damaged, and writing is refused until it can be read again.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.errors import ConfigError
from app.logging_setup import get_logger

LOGGER = get_logger()

CORRUPT_SUFFIX = ".unreadable"


class UnreadableFile(ConfigError):
    """The file exists but could not be opened, so it was left untouched."""


def read_json(path: Path, what: str) -> Any:
    """Read JSON, keeping a copy of anything that cannot be parsed.

    Raises :class:`ConfigError` for a file that does not parse (after moving it
    aside) and :class:`UnreadableFile` for one that cannot be opened.
    """
    try:
        # utf-8-sig: a file written by another tool may start with a BOM, which
        # plain utf-8 rejects and which would look like a corrupt file.
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise UnreadableFile(f"Cannot open the {what} file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        kept = quarantine(path)
        if kept is not None:
            raise ConfigError(
                f"Cannot read the {what} file: {exc}. It was kept as {kept.name}, "
                "so nothing is lost; a new one will be written."
            ) from exc
        raise ConfigError(f"Cannot read the {what} file: {exc}") from exc


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON through a temporary file, so a crash never truncates the file.

    Three things beyond the rename:
    - ``fsync`` on the temporary file, so the bytes are on the disk before the name
      points at them;
    - ``fsync`` on the directory, so the rename itself survives a reset;
    - one previous copy kept as ``<name>.bak``, which is the only way back when the
      new file parses but says the wrong thing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _keep_previous(path)
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _keep_previous(path: Path) -> None:
    """Copy the file that is about to be replaced next to it, once."""
    if not path.is_file():
        return
    backup = path.with_name(path.name + ".bak")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        # The write itself is what matters; a missing backup must not stop it.
        LOGGER.warning("Could not keep a backup of %s: %s", path.name, exc)


def _sync_directory(folder: Path) -> None:
    """Tell the disk that the rename happened.

    Windows cannot open a directory as a file handle, so there is nothing to
    sync there: NTFS journals the metadata itself. Everywhere else the rename is
    synced after the fact, because without it the name can be lost even though
    the data reached the disk.
    """
    if os.name == "nt":
        return
    try:
        handle = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        # Windows refuses to fsync a directory handle; the data is already safe.
        pass
    finally:
        os.close(handle)


def quarantine(path: Path) -> Path | None:
    """Move a file that cannot be parsed aside, keeping its bytes.

    Returns the new path, or ``None`` when even that failed.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}{CORRUPT_SUFFIX}-{stamp}")
    try:
        os.replace(path, target)
    except OSError as exc:
        LOGGER.error("Could not set the broken %s aside: %s", path.name, exc)
        return None
    LOGGER.error("The unreadable file %s was kept as %s", path.name, target.name)
    return target
