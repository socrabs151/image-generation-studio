"""Provider abstract base class and shared HTTP helpers.

A provider adapts one aggregator (AITUNNEL, Polza.ai, ...) to a common interface.
Providers must not import PySide6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from app.core.errors import (
    AuthenticationError,
    BadParameterError,
    InsufficientFundsError,
    NetworkError,
    ProviderError,
    ProviderTimeoutError,
)
from app.core.models import AccountInfo, GenerationRequest, GenerationResult, ModelInfo


class Provider(ABC):
    """Common interface for every aggregator."""

    id: str = ""
    display_name: str = ""
    requires_key: bool = True

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    @abstractmethod
    def fetch_catalog(self, timeout: int = 60) -> list[ModelInfo]:
        """Return the list of image-generation models."""

    @abstractmethod
    def generate(
        self,
        request: GenerationRequest,
        timeout: int = 180,
        cancel_check: Callable[[], bool] | None = None,
    ) -> GenerationResult:
        """Run a generation request and return the images and the actual cost.

        ``cancel_check`` is polled by providers that wait for a result in several
        steps, so a long task can be interrupted while it is still running.
        """""

    @abstractmethod
    def check_account(self, timeout: int = 30) -> AccountInfo:
        """Return balance and budget information for the configured key."""


def raise_for_status(status_code: int, detail: str = "") -> None:
    """Map an HTTP status code to the matching application exception."""
    message = detail.strip() or f"HTTP {status_code}"
    if status_code in (401, 403):
        raise AuthenticationError(message, status_code=status_code)
    if status_code == 402:
        raise InsufficientFundsError(message, status_code=status_code)
    if status_code == 400:
        raise BadParameterError(message, status_code=status_code)
    if status_code == 504:
        raise ProviderTimeoutError(message, status_code=status_code)
    raise ProviderError(message, status_code=status_code)


def wrap_network_error(exc: Exception) -> NetworkError:
    """Convert a transport-level failure into :class:`NetworkError`."""
    return NetworkError(f"Network request failed: {exc}")
