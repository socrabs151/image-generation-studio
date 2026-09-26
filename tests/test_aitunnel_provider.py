"""Tests for the AITUNNEL provider payload building and catalog parsing.

Network access is not required: only pure functions are exercised.
"""

from __future__ import annotations

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


def test_parameter_without_auto_is_treated_as_mandatory() -> None:
    # AITUNNEL does not publish which parameters are mandatory; a value list without
    # "auto" cannot be left out, otherwise the provider rejects the request.
    model = AitunnelProvider._parse_model(
        "gemini",
        {
            "supported_aspect_ratios": ["1:1", "16:9"],
            "supported_resolutions": ["1K", "2K"],
            "supported_quality": ["auto", "high"],
            "supported_output_formats": ["auto", "png"],
        },
    )

    assert model.required_parameters == ["aspect_ratio", "resolution"]


def test_no_required_parameters_without_value_lists() -> None:
    model = AitunnelProvider._parse_model("plain", {"description": "no options"})

    assert model.required_parameters == []
