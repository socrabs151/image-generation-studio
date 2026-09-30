"""Decisions taken before a paid request is started.

Qt-free on purpose: the CI runner has no ``libEGL``, and a test that imports Qt
fails at collection. The window keeps the widgets, these functions keep the
rules, so the rules can be tested.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

#: The name of the file used to find out whether a folder accepts a write.
PROBE_NAME = ".write-test"


class WorkerSlot:
    """One background slot shared by the catalog, the balance and a generation.

    All three kinds of work go through a single slot, which is why a helper
    starting during a generation used to replace the reference to it: the
    helper finished first, cleared the slot, and re-enabled Generate while the
    generation was still running. A second press then started a second paid
    request.

    The slot now only answers whether a task may start, and remembers whether
    the task that finished is the one allowed to release the Generate button.
    """

    def __init__(self) -> None:
        self._busy = False
        self._generation_runs = False

    @property
    def busy(self) -> bool:
        """Whether any background task is running."""
        return self._busy

    @property
    def generation_running(self) -> bool:
        """Whether a generation, as opposed to a helper, is running."""
        return self._generation_runs

    def may_start(self) -> bool:
        """Whether a task may start now. Helpers ask this too, and are refused."""
        return not self._busy

    def start(self, is_generation: bool) -> None:
        self._busy = True
        self._generation_runs = is_generation

    def finish(self) -> bool:
        """Release the slot; report whether Generate may be re-enabled.

        Only a generation decides that. A helper finishing while a generation
        runs is impossible now, because helpers may not start during one, but
        the answer stays False rather than depending on that.
        """
        was_generation = self._generation_runs
        self._busy = False
        self._generation_runs = False
        return was_generation


def save_folder_problem(folder: str | os.PathLike[str]) -> str | None:
    """Why results could not be written to ``folder``, or ``None`` if they can.

    Asked before the request is sent, not after the answer: the folder used to be
    touched only once the aggregator had already charged for the work. A write
    probe is the only honest check for a full disk, and it is removed again.
    """
    target = Path(folder)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        return f"{folder} is a file, not a folder."
    except NotADirectoryError:
        return f"A part of {folder} is a file, not a folder."
    except OSError as exc:
        return f"Cannot create {folder}: {exc.strerror or exc}."

    probe = target / PROBE_NAME
    try:
        probe.write_bytes(b"")
    except OSError as exc:
        if exc.errno == errno.EACCES:
            return f"No write access to {folder}."
        if exc.errno == errno.ENOSPC:
            return f"There is no space left on the disk holding {folder}."
        return f"Cannot write to {folder}: {exc.strerror or exc}."
    finally:
        probe.unlink(missing_ok=True)
    return None
