"""Tests for generation request validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import BadParameterError, ConfigError
from app.core.models import (
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)
from app.services.generation_service import GenerationService, safe_filename_component
from app.services.history_store import HistoryRecord, HistoryStore


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
    paths, save_error = service._save_images(result, tmp_path, _request())

    assert len(paths) == 1
    saved = Path(paths[0])
    assert saved.exists()
    assert saved.parent == tmp_path
    assert saved.name.endswith("_x-ai-grok-imagine-image.png")


def test_reserved_file_name_falls_back(service: GenerationService) -> None:
    assert safe_filename_component("CON") == "model"
    assert safe_filename_component("///") == "model"
    assert safe_filename_component("openai/gpt-image-1.5") == "openai-gpt-image-1.5"


def test_missing_required_parameter_is_rejected(
    service: GenerationService,
) -> None:
    model = _model(
        aspect_ratios=["1:1", "16:9"],
        required_parameters=["aspect_ratio"],
    )
    with pytest.raises(BadParameterError) as info:
        service.validate(_request(), model)

    message = str(info.value)
    assert "aspect_ratio" in message
    assert "1:1, 16:9" in message
    assert model.id in message


def test_required_parameter_satisfied_by_the_request(service: GenerationService) -> None:
    model = _model(aspect_ratios=["1:1"], required_parameters=["aspect_ratio"])
    service.validate(_request(aspect_ratio="1:1"), model)


def test_required_parameter_satisfied_by_passthrough(service: GenerationService) -> None:
    model = _model(
        allowed_passthrough=["upscale_factor"],
        required_parameters=["upscale_factor"],
    )
    service.validate(_request(passthrough={"upscale_factor": "2"}), model)
    with pytest.raises(BadParameterError):
        service.validate(_request(), model)


def test_no_required_parameters_keeps_optional_fields_empty(
    service: GenerationService,
) -> None:
    model = _model(aspect_ratios=["1:1", "16:9"], required_parameters=[])
    service.validate(_request(), model)


def test_model_needing_a_reference_is_rejected_without_one(
    service: GenerationService,
) -> None:
    model = _model(requires_reference=True, max_input_references=1, supports_edit=True)
    with pytest.raises(BadParameterError) as info:
        service.validate(_request(), model)
    assert "reference image" in str(info.value)


def test_model_needing_a_reference_accepts_one(service: GenerationService) -> None:
    model = _model(requires_reference=True, max_input_references=1, supports_edit=True)
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    service.validate(_request(input_references=[png_header]), model)


def test_upscaler_works_without_a_prompt(service: GenerationService) -> None:
    # A model without text-to-image works on the picture alone: demanding a prompt
    # made the upscale model unusable.
    model = _model(
        supports_generation=False,
        requires_reference=True,
        max_input_references=1,
        supports_edit=True,
        allowed_passthrough=["upscale_factor"],
        required_parameters=[],
    )
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    service.validate(
        _request(prompt="", input_references=[png_header], passthrough={"upscale_factor": "2"}),
        model,
    )


def test_text_to_image_still_requires_a_prompt(service: GenerationService) -> None:
    with pytest.raises(BadParameterError) as info:
        service.validate(_request(prompt="   "), _model(supports_generation=True))
    assert "Prompt" in str(info.value)


def test_extension_follows_the_bytes_when_no_media_type(
    service: GenerationService, tmp_path: Path
) -> None:
    # Polza.ai returns base64 payloads without a media type, so a JPEG result used
    # to be written as a .png file.
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 8
    result = GenerationResult(
        images=[GeneratedImage(data=jpeg)],
        cost_rub=1.0,
        balance=None,
        model="muse-image",
    )

    paths, save_error = service._save_images(result, tmp_path, _request())

    assert paths[0].endswith(".jpg")
    assert Path(paths[0]).read_bytes() == jpeg


def test_declared_media_type_wins_over_the_bytes(
    service: GenerationService, tmp_path: Path
) -> None:
    result = GenerationResult(
        images=[GeneratedImage(data=b"RIFF" + b"0" * 8, media_type="image/png")],
        cost_rub=1.0,
        balance=None,
        model="muse-image",
    )

    paths, save_error = service._save_images(result, tmp_path, _request())

    assert paths[0].endswith(".png")


def test_unknown_bytes_fall_back_to_png(service: GenerationService, tmp_path: Path) -> None:
    result = GenerationResult(
        images=[GeneratedImage(data=b"not an image at all")],
        cost_rub=1.0,
        balance=None,
        model="muse-image",
    )

    paths, save_error = service._save_images(result, tmp_path, _request())

    assert paths[0].endswith(".png")


def test_paid_result_survives_a_broken_history_file(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A history that cannot be written must not discard a generated image."""
    result = GenerationResult(
        images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 8)],
        cost_rub=1.0,
        balance=None,
        model="muse-image",
    )
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(result),
    )
    monkeypatch.setattr(
        service._history, "add", _raise_config_error, raising=True
    )

    outcome = service.generate(_request(), _model(), save_dir=tmp_path, api_key="k")

    assert len(outcome.file_paths) == 1
    assert Path(outcome.file_paths[0]).exists()
    assert outcome.result.cost_rub == 1.0


def test_failed_generation_still_raises_when_history_is_broken(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(None),
    )
    monkeypatch.setattr(
        service._history, "add", _raise_config_error, raising=True
    )

    with pytest.raises(ConfigError):
        service.generate(_request(), _model(), save_dir=tmp_path, api_key="k")


def _raise_config_error(*_args, **_kwargs) -> None:
    raise ConfigError("Cannot read history file: broken")


# ---------- what ends up in the history is what matters ----------


def test_the_cost_and_the_files_reach_the_history(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paid generation has to be visible in the history with its cost and
    its files. Removing either from the record breaks nothing else, so this
    is the only thing that notices."""
    recorded: list[HistoryRecord] = []
    result = GenerationResult(
        images=[
            GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"1" * 8),
            GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"2" * 8),
        ],
        cost_rub=12.5,
        balance=None,
        model="muse-image",
    )
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(result),
    )
    monkeypatch.setattr(
        service._history, "add", lambda record, limit: recorded.append(record), raising=True
    )

    outcome = service.generate(_request(n=2), _model(), save_dir=tmp_path, api_key="k")

    assert len(recorded) == 1
    record = recorded[0]
    assert record.status == "ok"
    assert record.cost_rub == 12.5
    assert record.n == 2
    assert record.model == "muse-image"
    assert len(record.file_paths) == 2
    assert all(Path(path).exists() for path in record.file_paths)
    assert record.file_paths == outcome.file_paths


def test_a_failed_generation_is_recorded_with_its_text(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[HistoryRecord] = []
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(None),
    )
    monkeypatch.setattr(
        service._history, "add", lambda record, limit: recorded.append(record), raising=True
    )

    with pytest.raises(ConfigError):
        service.generate(_request(), _model(), save_dir=tmp_path, api_key="k")

    assert len(recorded) == 1
    assert recorded[0].status == "error"
    assert "refused" in recorded[0].error
    assert recorded[0].n == 1


def test_a_failure_to_write_the_files_still_records_the_cost(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider has charged by then. A full disk must not erase the
    record of what the money was spent on."""
    recorded: list[HistoryRecord] = []
    result = GenerationResult(
        images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 8)],
        cost_rub=7.25,
        balance=None,
        model="muse-image",
    )
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(result),
    )
    monkeypatch.setattr(
        service._history, "add", lambda record, limit: recorded.append(record), raising=True
    )
    # save_dir points at an existing file, so mkdir fails.
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        service.generate(_request(), _model(), save_dir=blocker, api_key="k")

    assert len(recorded) == 1
    assert recorded[0].cost_rub == 7.25
    assert recorded[0].status == "error"
    assert "not saved" in recorded[0].error


def test_one_unwritable_file_does_not_lose_the_rest_of_the_batch(
    service: GenerationService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Six paid images, one write fails: five are shown and recorded, and the
    entry says the batch is incomplete instead of passing it off as whole."""
    recorded: list[HistoryRecord] = []
    result = GenerationResult(
        images=[GeneratedImage(data=b"\x89PNG\r\n\x1a\n" + bytes([n]) * 8) for n in range(6)],
        cost_rub=30.0,
        balance=None,
        model="muse-image",
    )
    monkeypatch.setattr(
        "app.services.generation_service.create_provider",
        lambda provider_id, api_key: _StubProvider(result),
    )
    monkeypatch.setattr(
        service._history, "add", lambda record, limit: recorded.append(record), raising=True
    )
    real_write = Path.write_bytes
    calls = {"n": 0}

    def flaky_write(self: Path, data: bytes) -> int:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(28, "No space left on device")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky_write)

    outcome = service.generate(
        _request(n=6), _model(max_n=6), save_dir=tmp_path, api_key="k"
    )

    assert len(outcome.file_paths) == 5
    assert all(Path(path).exists() for path in outcome.file_paths)
    assert len(recorded) == 1
    assert recorded[0].status == "error"
    assert recorded[0].cost_rub == 30.0
    assert len(recorded[0].file_paths) == 5
    assert "1 of 6" in recorded[0].error


class _StubProvider:
    """A provider that returns a prepared result or fails."""

    def __init__(self, result: GenerationResult | None) -> None:
        self._result = result

    def generate(self, *_args, **_kwargs) -> GenerationResult:
        if self._result is None:
            raise ConfigError("the provider refused the request")
        return self._result
