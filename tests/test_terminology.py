"""User-visible strings that must say "aggregator", not "provider".

The spec (section 2) draws a line: the aggregator is the word for the interface
and for anything the user reads, "provider" stays inside the code. The check is
on the source text, so it needs no Qt and runs in CI everywhere.
"""

from __future__ import annotations

import pathlib
import re

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# Strings the user sees: labels, placeholders, tooltips, log lines, error text.
USER_VISIBLE = re.compile(
    r'"[^"]*\b[Pp]rovider\b[^"]*"'  # "Provider" inside a string literal
    r"|'[^']*\b[Pp]rovider\b[^']*'"
)

# Terms that are legitimately "provider" for the reader even in a user-visible
# string, because they name the field the provider itself returns.
ALLOWED = {
    '"include_providers"',  # the API query parameter
}

# Format fields that interpolate a Python variable named ``provider``. The word
# is in the code, not in the text the user reads.
CODE_INTERPOLATION = re.compile(r"\{provider\.[a-z_]+\}")


def _user_visible_strings() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(APP_DIR.parent).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in USER_VISIBLE.finditer(line):
                text = match.group(0)
                if text in ALLOWED or CODE_INTERPOLATION.search(text):
                    continue
                # Ignore lines that only document code, not the interface.
                stripped = line.strip()
                if stripped.startswith(("#", "*", '"', "'")) and '"""' not in line:
                    continue
                if '"""' in line and '"' not in line.replace('"""', ""):
                    continue
                found.append((relative, number, text))
    return found


def test_no_user_visible_string_says_provider() -> None:
    offenders = [
        f"{where}:{line}: {text}" for where, line, text in _user_visible_strings()
    ]
    assert not offenders, (
        "these strings are shown to the user and must say 'aggregator' "
        f"(spec section 2):\n{offenders}"
    )


def test_the_combobox_label_says_aggregator() -> None:
    text = (APP_DIR / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'QLabel("Aggregator:")' in text
    assert 'QLabel("Provider:")' not in text
