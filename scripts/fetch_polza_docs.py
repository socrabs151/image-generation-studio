"""Download the Polza.ai documentation into a local folder.

The vendor publishes a machine-readable index at ``https://polza.ai/docs/llms.txt``
where every entry points to a Markdown version of that page. This script reads the
index and saves each page as a separate file named ``NN_Title.md``, which is the
same layout already used in ``docs/aitunnel``.

The script never overwrites existing files unless ``--force`` is passed, so it is
safe to re-run to pick up new pages.

Usage:
    python scripts/fetch_polza_docs.py --skip 8
    python scripts/fetch_polza_docs.py --only image --force
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

INDEX_URL = "https://polza.ai/docs/llms.txt"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "polzaai"

INDEX_LINE = re.compile(r"^-\s+\[(?P<title>.+?)\]\((?P<url>[^)]+)\)")
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True)
class Page:
    """A single documentation page listed in the vendor index."""

    position: int
    title: str
    url: str


def slugify(title: str) -> str:
    """Convert a page title into a file name stem.

    Parentheses are dropped, spaces become hyphens and characters that Windows
    forbids in file names are replaced with a hyphen.
    """
    text = title.replace("(", " ").replace(")", " ")
    text = ILLEGAL_CHARS.sub("-", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-.")


def parse_index(text: str) -> list[Page]:
    """Extract page entries from the ``llms.txt`` index."""
    pages: list[Page] = []
    for line in text.splitlines():
        match = INDEX_LINE.match(line.strip())
        if match:
            pages.append(
                Page(
                    position=len(pages) + 1,
                    title=match.group("title").strip(),
                    url=match.group("url").strip(),
                )
            )
    return pages


def get_text(url: str, timeout: float, retries: int) -> str:
    """Fetch a URL and return its body as text, retrying on transient errors."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "image-generation-studio-docs-sync"},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def write_page(path: Path, content: str) -> None:
    """Write Markdown text as UTF-8 without BOM using Windows line endings."""
    text = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    with path.open("w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download the Polza.ai documentation as Markdown files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="target directory (default: docs/polzaai)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="skip the first N entries of the index",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="download at most N pages (0 means all)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="TEXT",
        help="keep only pages whose title or URL contains TEXT (repeatable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files that already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the pages without downloading them",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="pause between requests in seconds (default: 0.3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="attempts per page (default: 3)",
    )
    parser.add_argument(
        "--save-index",
        type=Path,
        default=None,
        help="also save the raw index to this path",
    )
    return parser


def select_pages(pages: list[Page], args: argparse.Namespace) -> list[Page]:
    selected = pages[args.skip :]
    for needle in args.only:
        needle = needle.lower()
        selected = [p for p in selected if needle in p.title.lower() or needle in p.url.lower()]
    if args.limit > 0:
        selected = selected[: args.limit]
    return selected


def main() -> int:
    args = build_parser().parse_args()
    pages = parse_index(get_text(INDEX_URL, args.timeout, args.retries))
    if not pages:
        print("Index contains no pages.", file=sys.stderr)
        return 1

    selected = select_pages(pages, args)
    print(f"Index: {len(pages)} pages, selected {len(selected)}.")

    if args.save_index:
        args.save_index.parent.mkdir(parents=True, exist_ok=True)
        write_page(args.save_index, get_text(INDEX_URL, args.timeout, args.retries))
        print(f"Index saved: {args.save_index}")

    if args.dry_run:
        for number, page in enumerate(selected, start=1):
            print(f"  {number:02d} {page.title} <- {page.url}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    saved = skipped = failed = 0

    for number, page in enumerate(selected, start=1):
        target = args.out / f"{number:02d}_{slugify(page.title)}.md"
        if target.exists() and not args.force:
            skipped += 1
            continue
        try:
            write_page(target, get_text(page.url, args.timeout, args.retries))
        except RuntimeError as error:
            failed += 1
            print(f"  FAIL {page.title}: {error}", file=sys.stderr)
            continue
        saved += 1
        print(f"  saved {target.name}")
        if args.delay > 0:
            time.sleep(args.delay)

    print(f"Done: {saved} saved, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
