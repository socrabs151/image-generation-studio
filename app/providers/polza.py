"""Polza.ai provider.

Endpoints used:

* catalog — ``GET https://polza.ai/api/v1/models/catalog?type=image`` (no key);
* generation — ``POST https://polza.ai/api/v1/media`` plus status polling;
* account — ``GET https://polza.ai/api/v2/balance``.

Generation always goes through the media endpoint. The OpenAI-compatible
``POST /v2/images/generations`` looks simpler, but its request schema has no
``aspect_ratio``, ``image_resolution`` or ``seed``, so the resolution and aspect
ratio chosen in the interface would be silently dropped. The media endpoint speaks
the same parameter names the catalog advertises and also accepts reference images.

The media endpoint answers with a task that has to be polled until it is
``completed``; the real cost is returned in ``usage.cost_rub``. A task yields one
image, so a request for several images runs several tasks.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

import requests

from app.core.errors import CancelledError, ConfigError, ProviderError, ProviderTimeoutError
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
    as_int,
    auth_headers,
    decode_base64,
    encode_base64,
    ensure_ok,
    guess_media_type,
    parse_json,
)

API_ROOT = "https://polza.ai/api"
CATALOG_URL = f"{API_ROOT}/v1/models/catalog"
MEDIA_URL = f"{API_ROOT}/v1/media"
BALANCE_URL = f"{API_ROOT}/v2/balance"

CATALOG_PAGE_SIZE = 100
POLL_INTERVAL = 4.0

# A media task produces a single image, so ``n`` is served by running ``n`` tasks.
# The cap mirrors the ``max_images`` ceiling documented for the endpoint.
MAX_IMAGES_PER_REQUEST = 6

# The API documents the seed range as 1..4294967295.
MAX_SEED = 4294967295

# Catalog parameter names already covered by GenerationRequest fields; everything
# else the model advertises is offered to the user as a passthrough field.
_MAPPED_PARAMETERS = frozenset(
    {
        "prompt",
        "aspect_ratio",
        "image_resolution",
        "quality",
        "output_format",
        "background",
        "seed",
        "images",
    }
)

_TERMINAL_FAILURES = ("failed", "cancelled")


class PolzaProvider(Provider):
    """Polza.ai aggregator provider."""

    id = "polza"
    display_name = "Polza.ai"
    requires_key = True

    # ---------- catalog ----------
    def fetch_catalog(self, timeout: int = 60) -> list[ModelInfo]:
        """Load the image-model catalog (no API key required)."""
        try:
            response = requests.get(
                CATALOG_URL,
                params={
                    "type": "image",
                    "include_providers": "true",
                    "limit": CATALOG_PAGE_SIZE,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        ensure_ok(response)
        payload = parse_json(response)
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise ConfigError("Unexpected catalog response format.")
        return [self._parse_model(entry) for entry in entries if isinstance(entry, dict)]

    @staticmethod
    def _parse_model(entry: dict) -> ModelInfo:
        described, parameters = _parameters_of(entry)

        provider = entry.get("top_provider")
        provider = provider if isinstance(provider, dict) else {}
        min_price, max_price = _price_range(provider.get("pricing"))

        images = parameters.get("images")
        images = images if isinstance(images, dict) else {}
        max_references = as_int(images.get("max"), 0)

        return ModelInfo(
            id=str(entry.get("id") or ""),
            provider_id=PolzaProvider.id,
            description=str(entry.get("short_description") or entry.get("name") or ""),
            min_price=min_price,
            max_price=max_price,
            resolutions=_values(parameters, "image_resolution"),
            aspect_ratios=_values(parameters, "aspect_ratio"),
            qualities=_values(parameters, "quality"),
            formats=_values(parameters, "output_format"),
            backgrounds=_values(parameters, "background"),
            supports_seed="seed" in parameters,
            # A model whose parameters the catalog does not describe is still a
            # generation model; a described set without a prompt means the model
            # transforms an image instead of generating one from a description.
            supports_generation=("prompt" in parameters) if described else True,
            supports_edit=max_references > 0,
            max_n=MAX_IMAGES_PER_REQUEST,
            max_input_references=max_references,
            required_parameters=_required(parameters),
            allowed_passthrough=[
                name for name in parameters if name not in _MAPPED_PARAMETERS
            ],
        )

    # ---------- generation ----------
    def generate(
        self,
        request: GenerationRequest,
        timeout: int = 180,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        """Run a generation request and return the images plus the actual cost.

        A media task yields exactly one image and the catalog advertises no
        multi-image parameter, so ``n`` is served by running ``n`` tasks. The price
        of every task is summed, which matches the amount the interface reserves
        before the request.
        """
        self._require_key()
        if request.n <= 1:
            return self._run_task(request, timeout, cancel_check)
        return self._run_tasks(request, timeout, cancel_check)

    def _run_tasks(
        self,
        request: GenerationRequest,
        timeout: int,
        cancel_check: Callable[[], bool] | None,
    ) -> GenerationResult:
        """Run one media task per requested image and collect all results."""
        images: list[GeneratedImage] = []
        cost = 0.0
        priced = False
        model = request.model
        for index in range(request.n):
            if cancel_check is not None and cancel_check():
                raise CancelledError()
            # A fixed seed would make every task return the same picture, so each
            # image after the first is drawn from the next seed value.
            task = replace(request, n=1, seed=_seed_for(request.seed, index))
            outcome = self._run_task(task, timeout, cancel_check)
            images.extend(outcome.images)
            if outcome.cost_rub is not None:
                cost += outcome.cost_rub
                priced = True
            model = outcome.model or model
        if not images:
            raise ConfigError("The provider returned no images.")
        return GenerationResult(
            images=images,
            cost_rub=cost if priced else None,
            balance=None,
            model=model,
        )

    def _run_task(
        self,
        request: GenerationRequest,
        timeout: int,
        cancel_check: Callable[[], bool] | None,
    ) -> GenerationResult:
        """Run a single media task and wait for its result."""
        payload = self._post(MEDIA_URL, self._build_payload(request), timeout)
        if _is_task(payload):
            payload = self._await_media(str(payload.get("id")), timeout, cancel_check)
        return self._result_from_media(payload, request.model)

    @staticmethod
    def _build_payload(request: GenerationRequest) -> dict:
        """Translate a :class:`GenerationRequest` into a media-endpoint payload."""
        image_input: dict = {"prompt": request.prompt}
        optional = {
            "aspect_ratio": request.aspect_ratio,
            "image_resolution": request.resolution,
            "quality": request.quality,
            "output_format": request.output_format,
            "background": request.background,
            "seed": request.seed,
        }
        for key, value in optional.items():
            if value not in (None, ""):
                image_input[key] = value
        if request.input_references:
            image_input["images"] = [
                {"type": "base64", "data": encode_base64(reference)}
                for reference in request.input_references
            ]
        body: dict = {"model": request.model, "input": image_input, "async": False}
        body.update(request.passthrough)
        return body

    def _post(self, url: str, body: dict, timeout: int) -> dict:
        try:
            response = requests.post(
                url,
                headers=auth_headers(self.api_key, json_body=True),
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        ensure_ok(response)
        return parse_json(response)

    def _get(self, url: str, timeout: int) -> dict:
        try:
            response = requests.get(
                url,
                headers=auth_headers(self.api_key),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        ensure_ok(response)
        return parse_json(response)

    def _await_media(
        self,
        media_id: str,
        timeout: int,
        cancel_check: Callable[[], bool] | None,
    ) -> dict:
        """Poll a media task until it completes, fails or the timeout is reached."""
        deadline = time.monotonic() + timeout
        while True:
            if cancel_check is not None and cancel_check():
                raise CancelledError()
            payload = self._get(f"{MEDIA_URL}/{media_id}", timeout=POLL_INTERVAL * 4)
            status = str(payload.get("status") or "")
            if status == "completed":
                return payload
            if status in _TERMINAL_FAILURES:
                raise ProviderError(_media_error_message(payload))
            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"Generation did not finish within {timeout} s (task {media_id})."
                )
            time.sleep(POLL_INTERVAL)

    # ---------- results ----------
    def _result_from_media(self, payload: dict, fallback_model: str) -> GenerationResult:
        data = payload.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        images: list[GeneratedImage] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            encoded = item.get("b64_json") or item.get("b64")
            if encoded:
                images.append(
                    GeneratedImage(data=decode_base64(str(encoded)), media_type=None)
                )
                continue
            url = item.get("url")
            if url:
                images.append(self._download(str(url)))
        if not images:
            raise ConfigError("The provider returned no images.")
        usage = payload.get("usage") or {}
        return GenerationResult(
            images=images,
            cost_rub=as_float(usage.get("cost_rub") or usage.get("cost")),
            balance=None,
            model=str(payload.get("model") or fallback_model),
        )

    def _download(self, url: str) -> GeneratedImage:
        """Fetch a generated image from the temporary storage URL."""
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise wrap_network_error(exc) from exc
        return GeneratedImage(data=response.content, media_type=guess_media_type(response.content))

    # ---------- account ----------
    def check_account(self, timeout: int = 30) -> AccountInfo:
        """Return the organisation balance and the amount available to spend."""
        self._require_key()
        payload = self._get(BALANCE_URL, timeout)
        info = AccountInfo()
        info.balance = as_float(payload.get("amount"))
        info.budget_remaining = as_float(payload.get("available"))
        reserved = as_float(payload.get("reservedAmount"))
        spent = as_float(payload.get("spentAmount"))
        if reserved is not None:
            info.limits["reserved"] = reserved
        if spent is not None:
            info.limits["spent"] = spent
        return info

    # ---------- internals ----------
    def _require_key(self) -> None:
        if self.requires_key and not self.api_key:
            raise ConfigError("API key is not set for this provider.")


def _parameters_of(entry: dict) -> tuple[bool, dict]:
    """Return whether the catalog describes the model parameters, and those parameters.

    The catalog sometimes omits them entirely and sometimes lists them per provider.
    """
    for source in (entry, entry.get("top_provider")):
        if isinstance(source, dict) and isinstance(source.get("parameters"), dict):
            return True, source["parameters"]
    return False, {}


def _values(parameters: dict, name: str) -> list[str]:
    """Read the allowed values of a catalog parameter."""
    constraint = parameters.get(name)
    if not isinstance(constraint, dict):
        return []
    values = constraint.get("values")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _required(parameters: dict) -> list[str]:
    """Parameter names the model marks as required in the catalog.

    ``images`` is left out: reference images are validated separately against the
    maximum count, and a model that only transforms an uploaded image is not offered
    for prompt-driven generation at all.
    """
    names = []
    for name, constraint in parameters.items():
        if name == "images" or not isinstance(constraint, dict):
            continue
        if constraint.get("required"):
            names.append(name)
    return sorted(names)


def _price_range(pricing) -> tuple[float | None, float | None]:
    """Derive a per-image price range from a Polza.ai pricing block.

    Tiered pricing (for example ``image_resolution=2K`` costs more) becomes a range;
    a flat ``per_request`` price becomes a single value. Token-based prices cannot be
    converted to a per-image amount and are reported as unknown.
    """
    if not isinstance(pricing, dict):
        return None, None
    tiers = pricing.get("tiers")
    if isinstance(tiers, list) and tiers:
        costs = [
            cost
            for cost in (as_float(tier.get("cost_rub")) for tier in tiers if isinstance(tier, dict))
            if cost is not None
        ]
        if costs:
            return min(costs), max(costs)
    per_request = as_float(pricing.get("per_request"))
    if per_request is not None:
        return per_request, per_request
    return None, None


def _seed_for(seed: int | None, index: int) -> int | None:
    """Return the seed for the ``index``-th image of a multi-image request."""
    if seed is None:
        return None
    return 1 + (seed - 1 + index) % MAX_SEED


def _is_task(payload: dict) -> bool:
    """Whether a response is a task handle that still has to be polled."""
    return bool(payload.get("id")) and "data" not in payload


def _media_error_message(payload: dict) -> str:
    """Human-readable message for a failed media task."""
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "code"):
            if error.get(key):
                return str(error[key])
    if error:
        return str(error)
    return "The provider reported a failed generation."
