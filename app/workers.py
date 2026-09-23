"""Background tasks executed outside the UI thread.

A small generic worker wraps any callable and reports its outcome through Qt
signals, which are delivered in the UI thread. Network and file operations must run
through these workers so the interface never blocks.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    """Signals emitted by :class:`FunctionWorker`."""

    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    """Run ``function(*args, **kwargs)`` in a thread-pool thread.

    If the callable declares a ``cancel_check`` parameter, the worker passes a
    callable returning :meth:`is_cancelled`, allowing cooperative cancellation.
    """

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False
        self._accepts_cancel = "cancel_check" in inspect.signature(function).parameters

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    @Slot()
    def run(self) -> None:
        """Execute the callable and emit the result signals."""
        kwargs = dict(self._kwargs)
        if self._accepts_cancel:
            kwargs["cancel_check"] = self.is_cancelled
        try:
            result = self._function(*self._args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the UI as a message
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(result)
