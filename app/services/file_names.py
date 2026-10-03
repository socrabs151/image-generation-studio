"""File name templates for saved images.

Kept free of Qt so the rules can be tested on a machine without a display
server: the CI runner has no ``libEGL`` and the test suite must never import
PySide6.

A template is plain text with ``{placeholders}``. Anything the user does not
recognise is left alone rather than silently dropped, so a typo is visible in
the file name instead of quietly changing what gets saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

DEFAULT_FILENAME_TEMPLATE = "{date}-{time}_{model}"

# Placeholders the user may use, with what they are replaced by. Shown in the
# settings dialog next to the field.
PLACEHOLDERS = (
    "{date}",
    "{time}",
    "{datetime}",
    "{model}",
    "{provider}",
    "{prompt}",
    "{index}",
    "{total}",
)

# Reserved on Windows whatever the extension is.
RESERVED_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)

# Characters Windows does not allow in a name, plus control characters.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOKEN = re.compile(r"\{(\w+)\}")
_SPACES = re.compile(r"\s+")

MAX_STEM_LENGTH = 120
MAX_PROMPT_LENGTH = 40
MAX_MODEL_LENGTH = 60


@dataclass(frozen=True, slots=True)
class NameParts:
    """Everything a template may refer to."""

    model: str
    provider: str = ""
    prompt: str = ""
    index: int = 1
    total: int = 1
    when: datetime | None = None


def sanitize(value: str, *, limit: int = MAX_STEM_LENGTH, fallback: str = "") -> str:
    """Make an arbitrary string usable as part of a file name on Windows.

    Trailing dots and spaces are dropped because Windows strips them silently,
    which would make two different names collide on disk.
    """
    # Control characters are replaced first: some of them (\\x1c to \\x1f) count as
    # whitespace, so cleaning spaces beforehand would turn them into a space
    # instead of a dash.
    cleaned = _UNSAFE.sub("-", value).strip()
    cleaned = _SPACES.sub(" ", cleaned)
    cleaned = cleaned.strip("-. ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)[:limit].strip("-. ")
    if not cleaned or cleaned.upper() in RESERVED_STEMS:
        return fallback
    return cleaned


def render_filename(template: str, parts: NameParts) -> str:
    """Build the stem of a file name from ``template``.

    The extension is added by the caller, because it depends on the image that
    came back rather than on the request.
    """
    when = parts.when or datetime.now()
    values = {
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H-%M-%S"),
        "datetime": when.strftime("%Y-%m-%d_%H-%M-%S"),
        "model": sanitize(parts.model, limit=MAX_MODEL_LENGTH, fallback="model"),
        "provider": sanitize(parts.provider, limit=MAX_MODEL_LENGTH),
        "prompt": sanitize(parts.prompt, limit=MAX_PROMPT_LENGTH),
        "index": str(parts.index),
        "total": str(parts.total),
    }

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return values.get(name, match.group(0))

    stem = _TOKEN.sub(replace, template or "")
    cleaned = sanitize(stem, limit=MAX_STEM_LENGTH, fallback="")
    if not cleaned:
        # A template made only of empty values still has to name something.
        cleaned = f"{values['date']}-{values['time']}_{values['model']}"
    return cleaned


def unknown_placeholders(template: str) -> list[str]:
    """Placeholders the template uses that are not in :data:`PLACEHOLDERS`."""
    known = {token.strip("{}") for token in PLACEHOLDERS}
    return [match.group(0) for match in _TOKEN.finditer(template) if match.group(1) not in known]
