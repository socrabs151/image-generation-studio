"""Orchestration of image generation.

Responsibilities: validate the request, call the provider, save the resulting files
and append a history record. There are no automatic retries — a failed generation
must never be repeated silently, because each attempt spends real money.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import MAX_REFERENCE_BYTES, REFERENCE_FORMATS
from app.core.errors import BadParameterError, CancelledError
from app.core.models import GenerationRequest, GenerationResult, ModelInfo
from app.core.pricing import reserved_amount
from app.providers import create_provider
from app.services.history_store import HistoryRecord, HistoryStore, now_iso

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"RIFF", "webp"),
    (b"GIF8", "gif"),
)

# Model ids may be namespaced ("x-ai/grok-imagine-image"), and a slash in a file name
# would be read as a directory separator on Windows.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED_FILENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_MAX_MODEL_NAME_LENGTH = 60


def safe_filename_component(value: str, fallback: str = "model") -> str:
    """Turn an arbitrary identifier into a file name that is safe on Windows."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("-", value).strip("-._")
    cleaned = re.sub(r"-{2,}", "-", cleaned)[:_MAX_MODEL_NAME_LENGTH].strip("-._")
    if not cleaned or cleaned.upper() in _RESERVED_FILENAMES:
        return fallback
    return cleaned


def detect_format(data: bytes) -> str | None:
    """Return the image format ('png', 'jpeg', 'webp', 'gif') by magic bytes."""
    for signature, fmt in _MAGIC:
        if data.startswith(signature):
            return fmt
    return None


@dataclass(slots=True)
class GenerationOutcome:
    """Result of a successful generation, including saved file paths."""

    result: GenerationResult
    file_paths: list[str]


class GenerationService:
    """Validate, execute and persist a generation request."""

    def __init__(self, history: HistoryStore) -> None:
        self._history = history

    def reserved_amount(self, model: ModelInfo | None, n: int) -> float | None:
        """Return the amount the provider will freeze on the balance."""
        if model is None:
            return None
        return reserved_amount(model.max_price, n)

    def validate(self, request: GenerationRequest, model: ModelInfo | None) -> None:
        """Raise :class:`BadParameterError` when the request is invalid."""
        if not request.prompt.strip():
            raise BadParameterError("Prompt must not be empty.")
        if request.n < 1:
            raise BadParameterError("Image count must be at least 1.")
        if model is None:
            return
        if request.n > model.max_n:
            raise BadParameterError(f"This model allows at most {model.max_n} image(s).")
        references = request.input_references
        if references and not model.supports_edit:
            raise BadParameterError("This model does not support reference images.")
        if references and len(references) > model.max_input_references:
            raise BadParameterError(
                f"This model allows at most {model.max_input_references} reference image(s)."
            )
        for reference in references:
            if len(reference) > MAX_REFERENCE_BYTES:
                raise BadParameterError(
                    f"Reference image exceeds {MAX_REFERENCE_BYTES // (1024 * 1024)} MB."
                )
            if detect_format(reference) not in REFERENCE_FORMATS:
                allowed = ", ".join(REFERENCE_FORMATS)
                raise BadParameterError(f"Unsupported reference format. Allowed: {allowed}.")
        self._validate_required(request, model)
        self._validate_choice(request.background, model.backgrounds, "background")
        self._validate_choice(request.resolution, model.resolutions, "resolution")
        self._validate_choice(request.aspect_ratio, model.aspect_ratios, "aspect_ratio")

    @staticmethod
    def _validate_required(request: GenerationRequest, model: ModelInfo) -> None:
        """Refuse a request that omits a parameter the model cannot do without."""
        if not model.required_parameters:
            return
        sent = {
            "prompt": request.prompt,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "quality": request.quality,
            "size": request.size,
            "output_format": request.output_format,
            "background": request.background,
            **request.passthrough,
        }
        missing = model.missing_required(sent)
        if not missing:
            return
        options = {
            "resolution": model.resolutions,
            "aspect_ratio": model.aspect_ratios,
            "quality": model.qualities,
            "output_format": model.formats,
            "background": model.backgrounds,
        }
        details = []
        for name in missing:
            allowed = options.get(name)
            suffix = f" ({', '.join(allowed)})" if allowed else ""
            details.append(f"{name}{suffix}")
        raise BadParameterError(
            f'Model {model.id} requires {", ".join(details)}. '
            "Fill the field in the parameters panel."
        )

    def generate(
        self,
        request: GenerationRequest,
        model: ModelInfo | None,
        save_dir: Path,
        api_key: str,
        history_limit: int = 200,
        timeout: int = 180,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GenerationOutcome:
        """Run the request through the provider, save files and record history."""
        self.validate(request, model)
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        provider = create_provider(request.provider_id, api_key)
        try:
            result = provider.generate(request, timeout=timeout)
        except Exception as exc:
            self._history.add(
                HistoryRecord(
                    timestamp=now_iso(),
                    provider_id=request.provider_id,
                    model=request.model,
                    prompt=request.prompt,
                    n=request.n,
                    status="error",
                    error=str(exc),
                ),
                limit=history_limit,
            )
            raise
        if cancel_check is not None and cancel_check():
            raise CancelledError()

        file_paths = self._save_images(result, save_dir, request)
        self._history.add(
            HistoryRecord(
                timestamp=now_iso(),
                provider_id=request.provider_id,
                model=result.model,
                prompt=request.prompt,
                n=len(result.images),
                cost_rub=result.cost_rub,
                file_paths=file_paths,
                status="ok",
            ),
            limit=history_limit,
        )
        return GenerationOutcome(result=result, file_paths=file_paths)

    @staticmethod
    def _save_images(
        result: GenerationResult, save_dir: Path, request: GenerationRequest
    ) -> list[str]:
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_iso().replace(":", "-")
        model = safe_filename_component(result.model)
        paths: list[str] = []
        for index, image in enumerate(result.images, 1):
            extension = _EXTENSIONS.get(image.media_type or "", "png")
            suffix = f"_{index}" if len(result.images) > 1 else ""
            path = save_dir / f"{stamp}_{model}{suffix}.{extension}"
            path.write_bytes(image.data)
            paths.append(str(path))
        return paths

    @staticmethod
    def _validate_choice(value: str | None, allowed: list[str], field_name: str) -> None:
        if value and allowed and value not in allowed:
            options = ", ".join(allowed)
            raise BadParameterError(f"Invalid {field_name} '{value}'. Available: {options}.")

    @staticmethod
    def decode_data_url(data_url: str) -> bytes:
        """Decode a ``data:`` URI (used to reload references if needed)."""
        _, _, encoded = data_url.partition(",")
        return base64.b64decode(encoded)

    @staticmethod
    def extension_for(media_type: str | None) -> str:
        """Return a file extension for an image media type."""
        return _EXTENSIONS.get(media_type or "", "png")
