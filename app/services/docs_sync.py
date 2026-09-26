"""Download the vendor documentation of each aggregator.

The reference files under ``docs/<provider>/`` are not part of the repository, so a
fresh clone has none of them. Every provider publishes a machine-readable index
(``llms.txt``) that links to a Markdown version of each page; this service turns that
index into the local file tree the documentation window reads.

The module is deliberately free of Qt so the command-line script and the application
share the same code and the logic can be tested without a display.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.config import DOCS_DIR

USER_AGENT = "image-generation-studio/0.1"

# An index line looks like: - [Title](https://host/docs/page.md): Description
INDEX_LINE = re.compile(r"^-\s+\[(?P<title>[^]]+)\]\((?P<url>[^)]+)\)")
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
PAGE_SIZE = 100

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DocsSource:
    """Where the documentation of one aggregator can be downloaded from."""

    provider_id: str
    display_name: str
    index_url: str
    # Number of index entries to skip before the actual guide pages.
    skip: int = 0


@dataclass(frozen=True, slots=True)
class Page:
    """A single documentation page listed in a vendor index."""

    title: str
    url: str


@dataclass(slots=True)
class FetchResult:
    """Outcome of a documentation download."""

    provider_id: str
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether nothing failed."""
        return self.failed == 0

    def summary(self) -> str:
        """One-line description for the log."""
        state = "cancelled" if self.cancelled else "done"
        return (
            f"{state}: {self.saved} saved, {self.skipped} skipped, "
            f"{self.failed} failed of {self.total}"
        )


SOURCES: dict[str, DocsSource] = {
    "aitunnel": DocsSource(
        provider_id="aitunnel",
        display_name="AITUNNEL",
        index_url="https://aitunnel.ru/llms.txt",
    ),
    "polzaai": DocsSource(
        provider_id="polzaai",
        display_name="Polza.ai",
        index_url="https://polza.ai/docs/llms.txt",
        # The first entries of the index are landing and company pages, not guides.
        skip=8,
    ),
}


def source_ids() -> list[str]:
    """Ids of every provider with a documentation source."""
    return list(SOURCES)


def get_source(provider_id: str) -> DocsSource:
    """Return the source description for ``provider_id``."""
    try:
        return SOURCES[provider_id]
    except KeyError as exc:
        raise KeyError(f"Unknown documentation source: {provider_id}") from exc


def slugify(title: str) -> str:
    """Convert a page title into a file name stem.

    Parentheses are dropped, spaces become hyphens and characters that Windows
    forbids in file names are replaced with a hyphen.
    """
    text = title.replace("(", " ").replace(")", " ")
    text = ILLEGAL_CHARS.sub("-", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-.") or "page"


def parse_index(text: str) -> list[Page]:
    """Extract the page entries from an ``llms.txt`` index."""
    pages: list[Page] = []
    for line in text.splitlines():
        match = INDEX_LINE.match(line.strip())
        if match:
            pages.append(
                Page(title=match.group("title").strip(), url=match.group("url").strip())
            )
    return pages


def write_page(path: Path, content: str) -> None:
    """Write Markdown text as UTF-8 without BOM using Windows line endings."""
    text = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    with path.open("w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)


def has_docs(source: DocsSource, docs_dir: Path | str = DOCS_DIR) -> bool:
    """Whether any Markdown file of this provider is already present."""
    folder = Path(docs_dir) / source.provider_id
    return folder.is_dir() and any(folder.glob("*.md"))


def _get_text(url: str, timeout: float, retries: int) -> str:
    """Fetch a URL and return its body as text, retrying on transport errors."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as error:
            last_error = error
            if attempt < retries:
                continue
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def select_pages(
    source: DocsSource,
    pages: list[Page],
    skip: int | None = None,
    limit: int = 0,
    only: Iterable[str] = (),
) -> list[Page]:
    """Apply the skip, filter and limit options to the index entries."""
    selected = pages[source.skip if skip is None else skip :]
    for needle in only:
        lowered = needle.lower()
        selected = [
            page
            for page in selected
            if lowered in page.title.lower() or lowered in page.url.lower()
        ]
    if limit > 0:
        selected = selected[:limit]
    return selected


def fetch_docs(
    source: DocsSource,
    docs_dir: Path | str = DOCS_DIR,
    skip: int | None = None,
    limit: int = 0,
    only: Iterable[str] = (),
    force: bool = False,
    delay: float = 0.3,
    timeout: float = 30.0,
    retries: int = 3,
    progress: ProgressCallback | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> FetchResult:
    """Download the documentation of one provider into ``docs_dir``.

    Existing files are kept unless ``force`` is set, so the function is safe to call
    for a folder that is already populated. ``cancel_check`` is consulted before every
    page, which lets the caller stop a long download.
    """
    target_dir = Path(docs_dir) / source.provider_id
    result = FetchResult(provider_id=source.provider_id)
    index_text = _get_text(source.index_url, timeout, retries)
    pages = select_pages(source, parse_index(index_text), skip=skip, limit=limit, only=only)
    result.total = len(pages)
    if not pages:
        return result

    target_dir.mkdir(parents=True, exist_ok=True)

    for number, page in enumerate(pages, start=1):
        if cancel_check is not None and cancel_check():
            result.cancelled = True
            break
        target = target_dir / f"{number:02d}_{slugify(page.title)}.md"
        if target.exists() and not force:
            result.skipped += 1
            continue
        try:
            write_page(target, _get_text(page.url, timeout, retries))
        except RuntimeError as error:
            result.failed += 1
            result.errors.append(f"{page.title}: {error}")
            continue
        result.saved += 1
        if progress is not None:
            progress(f"{number}/{len(pages)} {target.name}")
        if delay > 0:
            _sleep(delay)
    return result


def _sleep(seconds: float) -> None:
    """Pause between requests, isolated so tests can replace it."""
    import time

    time.sleep(seconds)
