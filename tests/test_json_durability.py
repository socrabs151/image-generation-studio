"""B11: the bytes must reach the disk, and the old version must stay reachable."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.json_file import read_json, write_json_atomic


class TestBackup:
    def test_the_previous_version_is_kept(self, tmp_path: Path) -> None:
        target = tmp_path / "history.json"
        write_json_atomic(target, {"generation": 1})
        write_json_atomic(target, {"generation": 2})

        backup = target.with_name(target.name + ".bak")
        assert backup.exists()
        assert json.loads(backup.read_text(encoding="utf-8")) == {"generation": 1}
        assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 2}

    def test_only_one_backup_is_kept(self, tmp_path: Path) -> None:
        target = tmp_path / "history.json"
        for generation in range(1, 5):
            write_json_atomic(target, {"generation": generation})

        backups = list(tmp_path.glob("*.bak"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == {"generation": 3}

    def test_the_first_write_creates_no_backup(self, tmp_path: Path) -> None:
        target = tmp_path / "settings.json"

        write_json_atomic(target, {"theme": "dark"})

        assert not target.with_name(target.name + ".bak").exists()

    def test_the_reader_ignores_the_backup(self, tmp_path: Path) -> None:
        """A stray file next to the data must not be mistaken for it."""
        target = tmp_path / "settings.json"
        write_json_atomic(target, {"theme": "dark"})
        write_json_atomic(target, {"theme": "light"})

        assert read_json(target, "settings") == {"theme": "light"}


class TestDurability:
    def test_no_temporary_file_survives(self, tmp_path: Path) -> None:
        target = tmp_path / "history.json"

        write_json_atomic(target, {"a": 1})

        assert sorted(p.name for p in tmp_path.iterdir()) == ["history.json"]

    def test_a_failing_rename_leaves_the_old_file_intact(self, tmp_path: Path) -> None:
        """The point of the temporary file: the old data is never half-overwritten."""
        import app.services.json_file as module

        target = tmp_path / "history.json"
        write_json_atomic(target, {"generation": 1})

        real = module.os.replace

        def failing(src, dst, *args, **kwargs):
            if str(dst) == str(target):
                raise OSError("Access is denied")
            return real(src, dst, *args, **kwargs)

        module.os.replace = failing
        try:
            write_json_atomic(target, {"generation": 2})
        except OSError:
            pass
        finally:
            module.os.replace = real

        assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 1}
        assert not list(tmp_path.glob("*.tmp"))

    def test_a_backup_failure_does_not_stop_the_write(self, tmp_path: Path) -> None:
        import app.services.json_file as module

        target = tmp_path / "history.json"
        write_json_atomic(target, {"generation": 1})

        real = module.shutil.copy2

        def failing(*args, **kwargs):
            raise OSError("no space for a backup")

        module.shutil.copy2 = failing
        try:
            write_json_atomic(target, {"generation": 2})
        finally:
            module.shutil.copy2 = real

        assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 2}


class TestFsyncIsCalled:
    """The effect of fsync only shows up on a real power cut.

    What can be pinned from here is that the write asks for it: the bytes are
    flushed before the rename, and the directory is flushed after it. Without
    this, removing the calls changes nothing a test can see.
    """

    def test_the_data_is_synced_before_the_rename(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        import app.services.json_file as module

        events: list[str] = []
        real_fsync = module.os.fsync
        real_replace = module.os.replace

        def spy_fsync(fd):
            events.append("fsync")
            return real_fsync(fd)

        def spy_replace(src, dst, *args, **kwargs):
            events.append(f"replace:{Path(dst).name}")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(module.os, "fsync", spy_fsync, raising=False)  # type: ignore[attr-defined]
        monkeypatch.setattr(module.os, "replace", spy_replace, raising=False)  # type: ignore[attr-defined]

        write_json_atomic(tmp_path / "history.json", {"a": 1})

        assert "fsync" in events
        assert events.index("fsync") < events.index("replace:history.json"), (
            "the bytes must be on the disk before the name points at them"
        )

    def test_the_directory_is_synced_after_the_rename(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        import app.services.json_file as module

        events: list[str] = []
        real_fsync = module.os.fsync
        real_replace = module.os.replace

        def spy_fsync(fd):
            events.append("fsync")
            return real_fsync(fd)

        def spy_replace(src, dst, *args, **kwargs):
            events.append(f"replace:{Path(dst).name}")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(module.os, "fsync", spy_fsync, raising=False)  # type: ignore[attr-defined]
        monkeypatch.setattr(module.os, "replace", spy_replace, raising=False)  # type: ignore[attr-defined]

        write_json_atomic(tmp_path / "settings.json", {"a": 1})

        import os

        if os.name == "nt":
            # Windows cannot sync a directory handle; the data sync above is
            # what there is to check on this platform.
            assert "fsync" in events
        else:
            assert events[-1].startswith("fsync"), "the rename itself must be synced too"
