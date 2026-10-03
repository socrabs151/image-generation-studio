"""A13: a flaky status poll must not throw away a paid task."""

from __future__ import annotations

import pytest

import app.providers.polza as polza
from app.core.errors import NetworkError, ProviderError, ProviderTimeoutError
from app.providers.polza import Deadline, PolzaProvider

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


class _Flaky:
    """A media endpoint that fails a few times before answering."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.asked = 0

    def _get(self, url: str, timeout: int) -> dict:
        index = min(self.asked, len(self.answers) - 1)
        self.asked += 1
        answer = self.answers[index]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _provider(answers: list):
    flaky = _Flaky(answers)
    provider = PolzaProvider("key")
    provider._get = flaky._get  # type: ignore[method-assign]
    return provider, flaky


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(polza, "POLL_INTERVAL", 0.0)
    monkeypatch.setattr(polza, "POLL_RETRY_DELAY", 0.0)


class TestAHiccupDoesNotKillTheTask:
    def test_one_bad_gateway_is_retried(self) -> None:
        provider, flaky = _provider(
            [ProviderError("502 Bad Gateway"), {"status": "completed", "data": []}]
        )

        payload = provider._await_media("task-1", Deadline(60), None)

        assert payload["status"] == "completed"
        assert flaky.asked == 2

    def test_a_network_drop_is_retried(self) -> None:
        provider, flaky = _provider(
            [NetworkError("connection reset"), {"status": "completed", "data": []}]
        )

        assert provider._await_media("task-1", Deadline(60), None)["status"] == "completed"
        assert flaky.asked == 2

    def test_several_hiccups_in_a_row_are_survived(self) -> None:
        provider, flaky = _provider(
            [
                ProviderError("503"),
                NetworkError("timeout"),
                ProviderError("429 Too Many Requests"),
                {"status": "completed", "data": []},
            ]
        )

        assert provider._await_media("task-1", Deadline(60), None)["status"] == "completed"
        assert flaky.asked == 4

    def test_the_counter_resets_after_a_good_answer(self) -> None:
        """Three failures, one success, three more failures — still not given up."""
        answers = [ProviderError("502"), ProviderError("502"), ProviderError("502")]
        answers.append({"status": "processing"})
        answers.extend([ProviderError("502")] * 3)
        answers.append({"status": "completed", "data": []})
        provider, flaky = _provider(answers)

        assert provider._await_media("task-1", Deadline(60), None)["status"] == "completed"
        assert flaky.asked == 8


class TestGivingUp:
    def test_too_many_failures_stop_the_polling(self) -> None:
        provider, flaky = _provider([ProviderError("502 Bad Gateway")])

        with pytest.raises(ProviderError) as caught:
            provider._await_media("task-42", Deadline(60), None)

        assert flaky.asked == polza.POLL_RETRIES + 1
        message = str(caught.value)
        assert "task-42" in message, "the task id is the only way back to the picture"
        assert "may be billed" in message

    def test_the_last_reason_is_reported(self) -> None:
        provider, _ = _provider([NetworkError("connection reset by peer")])

        with pytest.raises(ProviderError) as caught:
            provider._await_media("task-1", Deadline(60), None)

        assert "connection reset by peer" in str(caught.value)

    def test_an_expired_budget_does_not_ask_at_all(self) -> None:
        """No time left means no time to retry, and no reason to ask once more."""
        provider, flaky = _provider([ProviderError("502")])

        with pytest.raises(ProviderTimeoutError):
            provider._await_media("task-1", Deadline(0, minimum=0), None)

        assert flaky.asked == 0


class TestThePostIsStillNotRetried:
    def test_starting_a_task_is_never_repeated(self) -> None:
        """Sending the request twice would charge twice."""
        source = pathlib_read()

        assert "requests.post" in source
        post_calls = [line for line in source.splitlines() if "requests.post" in line]
        assert len(post_calls) == 1, "there must be exactly one place that starts a task"


def pathlib_read() -> str:
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "app" / "providers" / "polza.py"
    return source.read_text(encoding="utf-8")
