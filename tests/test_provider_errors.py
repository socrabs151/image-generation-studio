"""A14: the aggregator's own words reach the user."""

from __future__ import annotations

import pytest

from app.core.errors import (
    BadParameterError,
    ProviderBusyError,
    ProviderError,
    ProviderNotFoundError,
    ProviderTimeoutError,
)
from app.providers.base import raise_for_status
from app.providers.polza import PolzaProvider, _empty_result_message, _warnings_message


class TestAnEmptyResultExplainsItself:
    def _result(self, payload: dict):
        provider = PolzaProvider("key")
        provider._download = lambda url: None  # type: ignore[method-assign]
        return provider._result_from_media(payload, "seedream-4")

    def test_the_vendor_reason_is_passed_on(self) -> None:
        payload = {"status": "completed", "data": [], "error": {"message": "content filtered"}}

        with pytest.raises(ProviderError) as caught:
            self._result(payload)

        assert "content filtered" in str(caught.value)

    def test_a_plain_string_error_works_too(self) -> None:
        payload = {"data": [], "error": "the model is retired"}

        with pytest.raises(ProviderError) as caught:
            self._result(payload)

        assert "the model is retired" in str(caught.value)

    def test_a_detail_field_is_used_when_there_is_no_error(self) -> None:
        payload = {"data": [], "detail": "quota exhausted for this key"}

        with pytest.raises(ProviderError) as caught:
            self._result(payload)

        assert "quota exhausted" in str(caught.value)

    def test_an_explanationless_body_still_says_something_useful(self) -> None:
        with pytest.raises(ProviderError) as caught:
            self._result({"data": []})

        message = str(caught.value)
        assert "no images" in message
        assert "completed" in message

    def test_an_empty_result_is_not_a_configuration_error(self) -> None:
        """It used to be reported as a broken configuration, which it is not."""
        from app.core.errors import ConfigError

        with pytest.raises(ProviderError) as caught:
            self._result({"data": [], "error": {"message": "content filtered"}})

        assert not isinstance(caught.value, ConfigError), (
            "a vendor explanation is not a broken configuration"
        )

    def test_the_message_helper_survives_odd_bodies(self) -> None:
        assert _empty_result_message({}) == ""
        assert _empty_result_message({"error": 42}) == ""
        assert _empty_result_message({"error": {"message": ""}}) == ""
        assert _empty_result_message({"message": "  padded  "}) == "padded"

    def test_images_still_win_over_an_error_field(self) -> None:
        """A warning alongside pictures must not become a failure."""
        png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
            "IQAAAABJRU5ErkJggg=="
        )
        result = self._result({"data": [{"b64_json": png}], "error": {"message": "partial"}})

        assert len(result.images) == 1


class TestWarningsAreNotSwallowed:
    def test_warnings_are_collected(self) -> None:
        text = _warnings_message({"warnings": ["resolution ignored", "quality ignored"]})

        assert "resolution ignored" in text
        assert "quality ignored" in text

    def test_a_missing_warnings_field_is_fine(self) -> None:
        assert _warnings_message({}) == ""
        assert _warnings_message({"warnings": "not a list"}) == ""
        assert _warnings_message({"warnings": []}) == ""


class TestEveryStatusMeansSomething:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (400, BadParameterError),
            (401, Exception),
            (402, Exception),
            (403, Exception),
            (404, ProviderNotFoundError),
            (408, ProviderTimeoutError),
            (413, BadParameterError),
            (422, BadParameterError),
            (429, ProviderBusyError),
            (503, ProviderBusyError),
            (504, ProviderTimeoutError),
            (500, ProviderError),
            (502, ProviderError),
            (418, ProviderError),
        ],
    )
    def test_the_status_maps_to_its_own_error(self, status: int, expected: type) -> None:
        from app.core.errors import AuthenticationError, InsufficientFundsError

        if expected is Exception:
            expected = AuthenticationError if status in (401, 403) else InsufficientFundsError

        with pytest.raises(expected):
            raise_for_status(status)

    def test_a_busy_aggregator_is_not_a_bad_request(self) -> None:
        """429 and 503 are the two a retry can fix, so they must be tellable apart."""
        for status in (429, 503):
            with pytest.raises(ProviderBusyError):
                raise_for_status(status)

            assert not isinstance(
                ProviderBusyError("x"), BadParameterError
            ), "a busy aggregator is not our parameter's fault"

    def test_the_detail_from_the_aggregator_is_kept(self) -> None:
        with pytest.raises(ProviderError) as caught:
            raise_for_status(500, "upstream exploded")

        assert "upstream exploded" in str(caught.value)

    def test_the_status_is_kept_on_the_error(self) -> None:
        with pytest.raises(ProviderBusyError) as caught:
            raise_for_status(429, "slow down")

        assert caught.value.status_code == 429

    def test_a_status_without_detail_is_still_readable(self) -> None:
        with pytest.raises(ProviderNotFoundError) as caught:
            raise_for_status(404)

        assert "404" in str(caught.value)
