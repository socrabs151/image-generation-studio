"""Background tasks executed outside the UI thread.

A small generic worker wraps any callable and reports its outcome through Qt
signals, which are delivered in the UI thread. Network and file operations must run
through these workers so the interface never blocks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.core.tasks import run_task


class WorkerSignals(QObject):
    """Signals emitted by :class:`FunctionWorker`."""

    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    """Run ``function(*args, **kwargs)`` in a thread-pool thread and report it.

    The worker is the Qt half only: what a task receives, how a failure is turned
    into a message and who may cancel it are decided in :mod:`app.core.tasks`,
    which carries no Qt and can be tested without it.
    """

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    @Slot()
    def run(self) -> None:
        """Execute the callable and emit the result signals."""
        outcome = run_task(self._function, self._args, self._kwargs, self.is_cancelled)
        if outcome.failed:
            self.signals.failed.emit(outcome.error)
            return
        self.signals.finished.emit(outcome.result)
