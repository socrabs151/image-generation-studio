"""Shared HTTP and payload helpers for providers.

Providers speak different dialects but need the same primitives: magic-byte media
type detection, lenient number parsing and error extraction. Polza.ai nests its
error object (``{"error": {"code": ..., "message": ...}}``) while AITUNNEL returns
a plain string, so the helpers here accept both shapes.
"""

from __future__ import annotations

import base64
import binascii
import json

import requests

from app.core.errors import ConfigError, InsufficientFundsError, ProviderError
from app.providers.base import raise_for_status

USER_AGENT = "image-generation-studio/0.1"

_MEDIA_TYPES = (
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
    (b"GIF8", "image/gif"),
)

INSUFFICIENT_FUNDS_CODE = "INSUFFICIENT_BALANCE"


def guess_media_type(data: bytes) -> str:
    """Guess an image MIME type from its magic bytes (default: png)."""
    for prefix, media_type in _MEDIA_TYPES:
        if data.startswith(prefix):
            return media_type
    return "image/png"


def encode_base64(data: bytes) -> str:
    """Return raw image bytes as an ASCII base64 string."""
    return base64.b64encode(data).decode("ascii")


def to_data_url(data: bytes) -> str:
    """Encode raw image bytes as a ``data:`` URI with the detected MIME type."""
    return f"data:{guess_media_type(data)};base64,{encode_base64(data)}"


def decode_base64(encoded: str) -> bytes:
    """Decode a base64 image payload, reporting a clear error when it is broken."""
    try:
        return base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ProviderError(f"The provider returned an undecodable image: {exc}") from exc


def as_float(value) -> float | None:
    """Convert a value to float, returning ``None`` for empty or invalid input."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value, default: int = 0) -> int:
    """Convert a value to int, falling back to ``default`` for invalid input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_json(response: requests.Response) -> dict:
    """Decode a JSON object body, raising :class:`ConfigError` when malformed."""
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON response: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("Unexpected response format: a JSON object was expected.")
    return payload


def error_detail(response: requests.Response) -> str:
    """Extract a short human-readable error message from a response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            for key in ("message", "code", "reason"):
                if error.get(key):
                    return str(error[key])[:300]
        if error:
            return str(error)[:300]
        for key in ("message", "detail"):
            if payload.get(key):
                return str(payload[key])[:300]
    return str(payload)[:300]


def error_code(response: requests.Response) -> str | None:
    """Extract the machine-readable error code, when the API provides one."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("reason")
        return str(code) if code else None
    return None


def ensure_ok(response: requests.Response) -> None:
    """Raise a mapped application exception for an unsuccessful response.

    An insufficient balance is reported by Polza.ai through a dedicated error code
    that can arrive with any 4xx status, so the code is checked before the status.
    """
    if response.status_code < 400:
        return
    detail = error_detail(response)
    if error_code(response) == INSUFFICIENT_FUNDS_CODE:
        raise InsufficientFundsError(detail, status_code=response.status_code)
    raise_for_status(response.status_code, detail)


def auth_headers(api_key: str, json_body: bool = False) -> dict:
    """Build the request headers for an authenticated JSON request."""
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers
