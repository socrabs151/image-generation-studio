"""Tests for generation request validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import BadParameterError
from app.core.models import GeneratedImage, GenerationRequest, GenerationResult, ModelInfo
from app.services.generation_service import GenerationService, safe_filename_component
from app.services.history_store import HistoryStore


@pytest.fixture()
def service(tmp_path: Path) -> GenerationService:
    return GenerationService(HistoryStore(tmp_path / "history.json"))


def _model(**overrides) -> ModelInfo:
    defaults = dict(
        id="gpt-image-1",
        provider_id="aitunnel",
        max_n=4,
        max_input_references=2,
        supports_edit=True,
        backgrounds=["auto", "transparent"],
        resolutions=["1K", "2K"],
        aspect_ratios=["1:1", "16:9"],
    )
    defaults.update(overrides)
    return ModelInfo(**defaults)


def _request(**overrides) -> GenerationRequest:
    defaults = dict(provider_id="aitunnel", model="gpt-image-1", prompt="cat")
    defaults.update(overrides)
    return GenerationRequest(**defaults)


def test_empty_prompt_rejected(service: GenerationService) -> None:
    with pytest.raises(BadParameterError):
        service.validate(_request(prompt="   "), _model())


def test_too_many_images(service: GenerationService) -> None:
    with pytest.raises(BadParameterError):
        service.validate(_request(n=5), _model(max_n=4))


def test_references_require_edit_support(service: GenerationService) -> None:
    with pytest.raises(BadParameterError):
        service.validate(_request(input_references=[b"x"]), _model(supports_edit=False))


def test_too_many_references(service: GenerationService) -> None:
    with pytest.raises(BadParameterError):
        service.validate(
            _request(input_references=[b"a", b"b", b"c"]),
            _model(max_input_references=2),
        )


def test_invalid_background(service: GenerationService) -> None:
    with pytest.raises(BadParameterError):
        service.validate(_request(background="opaque"), _model(backgrounds=["auto"]))


def test_valid_request_passes(service: GenerationService) -> None:
    service.validate(
        _request(n=2, background="transparent", resolution="1K", aspect_ratio="16:9"),
        _model(),
    )


def test_reference_format_rejected(service: GenerationService) -> None:
    # Plain text bytes do not look like a supported image format.
    with pytest.raises(BadParameterError):
        service.validate(_request(input_references=[b"not an image"]), _model())


def test_reference_format_accepted(service: GenerationService) -> None:
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    service.validate(_request(input_references=[png_header]), _model())


def test_namespaced_model_id_becomes_a_flat_file_name(
    service: GenerationService, tmp_path: Path
) -> None:
    result = GenerationResult(
        images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 8, media_type="image/png")],
        cost_rub=2.5,
        balance=None,
        model="x-ai/grok-imagine-image",
    )
    paths = service._save_images(result, tmp_path, _request())

    assert len(paths) == 1
    saved = Path(paths[0])
    assert saved.exists()
    assert saved.parent == tmp_path
    assert saved.name.endswith("_x-ai-grok-imagine-image.png")


def test_reserved_file_name_falls_back(service: GenerationService) -> None:
    assert safe_filename_component("CON") == "model"
    assert safe_filename_component("///") == "model"
    assert safe_filename_component("openai/gpt-image-1.5") == "openai-gpt-image-1.5"
