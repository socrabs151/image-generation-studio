"""AITUNNEL provider.

Endpoints used:

* catalog — ``GET https://api.aitunnel.ru/public/aitunnel/models/images`` (no key);
* generation — ``POST https://api.aitunnel.ru/v1/images/generations`` (sync, no polling);
* account — ``GET https://api.aitunnel.ru/v1/aitunnel/{balance,key,me}``.

The API freezes ``max_price_per_image * n`` on the balance before a request and
charges the actual cost afterwards; the real amount is returned in ``usage.cost_rub``.
"""

from __future__ import annotations

from collections.abc import Callable

import requests

from app.core.errors import CancelledError, ConfigError
from app.core.models import (
    AccountInfo,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)
from app.providers.base import Provider, wrap_network_error
from app.providers.http_utils import (
    USER_AGENT,
    as_float,
    auth_headers,
    decode_base64,
    ensure_ok,
    parse_json,
    to_data_url,
)

CATALOG_URL = "https://api.aitunnel.ru/public/aitunnel/models/images"
GENERATION_URL = "https://api.aitunnel.ru/v1/images/generations"
ACCOUNT_URL = "https://api.aitunnel.ru/v1/aitunnel"


def _required_parameters(
    resolutions: list[str],
    aspect_ratios: list[str],
    qualities: list[str],
    formats: list[str],
    backgrounds: list[str],
) -> list[str]:
    """Infer the mandatory parameters of a model from its advertised values.

    The AITUNNEL catalog lists the values a parameter accepts but does not say which
    of them are mandatory. A list that offers ``auto`` can be left out, so a list
    without it is treated as mandatory: the provider otherwise rejects the request
    and the caller still pays for the attempt. The names are the ones used in
    :class:`~app.core.models.GenerationRequest`, not the catalog field names.
    """
    candidates = {
        "resolution": resolutions,
        "aspect_ratio": aspect_ratios,
        "quality": qualities,
        "output_format": formats,
        "background": backgrounds,
    }
    return sorted(name for name, values in candidates.items() if values and "auto" not in values)


class AitunnelProvider(Provider):

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
        ensure_ok(response)
        payload = parse_json(response)
        return [self._parse_model(name, entry) for name, entry in payload.items()]

    @staticmethod
    def _parse_model(name: str, entry: dict) -> ModelInfo:
        resolutions = list(entry.get("supported_resolutions") or [])
        aspect_ratios = list(entry.get("supported_aspect_ratios") or [])
        qualities = list(entry.get("supported_quality") or [])
        formats = list(entry.get("supported_output_formats") or [])
        backgrounds = list(entry.get("supported_background") or [])
        return ModelInfo(
            id=name,
            provider_id=AitunnelProvider.id,
            description=entry.get("description") or "",
            min_price=as_float(entry.get("min_price_per_image")),
            max_price=as_float(entry.get("max_price_per_image")),
            resolutions=resolutions,
            aspect_ratios=aspect_ratios,
            qualities=qualities,
            formats=formats,
            backgrounds=backgrounds,
            supports_seed=bool(entry.get("supports_seed")),
            supports_generation=bool(entry.get("supports_generation", True)),
            supports_edit=bool(entry.get("supports_edit")),
            max_n=int(entry.get("max_n") or 1),
            max_input_references=int(entry.get("max_input_references") or 0),
            required_parameters=_required_parameters(
                resolutions=resolutions,
                aspect_ratios=aspect_ratios,
                qualities=qualities,
                formats=formats,
                backgrounds=backgrounds,
            ),
            allowed_passthrough=list(entry.get("allowed_passthrough_parameters") or []),
        )

    # ---------- generation ----------
    def generate(
        self,
        request: GenerationRequest,
        timeout: int = 180,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        """Run a synchronous image-generation request.

        The endpoint answers in a single response, so ``cancel_check`` is only
        consulted once, right before the request is sent.
        """
        self._require_key()
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        body = self._build_payload(request)
        try:
            response = requests.post(
                GENERATION_URL,
                headers=auth_headers(self.api_key, json_body=True),
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        ensure_ok(response)
        payload = parse_json(response)

        images: list[GeneratedImage] = []
        for item in payload.get("data") or []:
            encoded = item.get("b64_json")
            if not encoded:
                continue
            images.append(
                GeneratedImage(
                    data=decode_base64(encoded),
                    media_type=item.get("media_type"),
                )
            )
        if not images:
            raise ConfigError("The provider returned no images.")

        usage = payload.get("usage") or {}
        return GenerationResult(
            images=images,
            cost_rub=as_float(usage.get("cost_rub")),
            balance=as_float(usage.get("balance")),
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
                {"type": "image_url", "image_url": {"url": to_data_url(ref)}}
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
                    headers=auth_headers(self.api_key),
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise wrap_network_error(exc) from exc
            ensure_ok(response)
            payloads[name] = parse_json(response)

        balance = payloads.get("balance") or {}
        key = payloads.get("key") or {}
        me = payloads.get("me") or {}
        info.balance = as_float(balance.get("balance"))
        info.email = me.get("email")
        budget = as_float(balance.get("budget"))
        if budget is not None:
            info.budget_remaining = budget
            if isinstance(key.get("budget"), dict):
                info.budget_initial = as_float(key["budget"].get("initial"))
        allowed = key.get("allowed_models")
        if allowed:
            info.limits["allowed_models"] = list(allowed)
        return info

    # ---------- internals ----------
    def _require_key(self) -> None:
        if self.requires_key and not self.api_key:
            raise ConfigError("API key is not set for this provider.")
