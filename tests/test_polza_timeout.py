"""The timeout budget: one number for the whole request, not one per task."""

from __future__ import annotations

import time

import pytest

import app.providers.polza as polza
from app.core.errors import ProviderTimeoutError
from app.core.models import GenerationRequest
from app.providers.polza import Deadline, PolzaProvider

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


class _Recorder:
    """A provider whose HTTP calls answer instantly and record their timeouts."""

    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = list(statuses or ["completed"])
        self.timeouts: list[int] = []
        self.posts = 0
        self._polls = 0

    def _post(self, url: str, body: dict, timeout: int) -> dict:
        self.posts += 1
        self.timeouts.append(timeout)
        return {"id": "task-1", "status": "queued"}

    def instant_post(self, url: str, body: dict, timeout: int) -> dict:
        """A POST that answers at once with the picture, still recording the timeout."""
        self.posts += 1
        self.timeouts.append(timeout)
        return {"status": "completed", "data": [{"b64_json": PNG}]}

    def _get(self, url: str, timeout: int) -> dict:
        index = min(self._polls, len(self.statuses) - 1)
        self._polls += 1
        self.timeouts.append(timeout)
        return {"status": self.statuses[index], "data": [{"b64_json": PNG}]}


def _provider(statuses: list[str] | None = None):
    recorder = _Recorder(statuses)
    provider = PolzaProvider("key")
    provider._post = recorder._post  # type: ignore[method-assign]
    provider._get = recorder._get  # type: ignore[method-assign]
    return provider, recorder


def _request(n: int = 1) -> GenerationRequest:
    return GenerationRequest(
        provider_id="polza",
        model="seedream-4",
        prompt="a cat",
        n=n,
    )


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(polza, "POLL_INTERVAL", 0.0)


class TestTheDeadlineItself:
    def test_a_fresh_deadline_has_its_budget(self) -> None:
        deadline = Deadline(30)

        assert deadline.total == 30
        assert 29 <= deadline.remaining() <= 30
        assert deadline.expired() is False

    def test_the_budget_is_spent_not_restarted(self) -> None:
        deadline = Deadline(0.2, minimum=0.0)
        time.sleep(0.25)

        assert deadline.remaining() == 0.0
        assert deadline.expired() is True

    def test_a_tiny_budget_is_raised_to_the_floor(self) -> None:
        """Cutting a task off before the aggregator answered produces nothing."""
        assert Deadline(0).total == polza.MIN_TASK_TIMEOUT
        assert Deadline(2).total == polza.MIN_TASK_TIMEOUT

    def test_a_single_request_gets_at_least_a_second(self) -> None:
        """A fractional remainder must not become timeout=0 and hang forever."""
        assert Deadline(1.5, minimum=0).for_request() == 1
        assert Deadline(90, minimum=0).for_request() >= 88


class TestTheBudgetIsSharedByPostAndPolling:
    def test_the_polling_gets_what_the_post_left(self) -> None:
        provider, recorder = _provider()
        provider._post = lambda url, body, timeout: (  # type: ignore[method-assign]
            recorder.timeouts.append(timeout)
            or time.sleep(0.15)
            or {"id": "task-1", "status": "queued"}
        )

        provider._run_task(_request(), Deadline(1.0, minimum=0.5), None)

        assert recorder.timeouts[0] >= 1, "the POST got the whole budget"
        assert recorder.timeouts[-1] < recorder.timeouts[0] or recorder.timeouts[-1] <= 1

    def test_an_expired_budget_never_sends_anything(self) -> None:
        """Nothing is charged when there is no time left to try."""
        provider, recorder = _provider()

        with pytest.raises(ProviderTimeoutError):
            provider._run_task(_request(), Deadline(0, minimum=0), None)

        assert recorder.posts == 0


class TestTheBudgetIsSharedByTheBatch:
    def test_six_tasks_do_not_get_six_timeouts(self) -> None:
        provider, recorder = _provider()
        provider._post = recorder.instant_post  # type: ignore[method-assign]
        provider._result_from_media = lambda payload, model: _images()  # type: ignore[method-assign]

        provider.generate(_request(n=6), timeout=180)

        # 180 split six ways is 30 a task; the full 180 would be the old bug.
        assert recorder.posts == 6
        assert max(recorder.timeouts) <= 31, f"задача получила {max(recorder.timeouts)} с"

    def test_a_single_task_keeps_the_whole_timeout(self) -> None:
        provider, recorder = _provider()
        provider._post = recorder.instant_post  # type: ignore[method-assign]
        provider._result_from_media = lambda payload, model: _images()  # type: ignore[method-assign]

        provider.generate(_request(n=1), timeout=180)

        assert recorder.timeouts == [180]

    def test_the_batch_never_gets_less_than_the_floor(self) -> None:
        provider, recorder = _provider()
        provider._post = recorder.instant_post  # type: ignore[method-assign]
        provider._result_from_media = lambda payload, model: _images()  # type: ignore[method-assign]

        provider.generate(_request(n=6), timeout=15)

        assert min(recorder.timeouts) >= polza.MIN_TASK_TIMEOUT


def _images():
    from app.core.models import GeneratedImage, GenerationResult

    return GenerationResult(
        images=[GeneratedImage(data=b"\x89PNG", media_type="image/png")],
        cost_rub=1.0,
        balance=None,
        model="seedream-4",
    )
