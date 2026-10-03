"""The Polza media polling loop.

Before this there was no way to repeat the loop in a test: it slept four seconds
between asks. Setting ``POLL_INTERVAL`` to zero removes the wait without touching
``time.sleep``, and a timeout of zero makes the deadline condition true on the
first pass — so no clock is faked anywhere.
"""

from __future__ import annotations

import pytest

import app.providers.polza as polza
from app.core.errors import CancelledError, ProviderError, ProviderTimeoutError
from app.providers.polza import PolzaProvider


class _Polling:
    """A provider whose media endpoint answers with a scripted sequence."""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.asked: list[str] = []
        self.timeouts: list[int] = []

    def _get(self, url: str, timeout: int) -> dict:
        self.asked.append(url)
        self.timeouts.append(timeout)
        return self.payloads[min(len(self.asked) - 1, len(self.payloads) - 1)]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(polza, "POLL_INTERVAL", 0.0)


def _provider(payloads: list[dict]) -> tuple[PolzaProvider, _Polling]:
    polling = _Polling(payloads)
    provider = PolzaProvider.__new__(PolzaProvider)
    provider._get = polling._get  # type: ignore[method-assign]
    return provider, polling


def _await(provider: PolzaProvider, *, timeout: int = 180, cancel=None):
    return provider._await_media("task-1", timeout, cancel)


class TestASuccessfulTask:
    def test_a_completed_task_is_returned_at_once(self) -> None:
        provider, polling = _provider([{"status": "completed", "data": []}])

        result = _await(provider)

        assert result == {"status": "completed", "data": []}
        assert polling.asked == ["https://polza.ai/api/v1/media/task-1"]

    def test_a_task_is_asked_about_until_it_finishes(self) -> None:
        provider, polling = _provider(
            [
                {"status": "processing"},
                {"status": "processing"},
                {"status": "completed", "data": [{"b64_json": "eA=="}]},
            ]
        )

        result = _await(provider)

        assert result["status"] == "completed"
        assert len(polling.asked) == 3, "the loop gave up early"

    def test_the_poll_interval_bounds_the_request_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A poll that hangs must not outlive the interval it belongs to.

        The task answers at once, so the wait between asks never happens and the
        interval can be a real number here.
        """
        monkeypatch.setattr(polza, "POLL_INTERVAL", 1.5)
        provider, polling = _provider([{"status": "completed"}])

        _await(provider)

        assert polling.timeouts == [6]

    def test_the_loop_waits_between_asks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Asking as fast as the network answers would hammer the aggregator."""
        import time

        monkeypatch.setattr(polza, "POLL_INTERVAL", 0.4)
        provider, polling = _provider([{"status": "processing"}, {"status": "completed"}])

        started = time.monotonic()
        _await(provider)
        elapsed = time.monotonic() - started

        assert len(polling.asked) == 2
        # time.sleep may return a little early on Windows, so the check is a
        # fraction of the interval. Without the wait two asks take about a
        # millisecond, which this still rules out.
        assert elapsed >= 0.8 * polza.POLL_INTERVAL, (
            f"the loop asked twice in {elapsed:.3f} s without waiting"
        )

    def test_an_unknown_status_keeps_waiting(self) -> None:
        provider, polling = _provider(
            [{"status": "queued"}, {"status": "in_progress"}, {"status": "completed"}]
        )

        assert _await(provider)["status"] == "completed"
        assert len(polling.asked) == 3


class TestAFailedTask:
    @pytest.mark.parametrize("status", ["failed", "cancelled"])
    def test_a_terminal_failure_raises(self, status: str) -> None:
        provider, _ = _provider([{"status": status, "error": {"message": "no money"}}])

        with pytest.raises(ProviderError) as caught:
            _await(provider)

        assert "no money" in str(caught.value)

    def test_a_failure_stops_the_polling_immediately(self) -> None:
        provider, polling = _provider([{"status": "failed"}])

        with pytest.raises(ProviderError):
            _await(provider)

        assert len(polling.asked) == 1, "a failed task must not be asked about again"


class TestATimeout:
    def test_a_task_that_never_finishes_times_out(self) -> None:
        provider, _ = _provider([{"status": "processing"}])

        with pytest.raises(ProviderTimeoutError) as caught:
            _await(provider, timeout=0)

        assert "task-1" in str(caught.value), "the task id must be in the message"

    def test_a_timeout_names_the_wait_it_gave_up_after(self) -> None:
        provider, _ = _provider([{"status": "processing"}])

        with pytest.raises(ProviderTimeoutError) as caught:
            _await(provider, timeout=0)

        assert "within 0 s" in str(caught.value)


class TestCancellation:
    def test_a_cancelled_poll_stops_before_asking(self) -> None:
        provider, polling = _provider([{"status": "completed"}])

        with pytest.raises(CancelledError):
            _await(provider, cancel=lambda: True)

        assert polling.asked == [], "nothing may be asked after the user said stop"

    def test_cancellation_is_checked_between_asks(self) -> None:
        answers = iter([False, False, True])
        provider, polling = _provider([{"status": "processing"}, {"status": "processing"}])

        with pytest.raises(CancelledError):
            _await(provider, cancel=lambda: next(answers))

        assert len(polling.asked) == 2, "the loop must notice the cancellation"

    def test_a_completed_task_is_not_blocked_by_a_late_cancellation(self) -> None:
        """The answer arrived; a stop pressed after it must not throw away the paid image."""
        provider, _ = _provider([{"status": "completed", "data": [{"b64_json": "eA=="}]}])

        result = _await(provider, cancel=lambda: False)

        assert result["status"] == "completed"


class TestTheWholeRequest:
    def test_a_queued_task_is_polled_to_the_end(self) -> None:
        """The public path: the answer is a task id, the images are in its result."""
        provider, polling = _provider(
            [
                {"id": "task-1", "status": "queued"},
                {"id": "task-1", "status": "processing"},
                {"id": "task-1", "status": "completed", "data": [{"b64_json": "eA=="}]},
            ]
        )

        result = provider._await_media("task-1", 180, None)

        assert len(polling.asked) == 3
        assert result["data"][0]["b64_json"] == "eA=="
