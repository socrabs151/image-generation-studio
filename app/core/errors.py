"""Application exception hierarchy.

All errors raised by the core and service layers derive from :class:`AppError`,
so the UI can catch a single base type and show a friendly message.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for every application error."""


class ConfigError(AppError):
    """Invalid or corrupted configuration file."""


class NetworkError(AppError):
    """A network request failed (connection, DNS, TLS, timeout)."""


class ProviderError(AppError):
    """A provider (aggregator) rejected the request or returned an error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class InsufficientFundsError(ProviderError):
    """The provider reported insufficient balance or budget (HTTP 402)."""


class BadParameterError(ProviderError):
    """The provider rejected a request parameter (HTTP 400)."""


class AuthenticationError(ProviderError):
    """The API key is missing or invalid (HTTP 401/403)."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond in time (HTTP 504)."""


class CancelledError(AppError):
    """The operation was cancelled by the user."""
