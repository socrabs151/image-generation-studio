"""Types for the extra parameters a Polza.ai model advertises.

The catalog only lists parameter *names*, so the declared types have to come
from the vendor schema (``docs/polzaai/79_POST-Media.md``, ``ImageInputDto``).
They are not interchangeable: ``guidance_scale`` and ``strength`` are numbers,
``isEnhance`` and ``enable_safety_checker`` are booleans, and ``upscale_factor``
is a **string** enumeration of ``'1' '2' '4' '8'``. Guessing by the shape of the
value would turn a valid ``'2'`` into a number and get the request rejected.
"""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

_TRUE = frozenset({"true", "1", "yes", "on", "да", "истина"})
_FALSE = frozenset({"false", "0", "no", "off", "нет", "ложь"})


def _as_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return None


def _as_number(value: str) -> float | int | None:
    text = value.strip().replace(",", ".")
    try:
        return int(text) if text.lstrip("-").isdigit() else float(text)
    except ValueError:
        return None


# Types as declared in ImageInputDto. A parameter that is not listed here is
# sent as the string the user typed: better a clear rejection from the
# aggregator than a guessed type.
PASSTHROUGH_TYPES: dict[str, Any] = {
    "guidance_scale": _as_number,
    "strength": _as_number,
    "max_images": _as_number,
    "isEnhance": _as_bool,
    "enable_safety_checker": _as_bool,
}


def typed_passthrough(passthrough: dict[str, Any]) -> dict[str, Any]:
    """Cast the known parameters to the types the aggregator documents.

    A value that cannot be read as the declared type is left as typed and
    logged: nothing has been sent yet, so the aggregator can reject it with its
    own message, which is clearer than an error about a text field.
    """
    typed: dict[str, Any] = {}
    for name, value in passthrough.items():
        caster = PASSTHROUGH_TYPES.get(name)
        if caster is None or not isinstance(value, str):
            typed[name] = value
            continue
        cast = caster(value)
        if cast is None:
            LOGGER.warning(
                "Cannot read %s=%r as the type Polza.ai documents; sending it as text.",
                name,
                value,
            )
            typed[name] = value
        else:
            typed[name] = cast
    return typed
