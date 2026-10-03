"""Tests for the AITUNNEL provider payload building and catalog parsing.

Network access is not required: only pure functions are exercised.
"""

from __future__ import annotations

import pytest

from app.core.models import GenerationRequest
from app.providers.aitunnel import AitunnelProvider


def test_parse_model() -> None:
    entry = {
        "provider": "microsoft",
        "description": "test model",
        "min_price_per_image": 1.02,
        "max_price_per_image": 20.4,
        "supported_resolutions": ["1K", "2K"],
        "supported_aspect_ratios": ["1:1"],
        "supported_quality": ["low", "high"],
        "supported_output_formats": ["png"],
        "supported_background": ["auto"],
        "supports_seed": True,
        "supports_generation": True,
        "supports_edit": True,
        "max_n": 4,
        "max_input_references": 5,
        "allowed_passthrough_parameters": ["web_grounding"],
    }
    model = AitunnelProvider._parse_model("test-model", entry)

    assert model.id == "test-model"
    assert model.provider_id == "aitunnel"
    assert model.min_price == 1.02
    assert model.max_price == 20.4
    assert model.max_n == 4
    assert model.max_input_references == 5
    assert model.supports_edit is True
    assert model.backgrounds == ["auto"]


def test_build_payload_skips_empty_values() -> None:
    request = GenerationRequest(
        provider_id="aitunnel",
        model="seedream-4.5",
        prompt="sunset",
        n=2,
        resolution="2K",
    )
    payload = AitunnelProvider._build_payload(request)

    assert payload["model"] == "seedream-4.5"
    assert payload["n"] == 2
    assert payload["resolution"] == "2K"
    assert "quality" not in payload
    assert "seed" not in payload
    assert "input_references" not in payload


def test_build_payload_with_references() -> None:
    request = GenerationRequest(
        provider_id="aitunnel",
        model="gpt-image-1",
        prompt="add glasses",
        input_references=[b"\x89PNG\r\n"],
    )
    payload = AitunnelProvider._build_payload(request)

    references = payload["input_references"]
    assert len(references) == 1
    assert references[0]["type"] == "image_url"
    assert references[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_value_list_without_auto_is_not_mandatory() -> None:
    """The vendor's table marks every image parameter optional.

    Only `model` and `prompt` are required, so a list without "auto" must not make
    the panel preselect a value: `resolution` is exactly what decides the price, and
    sending one the user never chose silently changed the amount.
    """
    model = AitunnelProvider._parse_model(
        "gemini",
        {
            "supported_aspect_ratios": ["1:1", "16:9"],
            "supported_resolutions": ["1K", "2K"],
            "supported_quality": ["auto", "high"],
            "supported_output_formats": ["auto", "png"],
        },
    )

    assert model.required_parameters == []
    # The values are still advertised, the user just gets the choice.
    assert model.resolutions == ["1K", "2K"]
    assert model.aspect_ratios == ["1:1", "16:9"]


def test_no_required_parameters_without_value_lists() -> None:
    model = AitunnelProvider._parse_model("plain", {"description": "no options"})

    assert model.required_parameters == []


# ---------- a paid batch must survive one bad element ----------


def _generation_payload(*items: dict) -> dict:
    return {
        "data": list(items),
        "usage": {"cost_rub": 30.0, "balance": 100.0},
    }


def _response(payload: dict) -> object:
    class _Response:
        status_code = 200

        def json(self) -> dict:
            return payload

    return _Response()


def test_one_unreadable_image_does_not_lose_the_paid_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole response is paid for as a whole. One element that cannot be
    decoded must not throw the others away."""
    import base64

    provider = AitunnelProvider("key")
    good = {"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nrest").decode("ascii")}
    payload = _generation_payload(good, {"b64_json": "@@not base64@@"}, dict(good))
    monkeypatch.setattr(
        "app.providers.aitunnel.requests.post", lambda *a, **k: _response(payload)
    )
    monkeypatch.setattr("app.providers.aitunnel.ensure_ok", lambda *a, **k: None)
    monkeypatch.setattr("app.providers.aitunnel.parse_json", lambda *a, **k: payload)

    result = provider.generate(
        GenerationRequest(provider_id="aitunnel", model="m", prompt="cat", n=3)
    )

    assert len(result.images) == 2
    assert result.cost_rub == 30.0


def test_an_image_without_data_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    provider = AitunnelProvider("key")
    good = {"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nrest").decode("ascii")}
    payload = _generation_payload(good, {"url": "https://example.com/image.png"})
    monkeypatch.setattr(
        "app.providers.aitunnel.requests.post", lambda *a, **k: _response(payload)
    )
    monkeypatch.setattr("app.providers.aitunnel.ensure_ok", lambda *a, **k: None)
    monkeypatch.setattr("app.providers.aitunnel.parse_json", lambda *a, **k: payload)

    result = provider.generate(
        GenerationRequest(provider_id="aitunnel", model="m", prompt="cat", n=2)
    )

    assert len(result.images) == 1
    assert result.cost_rub == 30.0


def test_a_response_with_nothing_usable_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.errors import ConfigError

    provider = AitunnelProvider("key")
    payload = _generation_payload({"b64_json": "@@not base64@@"})
    monkeypatch.setattr("app.providers.aitunnel.requests.post", lambda *a, **k: _response(payload))
    monkeypatch.setattr("app.providers.aitunnel.ensure_ok", lambda *a, **k: None)
    monkeypatch.setattr("app.providers.aitunnel.parse_json", lambda *a, **k: payload)

    with pytest.raises(ConfigError):
        provider.generate(
            GenerationRequest(provider_id="aitunnel", model="m", prompt="cat", n=1)
        )
