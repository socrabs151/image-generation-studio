"""Running a background task, without Qt.

The rules that decide what happens to a task — whether it gets a cancellation
callback, and what its failure looks like — are not Qt's business. They live
here so they can be tested on a machine that has no Qt, which is exactly what CI
does: it runs the whole suite with PySide6 uninstalled.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """What a task produced: a result, or a message describing the failure."""

    result: Any = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


def accepts_cancel_check(function: Callable[..., Any]) -> bool:
    """Whether ``function`` declares a ``cancel_check`` parameter.

    Only such a function can be cancelled cooperatively; the others are run to
    the end.
    """
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        # Some callables (a C function, a partial of one) have no signature.
        return False
    return "cancel_check" in signature.parameters


def run_task(
    function: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> TaskOutcome:
    """Call ``function`` and turn whatever happens into a :class:`TaskOutcome`.

    Every failure becomes a message rather than an exception: a worker runs away
    from the code that started it, and a traceback there is useless to both the
    user and the log. A task that wants to be cancellable is given the callback;
    whether it honours it is up to the task.
    """
    call_kwargs = dict(kwargs or {})
    if accepts_cancel_check(function):
        call_kwargs["cancel_check"] = is_cancelled if is_cancelled is not None else _never
    try:
        return TaskOutcome(result=function(*args, **call_kwargs))
    except Exception as exc:  # noqa: BLE001 - reported to the UI as a message
        return TaskOutcome(error=str(exc))


def _never() -> bool:
    """A cancellation callback for a worker that can never be cancelled."""
    return False
