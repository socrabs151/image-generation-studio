"""Tests for the vendor documentation downloader.

The network is stubbed out: only the index parsing, file naming and the
skip/filter/force behaviour are exercised.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import docs_sync
from app.services.docs_sync import (
    SOURCES,
    FetchResult,
    fetch_docs,
    get_source,
    has_docs,
    parse_index,
    select_pages,
    slugify,
    source_ids,
)

INDEX = """
# AITUNNEL

- Base URL: https://api.aitunnel.ru/v1

## Документация

- [Введение](https://example.com/docs.md): base URL
- [Баланс и оплата](https://example.com/docs/payments.md): как пополнить
- [Вызов функций (Tool Calling)](https://example.com/docs/tools.md): пример
- [Jev: решения вместо текста](https://example.com/docs/jev.md): Jev
"""


def test_parse_index_ignores_prose_and_headers() -> None:
    pages = parse_index(INDEX)

    assert [page.title for page in pages] == [
        "Введение",
        "Баланс и оплата",
        "Вызов функций (Tool Calling)",
        "Jev: решения вместо текста",
    ]
    assert pages[0].url == "https://example.com/docs.md"


def test_slugify_produces_windows_safe_names() -> None:
    assert slugify("Введение") == "Введение"
    assert slugify("Вызов функций (Tool Calling)") == "Вызов-функций-Tool-Calling"
    assert slugify("Jev: решения вместо текста") == "Jev-решения-вместо-текста"
    assert slugify("///") == "page"


def test_sources_cover_both_aggregators() -> None:
    assert set(source_ids()) == {"aitunnel", "polzaai"}
    assert get_source("polzaai").skip == 8
    assert get_source("aitunnel").index_url.endswith("llms.txt")
    with pytest.raises(KeyError):
        get_source("nope")


def test_select_pages_applies_skip_filter_and_limit() -> None:
    source = get_source("aitunnel")
    pages = parse_index(INDEX)

    assert len(select_pages(source, pages, skip=0)) == 4
    assert len(select_pages(source, pages, skip=2)) == 2
    assert [p.title for p in select_pages(source, pages, only=["jev"])] == [
        "Jev: решения вместо текста"
    ]
    assert len(select_pages(source, pages, limit=1)) == 1


def _stub(monkeypatch: pytest.MonkeyPatch, existing: set[str] | None = None) -> list[str]:
    """Serve the index and page bodies from memory; return the saved file names."""
    existing = existing or set()
    saved: list[str] = []

    def fake_get(url: str, timeout: float, retries: int) -> str:
        if url.endswith("llms.txt"):
            return INDEX
        return f"# page\n\nsource: {url}\n"

    def real_get_text(url: str, timeout: float, retries: int) -> str:
        text = fake_get(url, timeout, retries)
        name = url.rsplit("/", 1)[-1].replace(".md", "")
        if name in existing:
            raise AssertionError(f"повторная загрузка {name}")
        return text

    monkeypatch.setattr(docs_sync, "_get_text", real_get_text)
    monkeypatch.setattr(docs_sync, "_sleep", lambda _seconds: None)
    return saved


def test_fetch_docs_writes_numbered_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub(monkeypatch)
    result = fetch_docs(get_source("aitunnel"), docs_dir=tmp_path)

    assert result.saved == 4
    assert result.failed == 0
    assert result.ok is True
    files = sorted(p.name for p in (tmp_path / "aitunnel").glob("*.md"))
    assert files == [
        "01_Введение.md",
        "02_Баланс-и-оплата.md",
        "03_Вызов-функций-Tool-Calling.md",
        "04_Jev-решения-вместо-текста.md",
    ]
    assert "source: https://example.com/docs.md" in (tmp_path / "aitunnel" / files[0]).read_text(
        encoding="utf-8"
    )


def test_fetch_docs_keeps_existing_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "aitunnel"
    target.mkdir(parents=True)
    (target / "01_Введение.md").write_text("старое", encoding="utf-8")
    _stub(monkeypatch, existing={"docs"})

    result = fetch_docs(get_source("aitunnel"), docs_dir=tmp_path)

    assert result.skipped == 1
    assert result.saved == 3
    assert (target / "01_Введение.md").read_text(encoding="utf-8") == "старое"


def test_force_overwrites_existing_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "aitunnel"
    target.mkdir(parents=True)
    (target / "01_Введение.md").write_text("старое", encoding="utf-8")
    _stub(monkeypatch)

    result = fetch_docs(get_source("aitunnel"), docs_dir=tmp_path, force=True)

    assert result.saved == 4
    assert (target / "01_Введение.md").read_text(encoding="utf-8") != "старое"


def test_progress_is_reported_per_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub(monkeypatch)
    lines: list[str] = []

    fetch_docs(get_source("aitunnel"), docs_dir=tmp_path, progress=lines.append)

    assert len(lines) == 4
    assert lines[0].startswith("1/4 ")


def test_cancel_stops_early(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub(monkeypatch)
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    result = fetch_docs(get_source("aitunnel"), docs_dir=tmp_path, cancel_check=cancel)

    assert result.cancelled is True
    assert result.saved == 2
    assert result.total == 4


def test_has_docs_detects_a_populated_folder(tmp_path: Path) -> None:
    source = get_source("aitunnel")
    assert has_docs(source, tmp_path) is False

    folder = tmp_path / "aitunnel"
    folder.mkdir(parents=True)
    assert has_docs(source, tmp_path) is False

    (folder / "01.md").write_text("x", encoding="utf-8")
    assert has_docs(source, tmp_path) is True


def test_failed_page_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_get(url: str, timeout: float, retries: int) -> str:
        if url.endswith("llms.txt"):
            return INDEX
        if "payments" in url:
            raise RuntimeError(f"failed to fetch {url}: 500")
        return "# page\n"

    monkeypatch.setattr(docs_sync, "_get_text", fake_get)
    monkeypatch.setattr(docs_sync, "_sleep", lambda _seconds: None)

    result = fetch_docs(get_source("aitunnel"), docs_dir=tmp_path)

    assert result.failed == 1
    assert result.ok is False
    assert any("Баланс" in message for message in result.errors)
    assert result.saved == 3


def test_result_summary_mentions_state() -> None:
    assert FetchResult("aitunnel", saved=2, total=5).summary().startswith("done:")
    assert FetchResult("aitunnel", saved=1, total=5, cancelled=True).summary().startswith(
        "cancelled:"
    )


def test_every_source_has_a_distinct_folder() -> None:
    folders = [source.provider_id for source in SOURCES.values()]
    assert len(folders) == len(set(folders))
