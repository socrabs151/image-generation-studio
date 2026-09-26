"""Download the aggregator reference documentation into ``docs/``.

The vendor documentation is not committed to the repository, so run this once after
cloning (and again whenever a provider publishes changes). Both aggregators expose a
machine-readable index, which is turned into the same ``NN_Title.md`` layout the
documentation window expects.

Usage:
    python scripts/fetch_docs.py                     # every provider
    python scripts/fetch_docs.py --provider polzaai
    python scripts/fetch_docs.py --provider polzaai --only image --force
    python scripts/fetch_docs.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running straight from a clone, before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DOCS_DIR  # noqa: E402
from app.services.docs_sync import (  # noqa: E402
    fetch_docs,
    get_source,
    has_docs,
    source_ids,
)

EXIT_FAILURE = 1


def _require_requests() -> None:
    """Fail with a clear hint when the dependencies are missing."""
    try:
        import requests  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "This script needs 'requests'. Install the dependencies first:\n"
            "    python -m pip install -e ."
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download the aggregator documentation as Markdown files.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=source_ids(),
        help="provider to download; repeatable, defaults to all",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DOCS_DIR,
        help="target folder (default: docs)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=None,
        help="override the number of index entries to skip",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="download at most N pages per provider (0 means all)",
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _require_requests()
    providers = args.provider or source_ids()
    exit_code = 0

    for provider_id in providers:
        source = get_source(provider_id)
        print(f"\n=== {source.display_name} ({source.index_url})")
        if has_docs(source, args.out) and not args.force:
            print("  documentation is already present; use --force to refresh it")

        if args.dry_run:
            from app.services.docs_sync import _get_text, parse_index, select_pages

            pages = select_pages(
                source,
                parse_index(_get_text(source.index_url, args.timeout, args.retries)),
                skip=args.skip,
                limit=args.limit,
                only=args.only,
            )
            print(f"  {len(pages)} pages would be downloaded")
            for number, page in enumerate(pages, start=1):
                print(f"    {number:02d} {page.title} <- {page.url}")
            continue

        try:
            result = fetch_docs(
                source,
                docs_dir=args.out,
                skip=args.skip,
                limit=args.limit,
                only=args.only,
                force=args.force,
                delay=args.delay,
                timeout=args.timeout,
                retries=args.retries,
                progress=lambda line: print(f"  saved {line}"),
            )
        except RuntimeError as error:
            print(f"  FAILED: {error}", file=sys.stderr)
            exit_code = EXIT_FAILURE
            continue

        print(f"  {result.summary()}")
        for message in result.errors:
            print(f"  FAIL {message}", file=sys.stderr)
        if not result.ok:
            exit_code = EXIT_FAILURE

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
