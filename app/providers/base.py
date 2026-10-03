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
    ProviderBusyError,
    ProviderError,
    ProviderNotFoundError,
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


# Statuses that are worth telling apart. Left in the generic ProviderError they all
# looked alike in the log, which is no help when deciding whether to retry, fix a
# parameter or top up an account.
_STATUS_ERRORS: dict[int, type] = {
    400: BadParameterError,
    401: AuthenticationError,
    402: InsufficientFundsError,
    403: AuthenticationError,
    404: ProviderNotFoundError,
    408: ProviderTimeoutError,
    413: BadParameterError,
    422: BadParameterError,
    429: ProviderBusyError,
    500: ProviderError,
    502: ProviderError,
    503: ProviderBusyError,
    504: ProviderTimeoutError,
}


def raise_for_status(status_code: int, detail: str = "") -> None:
    """Map an HTTP status code to the matching application exception.

    ``429`` and ``503`` become :class:`ProviderBusyError`, which is the one that
    says "the aggregator asked us to wait"; ``413`` is a parameter problem on our
    side (a reference image too large), not a provider fault.
    """
    message = detail.strip() or f"HTTP {status_code}"
    error = _STATUS_ERRORS.get(status_code, ProviderError)
    raise error(message, status_code=status_code)


def wrap_network_error(exc: Exception) -> NetworkError:
    """Convert a transport-level failure into :class:`NetworkError`."""
    return NetworkError(f"Network request failed: {exc}")
