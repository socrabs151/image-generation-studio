"""B7: a truncated page must not look downloaded, and one bad write is not fatal."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.docs_sync import DocsSource, fetch_docs, write_page


class _Response:
    def __init__(self, text: str) -> None:
        self._text = text
        self.status_code = 200

    @property
    def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        return None


# The same shape as a real llms.txt index: markdown links.
INDEX = """
# Polza.ai

## Документация

- [Введение](https://example.com/docs/one.md): первая
- [Баланс](https://example.com/docs/two.md): вторая
"""


class TestAtomicWrite:
    def test_the_page_is_written(self, tmp_path: Path) -> None:
        target = tmp_path / "page.md"

        write_page(target, "hello")

        assert target.read_bytes() == b"hello\r\n"

    def test_no_temporary_file_is_left_behind(self, tmp_path: Path) -> None:
        write_page(tmp_path / "page.md", "hello")

        assert [p.name for p in tmp_path.iterdir()] == ["page.md"]

    def test_a_failed_write_leaves_no_half_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A truncated file was worse than none: it looked downloaded forever."""
        target = tmp_path / "page.md"

        import app.services.docs_sync as module

        def exploding(*args, **kwargs):
            raise OSError("No space left on device")

        monkey = module.os.replace
        module.os.replace = exploding
        try:
            with pytest.raises(OSError):
                write_page(target, "hello")
        finally:
            module.os.replace = monkey

        assert not target.exists()
        assert list(tmp_path.iterdir()) == [], "a .part file survived"

    def test_an_existing_page_is_replaced_whole(self, tmp_path: Path) -> None:
        target = tmp_path / "page.md"
        target.write_text("old content", encoding="utf-8")

        write_page(target, "new content")

        assert target.read_bytes() == b"new content\r\n"


class TestFetch:
    def _source(self) -> DocsSource:
        return DocsSource(
            provider_id="polza",
            display_name="Polza.ai",
            index_url="https://example.com/llms.txt",
        )

    def _stub_get(self, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
        import app.services.docs_sync as module

        monkeypatch.setattr(
            module.requests, "get", lambda *a, **k: _Response(text), raising=False
        )

    def test_an_unwritable_page_does_not_stop_the_rest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_get(monkeypatch, INDEX)

        import app.services.docs_sync as module

        real = module.write_page
        calls = {"n": 0}

        def flaky(path: Path, content: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disk full")
            real(path, content)

        monkeypatch.setattr(module, "write_page", flaky)
        result = fetch_docs(self._source(), tmp_path, timeout=1)

        assert result.failed == 1
        assert result.saved == 1, "the second page was never tried"

    def test_a_runtime_error_on_a_page_is_still_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_get(monkeypatch, INDEX)

        import app.services.docs_sync as module

        def broken(path: Path, content: str) -> None:
            raise RuntimeError("bad page")

        monkeypatch.setattr(module, "write_page", broken)
        result = fetch_docs(self._source(), tmp_path, timeout=1)

        assert result.failed == 2
        assert result.saved == 0
        assert len(result.errors) == 2
