"""Aggregator provider registry.

Registering a new aggregator means adding its provider class here; the rest of the
application discovers providers through :func:`available_providers`.
"""

from __future__ import annotations

from app.providers.aitunnel import AitunnelProvider
from app.providers.base import Provider

_PROVIDERS: dict[str, type[Provider]] = {
    AitunnelProvider.id: AitunnelProvider,
}


def provider_ids() -> list[str]:
    """Return the ids of all registered providers."""
    return list(_PROVIDERS)


def get_provider_class(provider_id: str) -> type[Provider]:
    """Return the provider class for ``provider_id`` or raise ``KeyError``."""
    return _PROVIDERS[provider_id]


def create_provider(provider_id: str, api_key: str = "") -> Provider:
    """Instantiate a provider by id with the given API key."""
    return get_provider_class(provider_id)(api_key)
