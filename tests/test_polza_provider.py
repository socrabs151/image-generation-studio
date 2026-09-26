"""Tests for the Polza.ai provider: catalog parsing, payloads and result decoding.

Network access is not required: payload builders and parsers are exercised
directly, and the few HTTP paths use stubbed helpers.
"""

from __future__ import annotations

import base64

import pytest

from app.core.errors import InsufficientFundsError
from app.core.models import GenerationRequest
from app.providers import create_provider, provider_choices, provider_ids
from app.providers.http_utils import ensure_ok
from app.providers.polza import PolzaProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _entry(**overrides) -> dict:
    entry = {
        "id": "bytedance/seedream-4",
        "name": "Seedream 4",
        "type": "image",
        "short_description": "Image generation",
        "top_provider": {"pricing": {"tiers": [{"cost_rub": "14.00000000"}]}},
        "parameters": {
            "prompt": {"required": True, "max_length": 5000},
            "aspect_ratio": {"values": ["1:1", "16:9"]},
            "image_resolution": {"values": ["1K", "2K", "4K"]},
            "images": {"min": 0, "max": 10},
            "seed": {},
        },
    }
    entry.update(overrides)
    return entry


def _request(**overrides) -> GenerationRequest:
    defaults = dict(provider_id="polza", model="bytedance/seedream-4", prompt="a cat")
    defaults.update(overrides)
    return GenerationRequest(**defaults)


# ---------- registry ----------
def test_polza_is_registered() -> None:
    assert "polza" in provider_ids()
    assert create_provider("polza", "key").display_name == "Polza.ai"
    assert ("polza", "Polza.ai") in provider_choices()


# ---------- catalog ----------
def test_parse_model_reads_catalog_parameters() -> None:
    model = PolzaProvider._parse_model(_entry())

    assert model.id == "bytedance/seedream-4"
    assert model.provider_id == "polza"
    assert model.resolutions == ["1K", "2K", "4K"]
    assert model.aspect_ratios == ["1:1", "16:9"]
    assert model.max_input_references == 10
    assert model.supports_edit is True
    assert model.supports_seed is True
    assert model.supports_generation is True
    assert model.allowed_passthrough == []


def test_parse_model_exposes_extra_parameters_as_passthrough() -> None:
    entry = _entry(
        parameters={
            "prompt": {},
            "images": {"max": 1},
            "strength": {},
            "isEnhance": {},
        }
    )
    model = PolzaProvider._parse_model(entry)

    assert sorted(model.allowed_passthrough) == ["isEnhance", "strength"]
    assert model.supports_seed is False
    assert model.max_input_references == 1


def test_parse_model_price_range_from_tiers() -> None:
    entry = _entry(
        top_provider={
            "pricing": {
                "tiers": [
                    {"conditions": ["image_resolution=1K"], "cost_rub": "14.00000000"},
                    {"conditions": ["image_resolution=2K"], "cost_rub": "24.00000000"},
                ]
            }
        }
    )
    model = PolzaProvider._parse_model(entry)

    assert model.min_price == 14.0
    assert model.max_price == 24.0
    assert model.price_range is True


def test_parse_model_flat_per_request_price() -> None:
    entry = _entry(top_provider={"pricing": {"per_request": "2.90000000"}})
    model = PolzaProvider._parse_model(entry)

    assert model.min_price == 2.9
    assert model.max_price == 2.9
    assert model.price_range is False


def test_parse_model_without_described_parameters() -> None:
    model = PolzaProvider._parse_model({"id": "google/gemini-x", "parameters": []})

    assert model.supports_generation is True
    assert model.max_input_references == 0
    assert model.supports_edit is False
    assert model.min_price is None


def test_parse_model_reads_required_flags() -> None:
    entry = _entry(
        parameters={
            "prompt": {"required": True},
            "aspect_ratio": {"required": True, "values": ["1:1", "16:9"]},
            "quality": {"required": True, "values": ["high"]},
            "image_resolution": {"values": ["1K"]},
            "seed": {},
        }
    )
    model = PolzaProvider._parse_model(entry)

    assert model.required_parameters == ["aspect_ratio", "prompt", "quality"]


def test_required_ignores_reference_images() -> None:
    # Images are checked against the maximum count instead, and a model that only
    # transforms an upload is not offered for prompt-driven generation.
    entry = _entry(
        parameters={
            "prompt": {"required": True},
            "images": {"required": True, "min": 1, "max": 1},
            "upscale_factor": {"required": True, "values": ["2", "4"]},
        }
    )
    model = PolzaProvider._parse_model(entry)

    assert model.required_parameters == ["prompt", "upscale_factor"]


def test_parse_model_without_prompt_is_not_a_generation_model() -> None:
    model = PolzaProvider._parse_model(
        _entry(parameters={"images": {"max": 1}, "upscale_factor": {"values": ["2"]}})
    )

    assert model.supports_generation is False


# ---------- payloads ----------
def test_build_payload_uses_catalog_parameter_names() -> None:
    request = _request(
        n=3,
        aspect_ratio="16:9",
        resolution="2K",
        quality="high",
        output_format="png",
        background="transparent",
        seed=42,
    )
    body = PolzaProvider._build_payload(request)

    assert body["model"] == "bytedance/seedream-4"
    assert body["async"] is False
    image_input = body["input"]
    assert image_input["prompt"] == "a cat"
    assert image_input["aspect_ratio"] == "16:9"
    assert image_input["image_resolution"] == "2K"
    assert image_input["quality"] == "high"
    assert image_input["output_format"] == "png"
    assert image_input["background"] == "transparent"
    assert image_input["seed"] == 42
    assert "images" not in image_input


def test_build_payload_merges_passthrough() -> None:
    request = _request(passthrough={"isEnhance": True})
    body = PolzaProvider._build_payload(request)

    assert body["isEnhance"] is True


def test_build_payload_encodes_references_as_base64() -> None:
    request = _request(input_references=[PNG])
    body = PolzaProvider._build_payload(request)

    assert body["input"]["images"] == [
        {"type": "base64", "data": base64.b64encode(PNG).decode("ascii")}
    ]


def test_build_payload_omits_a_multi_image_field() -> None:
    # One media task returns one image, so no count field is sent at all.
    body = PolzaProvider._build_payload(_request(n=4))

    assert "max_images" not in body["input"]
    assert "n" not in body["input"]


# ---------- several images ----------
def test_several_images_run_one_task_each(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PolzaProvider("key")
    seen: list[dict] = []

    def fake_post(url: str, body: dict, timeout: int) -> dict:
        seen.append(body)
        return {
            "status": "completed",
            "model": body["model"],
            "data": {"b64_json": base64.b64encode(PNG).decode("ascii")},
            "usage": {"cost_rub": 2.9},
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = provider.generate(_request(n=4), timeout=1)

    assert len(seen) == 4
    assert len(result.images) == 4
    assert result.cost_rub == pytest.approx(11.6)


def test_several_images_shift_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PolzaProvider("key")
    seeds: list[int | None] = []

    def fake_post(url: str, body: dict, timeout: int) -> dict:
        seeds.append(body["input"].get("seed"))
        return {
            "status": "completed",
            "model": body["model"],
            "data": {"b64_json": base64.b64encode(PNG).decode("ascii")},
            "usage": {"cost_rub": 2.9},
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    provider.generate(_request(n=3, seed=100), timeout=1)

    assert seeds == [100, 101, 102]


def test_single_image_runs_one_task(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PolzaProvider("key")
    calls: list[dict] = []

    def fake_post(url: str, body: dict, timeout: int) -> dict:
        calls.append(body)
        return {
            "status": "completed",
            "model": body["model"],
            "data": {"b64_json": base64.b64encode(PNG).decode("ascii")},
            "usage": {"cost_rub": 2.9},
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = provider.generate(_request(n=1, seed=7), timeout=1)

    assert len(calls) == 1
    assert len(result.images) == 1
    assert result.cost_rub == 2.9


def test_cancel_stops_before_the_next_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.errors import CancelledError

    provider = PolzaProvider("key")
    calls: list[dict] = []

    def fake_post(url: str, body: dict, timeout: int) -> dict:
        calls.append(body)
        return {
            "status": "completed",
            "model": body["model"],
            "data": {"b64_json": base64.b64encode(PNG).decode("ascii")},
            "usage": {"cost_rub": 2.9},
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    # Cancel after the first task has been paid for and produced an image.
    with pytest.raises(CancelledError):
        provider.generate(_request(n=4), timeout=1, cancel_check=lambda: len(calls) >= 1)

    assert len(calls) == 1


# ---------- results ----------
def test_result_from_media_decodes_base64_and_cost() -> None:
    provider = PolzaProvider("key")
    payload = {
        "status": "completed",
        "model": "bytedance/seedream-4",
        "data": {"b64_json": base64.b64encode(PNG).decode("ascii")},
        "usage": {"cost_rub": 2.5, "cost": 2.5},
    }
    result = provider._result_from_media(payload, "fallback")

    assert result.images[0].data == PNG
    assert result.cost_rub == 2.5
    assert result.model == "bytedance/seedream-4"


def test_result_from_media_accepts_a_list_payload() -> None:
    provider = PolzaProvider("key")
    payload = {
        "data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}],
        "usage": {"cost": 4.0},
    }
    result = provider._result_from_media(payload, "fallback")

    assert len(result.images) == 1
    assert result.cost_rub == 4.0
    assert result.model == "fallback"


# ---------- account ----------
def test_check_account_maps_balance_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PolzaProvider("key")
    payload = {
        "amount": "1234.56000000",
        "available": "1200.06000000",
        "reservedAmount": "12.50000000",
        "spentAmount": "845.30000000",
    }
    monkeypatch.setattr(provider, "_get", lambda url, timeout: payload)

    info = provider.check_account()

    assert info.balance == 1234.56
    assert info.budget_remaining == 1200.06
    assert info.limits["reserved"] == 12.5
    assert info.limits["spent"] == 845.3


def test_check_account_requires_key() -> None:
    from app.core.errors import ConfigError

    with pytest.raises(ConfigError):
        PolzaProvider("").check_account()


# ---------- errors ----------
class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_insufficient_balance_code_maps_to_funds_error() -> None:
    response = _Response(
        400, {"error": {"code": "INSUFFICIENT_BALANCE", "message": "Not enough money"}}
    )

    with pytest.raises(InsufficientFundsError):
        ensure_ok(response)


def test_nested_error_message_is_extracted() -> None:
    response = _Response(400, {"error": {"code": "BAD_REQUEST", "message": "Bad prompt"}})

    with pytest.raises(Exception) as info:
        ensure_ok(response)

    assert "Bad prompt" in str(info.value)
