"""D5: an expired image link is reported as itself."""

from __future__ import annotations

import pytest
import requests

import app.providers.polza as polza
from app.core.errors import NetworkError, ProviderError
from app.providers.polza import PolzaProvider

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


class _Response:
    def __init__(self, status: int, content: bytes = b"", content_type: str = "image/png") -> None:
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def _download(response: _Response | Exception):
    provider = PolzaProvider("key")
    if isinstance(response, Exception):
        def boom(url, headers=None, timeout=None):
            raise response

        provider_session = boom
    else:
        def provider_session(url, headers=None, timeout=None):
            return response

    original = requests.get
    requests.get = provider_session  # type: ignore[assignment]
    try:
        return provider._download("https://cdn.example/image.png")
    finally:
        requests.get = original  # type: ignore[assignment]


@pytest.mark.parametrize("status", [403, 404, 410])
def test_an_expired_link_is_not_a_network_problem(status: int) -> None:
    with pytest.raises(ProviderError) as caught:
        _download(_Response(status))

    message = str(caught.value)
    assert "expired" in message
    assert str(status) in message
    assert "paid" in message, "the user must understand the money is already spent"


def test_a_transport_failure_is_still_a_network_problem() -> None:
    with pytest.raises(NetworkError):
        _download(requests.ConnectionError("no route to host"))


def test_a_server_error_is_still_a_network_problem() -> None:
    with pytest.raises(NetworkError):
        _download(_Response(500))


def test_a_page_instead_of_an_image_is_refused() -> None:
    with pytest.raises(ProviderError) as caught:
        _download(_Response(200, b"<html>maintenance</html>", "text/html"))

    assert "text/html" in str(caught.value)


def test_a_normal_picture_comes_through() -> None:
    image = _download(_Response(200, PNG.encode()))

    assert image.data == PNG.encode()
    assert image.media_type == "image/png"


def test_a_huge_body_is_refused() -> None:
    with pytest.raises(ProviderError):
        _download(_Response(200, b"\x00" * (polza.MAX_IMAGE_BYTES + 1)))


def test_no_content_type_is_not_treated_as_a_refusal() -> None:
    """Some storages send nothing; the bytes still decide."""
    image = _download(_Response(200, PNG.encode(), content_type=""))

    assert image.data == PNG.encode()
