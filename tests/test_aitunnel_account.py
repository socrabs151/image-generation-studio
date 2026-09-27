"""Tests for the AITUNNEL provider: account lookup resilience and catalog parsing."""

from __future__ import annotations

import json

import pytest
import requests

from app.providers.aitunnel import ACCOUNT_URL, AitunnelProvider
from app.providers.base import AuthenticationError


class _Response:
    """Minimal stand-in for a requests response."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)
        self.content = self.text.encode("utf-8")

    @property
    def ok(self) -> bool:  # noqa: D401 - mirrors requests
        return self.status_code < 400

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _install(monkeypatch: pytest.MonkeyPatch, answers: dict[str, _Response]) -> list[str]:
    """Answer the account endpoints; return the list of the requested names."""
    requested: list[str] = []

    def fake_get(url: str, **_kwargs) -> _Response:
        name = url.rsplit("/", 1)[-1]
        requested.append(name)
        assert url.startswith(ACCOUNT_URL)
        return answers[name]

    monkeypatch.setattr(requests, "get", fake_get)
    return requested


def test_balance_is_returned_even_when_profile_endpoints_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A key without access to /key and /me must still show the balance.
    _install(
        monkeypatch,
        {
            "balance": _Response(200, {"balance": 73.6, "budget": 200.0}),
            "key": _Response(403, {"error": "forbidden"}),
            "me": _Response(403, {"error": "forbidden"}),
        },
    )
    provider = AitunnelProvider("sk-test")

    info = provider.check_account()

    assert info.balance == pytest.approx(73.6)
    assert info.budget_remaining == pytest.approx(200.0)
    assert info.email is None


def test_balance_error_is_still_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "balance": _Response(401, {"error": "unauthorized"}),
            "key": _Response(200, {}),
            "me": _Response(200, {}),
        },
    )
    provider = AitunnelProvider("sk-test")

    with pytest.raises(AuthenticationError):
        provider.check_account()


def test_extra_profile_data_is_used_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "balance": _Response(200, {"balance": 10.0, "budget": 20.0}),
            "key": _Response(200, {"budget": {"initial": 100.0}, "allowed_models": ["m1"]}),
            "me": _Response(200, {"email": "user@example.com"}),
        },
    )
    provider = AitunnelProvider("sk-test")

    info = provider.check_account()

    assert info.budget_initial == pytest.approx(100.0)
    assert info.email == "user@example.com"
    assert info.limits["allowed_models"] == ["m1"]


def test_catalog_survives_a_non_numeric_field() -> None:
    # max_n arriving as a string used to raise ValueError and lose the whole catalog.
    entry = {
        "min_price_per_image": 1.0,
        "max_price_per_image": 2.0,
        "max_n": "many",
        "max_input_references": "lots",
    }

    model = AitunnelProvider._parse_model("broken-model", entry)

    assert model.max_n == 1
    assert model.max_input_references == 0
