"""Tests for the rules applied before a paid request is started.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, and a test
that imports Qt fails at collection. The rules live in
:mod:`app.ui.request_rules` so they can be checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.request_rules import PROBE_NAME, WorkerSlot, save_folder_problem

# ---------- the shared worker slot ----------


def test_an_empty_slot_accepts_a_task() -> None:
    slot = WorkerSlot()
    assert slot.may_start() is True
    assert slot.busy is False


def test_a_generation_locks_the_slot() -> None:
    slot = WorkerSlot()
    slot.start(is_generation=True)

    assert slot.may_start() is False
    assert slot.busy is True
    assert slot.generation_running is True


def test_a_helper_is_refused_during_a_generation() -> None:
    """The defect: the balance check started during a generation and replaced
    the reference to it, so the button came back while the work was still
    running and a second press started a second paid request."""
    slot = WorkerSlot()
    slot.start(is_generation=True)

    assert slot.may_start() is False, "helpers must wait for the generation"


def test_finishing_a_generation_releases_generate() -> None:
    slot = WorkerSlot()
    slot.start(is_generation=True)

    assert slot.finish() is True, "a generation decides to re-enable Generate"
    assert slot.may_start() is True
    assert slot.generation_running is False


def test_finishing_a_helper_never_releases_generate() -> None:
    slot = WorkerSlot()
    slot.start(is_generation=False)

    assert slot.finish() is False, (
        "a helper finishing must not re-enable Generate: the user could press it "
        "again and start a second paid request"
    )
    assert slot.may_start() is True


def test_the_slot_can_be_reused_after_a_generation() -> None:
    slot = WorkerSlot()
    slot.start(is_generation=True)
    slot.finish()
    slot.start(is_generation=False)
    assert slot.may_start() is False
    slot.finish()
    assert slot.may_start() is True


def test_a_second_generation_cannot_start_while_one_runs() -> None:
    slot = WorkerSlot()
    slot.start(is_generation=True)
    assert slot.may_start() is False


# ---------- the save folder ----------


def test_a_normal_folder_is_accepted_and_created(tmp_path: Path) -> None:
    target = tmp_path / "new-folder"
    assert save_folder_problem(target) is None
    assert target.is_dir()


def test_a_deep_path_is_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    assert save_folder_problem(target) is None
    assert target.is_dir()


def test_the_write_probe_does_not_stay_behind(tmp_path: Path) -> None:
    save_folder_problem(tmp_path)
    assert list(tmp_path.iterdir()) == [], "the probe file has to be removed"


def test_an_existing_folder_is_accepted(tmp_path: Path) -> None:
    assert save_folder_problem(tmp_path) is None


def test_a_file_where_the_folder_should_be_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")

    problem = save_folder_problem(blocker)

    assert problem is not None
    assert "file" in problem.lower()


def test_a_file_inside_the_path_is_reported(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    problem = save_folder_problem(blocker / "images")

    assert problem is not None, "a file in the middle of the path must be caught"


def test_the_probe_name_is_not_a_collision(tmp_path: Path) -> None:
    """The probe has its own name and is removed, so it cannot be mistaken for
    a result or left behind by a crash."""
    assert PROBE_NAME.startswith(".")
    assert PROBE_NAME.endswith("-test")


def test_a_folder_that_cannot_be_created_is_reported(tmp_path: Path) -> None:
    # A path under a file cannot be created on any platform.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    assert save_folder_problem(blocker / "a" / "b") is not None


@pytest.mark.parametrize("name", ["", "   ", "\t", "\n"])
def test_an_empty_folder_name_is_reported(name: str) -> None:
    """A damaged settings file can leave the save folder empty.

    ``Path("")`` is ``Path(".")``, so without this check the probe would report
    "ok" and the results would land in whatever directory the app was started
    from, with no warning anywhere.
    """
    problem = save_folder_problem(name)
    assert problem is not None, f"{name!r} must not be accepted as a folder"
    assert "not set" in problem


def test_an_empty_folder_name_creates_nothing(tmp_path: Path, monkeypatch) -> None:
    """Not only is it refused, no file is left behind anywhere."""
    monkeypatch.chdir(tmp_path)

    save_folder_problem("")

    assert list(tmp_path.iterdir()) == []
