"""AITUNNEL provider.

Endpoints used:

* catalog — ``GET https://api.aitunnel.ru/public/aitunnel/models/images`` (no key);
* generation — ``POST https://api.aitunnel.ru/v1/images/generations`` (sync, no polling);
* account — ``GET https://api.aitunnel.ru/v1/aitunnel/{balance,key,me}``.

The API freezes ``max_price_per_image * n`` on the balance before a request and
charges the actual cost afterwards; the real amount is returned in ``usage.cost_rub``.
"""

from __future__ import annotations

import base64
import json

import requests

from app.core.errors import ConfigError
from app.core.models import (
    AccountInfo,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)
from app.providers.base import Provider, raise_for_status, wrap_network_error

CATALOG_URL = "https://api.aitunnel.ru/public/aitunnel/models/images"
GENERATION_URL = "https://api.aitunnel.ru/v1/images/generations"
ACCOUNT_URL = "https://api.aitunnel.ru/v1/aitunnel"
USER_AGENT = "image-generation-studio/0.1"

_MEDIA_TYPES = (
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


def _guess_media_type(data: bytes) -> str:
    """Guess an image MIME type from its magic bytes (default: png)."""
    for prefix, media_type in _MEDIA_TYPES:
        if data.startswith(prefix):
            return media_type
    return "image/png"


def _to_data_url(data: bytes) -> str:
    """Encode raw image bytes as a ``data:`` URI accepted by ``input_references``."""
    return f"data:{_guess_media_type(data)};base64,{base64.b64encode(data).decode('ascii')}"


class AitunnelProvider(Provider):
    """AITUNNEL aggregator provider."""

    id = "aitunnel"
    display_name = "AITUNNEL"
    requires_key = True

    # ---------- catalog ----------
    def fetch_catalog(self, timeout: int = 60) -> list[ModelInfo]:
        """Load the public image-model catalog (no API key required)."""
        try:
            response = requests.get(
                CATALOG_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        self._ensure_ok(response)
        payload = self._parse_json(response)
        if not isinstance(payload, dict):
            raise ConfigError("Unexpected catalog response format.")
        return [self._parse_model(name, entry) for name, entry in payload.items()]

    @staticmethod
    def _parse_model(name: str, entry: dict) -> ModelInfo:
        return ModelInfo(
            id=name,
            provider_id=AitunnelProvider.id,
            description=entry.get("description") or "",
            min_price=_as_float(entry.get("min_price_per_image")),
            max_price=_as_float(entry.get("max_price_per_image")),
            resolutions=list(entry.get("supported_resolutions") or []),
            aspect_ratios=list(entry.get("supported_aspect_ratios") or []),
            qualities=list(entry.get("supported_quality") or []),
            formats=list(entry.get("supported_output_formats") or []),
            backgrounds=list(entry.get("supported_background") or []),
            supports_seed=bool(entry.get("supports_seed")),
            supports_generation=bool(entry.get("supports_generation", True)),
            supports_edit=bool(entry.get("supports_edit")),
            max_n=int(entry.get("max_n") or 1),
            max_input_references=int(entry.get("max_input_references") or 0),
            allowed_passthrough=list(entry.get("allowed_passthrough_parameters") or []),
        )

    # ---------- generation ----------
    def generate(self, request: GenerationRequest, timeout: int = 180) -> GenerationResult:
        """Run a synchronous image-generation request."""
        self._require_key()
        body = self._build_payload(request)
        try:
            response = requests.post(
                GENERATION_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        self._ensure_ok(response)
        payload = self._parse_json(response)

        images: list[GeneratedImage] = []
        for item in payload.get("data") or []:
            encoded = item.get("b64_json")
            if not encoded:
                continue
            images.append(
                GeneratedImage(
                    data=base64.b64decode(encoded),
                    media_type=item.get("media_type"),
                )
            )
        if not images:
            raise ConfigError("The provider returned no images.")

        usage = payload.get("usage") or {}
        return GenerationResult(
            images=images,
            cost_rub=_as_float(usage.get("cost_rub")),
            balance=_as_float(usage.get("balance")),
            model=payload.get("model") or request.model,
        )

    @staticmethod
    def _build_payload(request: GenerationRequest) -> dict:
        """Translate a :class:`GenerationRequest` into the API payload."""
        body: dict = {"model": request.model, "prompt": request.prompt, "n": request.n}
        optional = {
            "quality": request.quality,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "size": request.size,
            "output_format": request.output_format,
            "background": request.background,
            "seed": request.seed,
        }
        for key, value in optional.items():
            if value not in (None, ""):
                body[key] = value
        if request.input_references:
            body["input_references"] = [
                {"type": "image_url", "image_url": {"url": _to_data_url(ref)}}
                for ref in request.input_references
            ]
        body.update(request.passthrough)
        return body

    # ---------- account ----------
    def check_account(self, timeout: int = 30) -> AccountInfo:
        """Return balance, budget and account identity for the current key."""
        self._require_key()
        info = AccountInfo()
        payloads: dict[str, dict] = {}
        for name in ("balance", "key", "me"):
            try:
                response = requests.get(
                    f"{ACCOUNT_URL}/{name}",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "User-Agent": USER_AGENT,
                    },
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise wrap_network_error(exc) from exc
            self._ensure_ok(response)
            payloads[name] = self._parse_json(response)

        balance = payloads.get("balance") or {}
        key = payloads.get("key") or {}
        me = payloads.get("me") or {}
        info.balance = _as_float(balance.get("balance"))
        info.email = me.get("email")
        budget = _as_float(balance.get("budget"))
        if budget is not None:
            info.budget_remaining = budget
            if isinstance(key.get("budget"), dict):
                info.budget_initial = _as_float(key["budget"].get("initial"))
        allowed = key.get("allowed_models")
        if allowed:
            info.limits["allowed_models"] = list(allowed)
        return info

    # ---------- internals ----------
    def _require_key(self) -> None:
        if self.requires_key and not self.api_key:
            raise ConfigError("API key is not set for this provider.")

    @staticmethod
    def _ensure_ok(response: requests.Response) -> None:
        if response.status_code >= 400:
            raise_for_status(response.status_code, _error_detail(response))

    @staticmethod
    def _parse_json(response: requests.Response) -> dict:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON response: {exc}") from exc


def _as_float(value) -> float | None:
    """Convert a value to float, returning ``None`` for empty or invalid input."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error_detail(response: requests.Response) -> str:
    """Extract a short human-readable error message from a response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            if payload.get(key):
                return str(payload[key])[:300]
    return str(payload)[:300]
