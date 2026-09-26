"""Aggregator provider registry.

Registering a new aggregator means adding its provider class here; the rest of the
application discovers providers through :func:`available_providers`.
"""

from __future__ import annotations

from app.providers.aitunnel import AitunnelProvider
from app.providers.base import Provider
from app.providers.polza import PolzaProvider

_PROVIDERS: dict[str, type[Provider]] = {
    AitunnelProvider.id: AitunnelProvider,
    PolzaProvider.id: PolzaProvider,
}


def provider_ids() -> list[str]:
    """Return the ids of all registered providers."""
    return list(_PROVIDERS)


def provider_choices() -> list[tuple[str, str]]:
    """Return ``(provider_id, display_name)`` pairs in registration order."""
    return [(key, provider.display_name or key) for key, provider in _PROVIDERS.items()]


def display_name(provider_id: str) -> str:
    """Return the human-readable name of a provider, falling back to its id."""
    provider = _PROVIDERS.get(provider_id)
    return provider.display_name if provider and provider.display_name else provider_id


def get_provider_class(provider_id: str) -> type[Provider]:
    """Return the provider class for ``provider_id`` or raise ``KeyError``."""
    return _PROVIDERS[provider_id]


def create_provider(provider_id: str, api_key: str = "") -> Provider:
    """Instantiate a provider by id with the given API key."""
    return get_provider_class(provider_id)(api_key)
