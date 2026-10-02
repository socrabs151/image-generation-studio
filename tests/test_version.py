"""Tests for the one place the version is written.

It was written in four files, two of them copies, so a release had to remember
all of them. Nothing but this test would notice one being missed: the copies
were valid Python and produced a plausible user agent.

No PySide6 import here on purpose: the CI runner has no ``libEGL``.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import app
from app.providers.http_utils import USER_AGENT as PROVIDER_USER_AGENT
from app.services.docs_sync import USER_AGENT as DOCS_USER_AGENT

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: The only file allowed to hold a version literal.
VERSION_FILE = "app/__init__.py"

#: Text files worth searching for a stray copy of the number.
SOURCES = (
    "pyproject.toml",
    "app/__init__.py",
    "app/config.py",
    "app/providers/http_utils.py",
    "app/services/docs_sync.py",
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_the_version_looks_like_a_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", app.__version__), (
        f"{app.__version__} is not a plain semantic version"
    )


def test_only_one_file_holds_a_version_literal() -> None:
    pattern = re.compile(r'__version__\s*=\s*"([^"]+)"')
    holders = {
        relative: pattern.findall(_source(relative))
        for relative in SOURCES
        if pattern.search(_source(relative))
    }
    assert set(holders) == {VERSION_FILE}, (
        f"the version is written in more than one place: {holders}"
    )
    assert holders[VERSION_FILE] == [app.__version__], (
        "app/__init__.py must be the one copy, and the one the app reads"
    )


def test_pyproject_takes_the_version_from_the_package() -> None:
    """A second copy in the metadata is the copy that drifts."""
    text = _source("pyproject.toml")
    assert 'version = { attr = "app.__version__" }' in text, (
        "the package version must be read from app/__init__.py"
    )
    assert 'dynamic = ["version"]' in text, "version must be declared dynamic"
    # No plain `version = "x.y.z"` next to the name.
    static = re.findall(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert not static, f"pyproject still carries a hard-coded version: {static}"


def test_the_user_agent_is_built_from_the_version() -> None:
    expected = f"image-generation-studio/{app.__version__}"
    assert PROVIDER_USER_AGENT == expected
    assert DOCS_USER_AGENT == expected, (
        "docs_sync has its own copy of the user agent; it must come from the version"
    )


def test_no_source_hard_codes_the_version_string() -> None:
    """A literal like "image-generation-studio/0.1" survives a release and then
    tells the aggregator the wrong version.

    The search is for *any* version-shaped tail, not the current one: a stale
    copy says "0.1" while the app is at "0.1.0", and matching the current value
    would walk straight past it.
    """
    pattern = re.compile(r'"image-generation-studio/\d+(\.\d+)*"')
    offenders = [relative for relative in SOURCES if pattern.search(_source(relative))]
    assert not offenders, f"the user agent is written literally in {offenders}"


@pytest.mark.parametrize("relative", SOURCES)
def test_only_the_version_file_carries_a_version_literal(relative: str) -> None:
    """Any quoted version outside ``app/__init__.py`` is a copy waiting to drift.
    Dependency pins are exempt: they name someone else's version."""
    text = _source(relative)
    if relative == VERSION_FILE:
        return
    # Drop the dependency declarations, then look for what is left.
    without_pins = re.sub(r">=\s*\d+(\.\d+)*", ">=", text)
    found = re.findall(r'"\d+\.\d+(\.\d+)?"', without_pins)
    assert not found, (
        f"{relative} mentions {found}; only {VERSION_FILE} may name a version"
    )
