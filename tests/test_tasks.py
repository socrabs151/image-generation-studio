"""Task running and cancellation, without Qt.

These are the rules the UI depends on when it hands work to a thread pool: what a
callable receives, what counts as a failure, and who may stop it.
"""

from __future__ import annotations

import functools

import pytest

from app.core.errors import CancelledError
from app.core.tasks import TaskOutcome, accepts_cancel_check, run_task


class TestTheResultIsReported:
    def test_a_returned_value_comes_back(self) -> None:
        outcome = run_task(lambda: "ready")

        assert outcome == TaskOutcome(result="ready")
        assert outcome.failed is False
        assert outcome.error is None

    def test_none_is_a_result_and_not_a_failure(self) -> None:
        """None must not be mistaken for 'nothing happened' or for an error."""
        outcome = run_task(lambda: None)

        assert outcome.failed is False
        assert outcome.result is None

    def test_arguments_reach_the_task_unchanged(self) -> None:
        def task(a, b, *, c):
            return a + b + c

        outcome = run_task(task, (1, 2), {"c": 3})

        assert outcome.result == 6


class TestFailuresBecomeMessages:
    def test_an_exception_becomes_a_message(self) -> None:
        outcome = run_task(lambda: (_ for _ in ()).throw(RuntimeError("the disk is full")))

        assert outcome.failed is True
        assert outcome.error == "the disk is full"
        assert outcome.result is None

    def test_an_application_error_keeps_its_message(self) -> None:
        def cancelled() -> None:
            raise CancelledError()

        outcome = run_task(cancelled)

        assert outcome.failed is True
        assert outcome.error is not None
        assert "cancel" in outcome.error.lower()

    def test_a_keyboard_interrupt_is_not_swallowed(self) -> None:
        """A Ctrl+C must stop the program, not become a status message."""

        def interrupted() -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            run_task(interrupted)


class TestCooperativeCancellation:
    def test_a_task_that_asked_for_it_receives_the_callback(self) -> None:
        seen: list[object] = []

        def task(cancel_check):
            seen.append(cancel_check)
            return "done"

        run_task(task, is_cancelled=lambda: False)

        assert len(seen) == 1
        assert callable(seen[0])
        assert seen[0]() is False

    def test_the_callback_reports_the_request(self) -> None:
        state = {"cancelled": False}

        def task(cancel_check):
            return cancel_check()

        outcome = run_task(task, is_cancelled=lambda: state["cancelled"])

        assert outcome.result is False

        state["cancelled"] = True
        outcome = run_task(task, is_cancelled=lambda: state["cancelled"])

        assert outcome.result is True

    def test_a_task_that_did_not_ask_is_not_given_it(self) -> None:
        """Passing an unexpected keyword would break an ordinary function."""

        def task(a):
            return a

        outcome = run_task(task, (1,))

        assert outcome.result == 1

    def test_a_task_without_a_worker_still_gets_a_working_callback(self) -> None:
        """Called outside a worker, cancellation must not raise ``NameError``."""

        def task(cancel_check):
            return cancel_check()

        outcome = run_task(task)

        assert outcome.result is False

    def test_a_task_that_cancels_itself_reports_the_cancellation(self) -> None:
        def task(cancel_check):
            raise CancelledError()

        outcome = run_task(task, is_cancelled=lambda: True)

        assert outcome.failed is True
        assert outcome.error is not None


class TestSignatureDetection:
    def test_a_plain_function_is_detected(self) -> None:
        def task(cancel_check):
            return None

        assert accepts_cancel_check(task) is True

    def test_a_method_is_detected(self) -> None:
        class Service:
            def work(self, cancel_check):
                return None

        assert accepts_cancel_check(Service().work) is True

    def test_a_wrapped_function_is_detected(self) -> None:
        def task(cancel_check):
            return None

        assert accepts_cancel_check(functools.partial(task)) is True

    def test_a_function_without_it_is_not(self) -> None:
        def task(value):
            return value

        assert accepts_cancel_check(task) is False

    def test_a_callable_without_a_signature_does_not_explode(self) -> None:
        """Some builtins have no signature; the answer is 'cannot cancel'."""
        assert accepts_cancel_check(print) is False
