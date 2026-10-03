"""Orchestration of image generation.

Responsibilities: validate the request, call the provider, save the resulting files
and append a history record. There are no automatic retries — a failed generation
must never be repeated silently, because each attempt spends real money.
"""

from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import MAX_REFERENCE_BYTES, REFERENCE_FORMATS
from app.core.errors import (
    AppError,
    BadParameterError,
    CancelledError,
    InsufficientFundsError,
)
from app.core.models import (
    AccountInfo,
    GeneratedImage,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)
from app.core.pricing import can_afford, format_money, reserved_amount
from app.logging_setup import get_logger
from app.providers import create_provider
from app.providers.base import Provider
from app.services.file_names import (
    DEFAULT_FILENAME_TEMPLATE,
    NameParts,
    render_filename,
    unknown_placeholders,
)
from app.services.history_store import (
    HistoryRecord,
    HistoryStore,
    now_iso,
    request_snapshot,
)

LOGGER = get_logger()

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

# The format names reported by :func:`detect_format` mapped to the same extensions,
# so a detected JPEG is always written as .jpg and never as .jpeg.
_FORMAT_EXTENSIONS = {
    "png": "png",
    "jpeg": "jpg",
    "webp": "webp",
    "gif": "gif",
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


def _extension_for(image: GeneratedImage) -> str:
    """Pick the file extension for a saved image.

    The provider usually does not report a media type for base64 payloads, so the
    bytes decide: without this a JPEG result would be written as ``.png``.
    """
    declared = _EXTENSIONS.get(image.media_type or "")
    if declared:
        return declared
    return _FORMAT_EXTENSIONS.get(detect_format(image.data) or "", "png")


@dataclass(slots=True)
class GenerationOutcome:
    """Result of a successful generation, including saved file paths."""

    result: GenerationResult
    file_paths: list[str]
    account: AccountInfo | None = None


class GenerationService:
    """Validate, execute and persist a generation request."""

    def __init__(self, history: HistoryStore) -> None:
        self._history = history

    def validate(self, request: GenerationRequest, model: ModelInfo | None) -> None:
        """Raise :class:`BadParameterError` when the request is invalid."""
        if model is None:
            if not request.prompt.strip():
                raise BadParameterError("Prompt must not be empty.")
        elif model.supports_generation and not request.prompt.strip():
            # A model without text-to-image (an upscaler, for example) works on the
            # picture alone, so demanding a prompt would make it unusable.
            raise BadParameterError("Prompt must not be empty.")
        if request.n < 1:
            raise BadParameterError("Image count must be at least 1.")
        if model is None:
            return
        if request.n > model.max_n:
            raise BadParameterError(f"This model allows at most {model.max_n} image(s).")
        references = request.input_references
        if model.requires_reference and not references:
            raise BadParameterError(
                f'Model {model.id} transforms an uploaded image, so it needs a '
                "reference image. Load one in the workspace panel."
            )
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
        check_balance_first: bool = False,
        filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    ) -> GenerationOutcome:
        """Run the request through the provider, save files and record history.

        With ``check_balance_first`` the balance is asked for before anything is
        sent, so a request the aggregator would refuse fails here in a second
        instead of after the wait. Nothing is charged and nothing is written to
        the history when it refuses.
        """
        self.validate(request, model)
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        provider = create_provider(request.provider_id, api_key)
        account = self._check_affordable(provider, model, request, check_balance_first)
        snapshot = request_snapshot(request)
        started = time.monotonic()
        try:
            result = provider.generate(request, timeout=timeout, cancel_check=cancel_check)
        except Exception as exc:
            self._record(
                HistoryRecord(
                    timestamp=now_iso(),
                    provider_id=request.provider_id,
                    model=request.model,
                    prompt=request.prompt,
                    n=request.n,
                    status="error",
                    error=str(exc),
                    request=snapshot,
                    duration_seconds=time.monotonic() - started,
                ),
                limit=history_limit,
            )
            raise
        if cancel_check is not None and cancel_check():
            # The aggregator has already answered and already charged for this.
            # Cancelling here would throw away a paid picture and leave no trace
            # of the money, so the result is kept and the late cancellation is
            # only worth a line in the log.
            LOGGER.warning(
                "Cancellation arrived after the aggregator answered; the images of %s "
                "were already paid for and are saved.",
                request.model,
            )

        # The provider has already charged for this request, so a failure to
        # write the files must still leave a record with the cost: the money is
        # spent either way, and the user has to see what happened. Images that
        # did make it to disk are shown and recorded, the entry is marked as
        # failed so the missing ones are not passed off as a complete batch.
        try:
            file_paths, save_error = self._save_images(
                result, save_dir, request, template=filename_template
            )
        except OSError as exc:
            LOGGER.error("Could not save the images: %s", exc)
            self._record(
                HistoryRecord(
                    timestamp=now_iso(),
                    provider_id=request.provider_id,
                    model=result.model,
                    prompt=request.prompt,
                    n=len(result.images),
                    cost_rub=result.cost_rub,
                    status="error",
                    error=f"The images were paid for but not saved: {exc}",
                    request=snapshot,
                    duration_seconds=time.monotonic() - started,
                ),
                limit=history_limit,
            )
            raise
        if save_error:
            LOGGER.error(save_error)
        self._record(
            HistoryRecord(
                timestamp=now_iso(),
                provider_id=request.provider_id,
                model=result.model,
                prompt=request.prompt,
                n=len(result.images),
                cost_rub=result.cost_rub,
                file_paths=file_paths,
                status="error" if save_error else "ok",
                error=save_error or "",
                request=snapshot,
                duration_seconds=time.monotonic() - started,
            ),
            limit=history_limit,
        )
        return GenerationOutcome(result=result, file_paths=file_paths, account=account)

    def _check_affordable(
        self,
        provider: Provider,
        model: ModelInfo | None,
        request: GenerationRequest,
        enabled: bool,
    ) -> AccountInfo | None:
        """Refuse a request the key cannot pay for, before sending it.

        A batch is paid task by task, so a request that runs out of money half
        way leaves the earlier pictures already charged for. The estimate comes
        from the catalog and is an upper bound the aggregator freezes, which is
        exactly what a pre-flight check should compare against.

        A failing balance request is not a reason to block the user: the
        aggregator is the authority and will refuse on its own.
        """
        if not enabled:
            return None
        needed = reserved_amount(model.max_price, request.n) if model else None
        if needed is None:
            return None
        try:
            account = provider.check_account()
        except AppError as exc:
            LOGGER.warning("Could not check the balance before the request: %s", exc)
            return None
        for name, available in (
            ("balance", account.balance),
            ("key budget", account.budget_remaining),
        ):
            # can_afford lets an unknown figure through: a balance the
            # aggregator did not report must not block the user.
            if not can_afford(available, needed):
                raise InsufficientFundsError(
                    f"Not enough money: the request needs about {format_money(needed)} ₽, "
                    f"but the {name} is {format_money(available)} ₽. "
                    "Nothing was sent and nothing was charged."
                )
        return account

    def _record(self, record: HistoryRecord, limit: int) -> None:
        """Append a history entry, never failing the generation because of it.

        The provider has already charged for the request and the files are already
        written, so a broken or unwritable history file must not turn a paid
        generation into an error. The failure is logged instead.
        """
        try:
            self._history.add(record, limit=limit)
        except AppError as exc:
            LOGGER.warning("History was not written: %s", exc)
        except OSError as exc:
            LOGGER.warning("History file is not writable: %s", exc)

    @staticmethod
    def _save_images(
        result: GenerationResult,
        save_dir: Path,
        request: GenerationRequest,
        template: str = DEFAULT_FILENAME_TEMPLATE,
    ) -> tuple[list[str], str | None]:
        """Write the images and report what could not be written.

        Returns the saved paths and, when at least one image was lost, a text
        for the history entry. A batch is not thrown away because one file in
        the middle failed: the paid pictures that made it to disk are shown and
        the entry says that the batch is incomplete.

        ``template`` names the files; an empty one keeps the previous scheme.
        A name that is already taken gets a number appended, so a batch does not
        depend on the template mentioning ``{index}``.
        """
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_iso().replace(":", "-")
        model = safe_filename_component(result.model)
        unknown = unknown_placeholders(template)
        if unknown:
            LOGGER.warning(
                "The file name template uses unknown placeholders %s; they stay in "
                "the name as written.",
                ", ".join(unknown),
            )
        paths: list[str] = []
        failed = 0
        first_error = ""
        total = len(result.images)
        for index, image in enumerate(result.images, 1):
            extension = _extension_for(image)
            if template.strip():
                stem = render_filename(
                    template,
                    NameParts(
                        model=result.model,
                        provider=request.provider_id,
                        prompt=request.prompt,
                        index=index,
                        total=total,
                    ),
                )
            else:
                # An empty template keeps the previous naming.
                stem = f"{stamp}_{model}" + (f"_{index}" if total > 1 else "")
            for attempt in itertools.count(1):
                name = stem if attempt == 1 else f"{stem}_{attempt}"
                path = save_dir / f"{name}.{extension}"
                try:
                    # "x" refuses to open a name that is already taken, so a
                    # paid image is never silently overwritten by a second
                    # generation of the same model within the same second.
                    with path.open("xb") as handle:
                        handle.write(image.data)
                except FileExistsError:
                    continue
                except OSError as exc:
                    failed += 1
                    first_error = first_error or str(exc)
                    break
                paths.append(str(path))
                break
        if not paths:
            raise OSError(f"no image could be saved: {first_error or 'unknown error'}")
        if failed:
            return paths, (
                f"{failed} of {len(result.images)} images were paid for but could "
                f"not be saved: {first_error}"
            )
        return paths, None

    @staticmethod
    def _validate_choice(value: str | None, allowed: list[str], field_name: str) -> None:
        if value and allowed and value not in allowed:
            options = ", ".join(allowed)
            raise BadParameterError(f"Invalid {field_name} '{value}'. Available: {options}.")
