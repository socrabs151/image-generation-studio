"""Tests for the Markdown renderer used by the documentation window.

Only the HTML generation is exercised, so no window has to be created. The renderer
is deliberately free of PySide6: CI runs on a headless Linux runner without the Qt
runtime libraries, and importing Qt there fails.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.ui.markdown import (
    DARK_COLORS,
    LIGHT_COLORS,
    THEME_COLORS,
    render_markdown,
)

SAMPLE = """# Заголовок

> Цитата с пояснением.

Обычный текст с `инлайн-кодом` и [ссылкой](https://example.com).

| Поле | Тип |
| --- | --- |
| `amount` | string |
| `spent` | string |

```python
def hello(name: str) -> str:
    return f"привет, {name}"
```
"""


def test_index_banner_is_removed() -> None:
    document = render_markdown(
        "> ## Documentation Index\n> Fetch the complete documentation index\n\n# Title\n"
    )

    assert "Documentation Index" not in document
    assert "<h1>Title</h1>" in document


def test_code_block_is_highlighted_and_labelled() -> None:
    document = render_markdown("```python\nx = 1\n```\n")

    assert 'class="codelabel"' in document
    assert ">python</div>" in document
    assert 'class="codetext"' in document
    # The keyword must be coloured, which only happens through Pygments.
    assert "<span" in document
    assert "#101018" in document or "#f4f5f8" in document


def test_code_blocks_wrap_instead_of_stretching_the_page() -> None:
    document = render_markdown("```\n" + "long " * 200 + "\n```\n")

    # Qt cannot shrink a plain <pre>, so the renderer marks its own tag instead.
    assert 'class="codetext"' in document
    assert "white-space: pre-wrap" in document
    assert "<pre>" not in document


def test_table_is_striped() -> None:
    document = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n")

    assert "<table>" in document
    assert LIGHT_COLORS.table_header_background in document
    assert LIGHT_COLORS.table_stripe_background in document


def test_inline_code_and_links_are_styled() -> None:
    document = render_markdown("`code` and [link](https://example.com)\n")

    assert f"background-color:{LIGHT_COLORS.inline_code_background}" in document
    assert f"color:{LIGHT_COLORS.link}" in document


@pytest.mark.parametrize(
    ("theme", "background"),
    [("light", "#f4f5f8"), ("dark", "#101018")],
)
def test_theme_changes_the_palette(theme: str, background: str) -> None:
    document = render_markdown("```\nplain\n```\n", theme)

    assert background in document
    keyword = THEME_COLORS[theme].keyword.lower()
    highlighted = render_markdown("```python\nif x:\n    pass\n```\n", theme).lower()
    assert keyword in highlighted


def test_unknown_theme_falls_back_to_light() -> None:
    assert render_markdown("text", "neon") == render_markdown("text", "light")


def test_empty_document_renders_without_error() -> None:
    assert "<body>" in render_markdown("")


def test_renderer_does_not_require_qt() -> None:
    """The renderer must stay importable where Qt is unavailable.

    Importing PySide6.QtGui fails on a headless runner without libEGL, which broke
    CI; the rendering logic therefore has to live outside the widget module.
    """
    import app.ui.markdown as renderer

    source = pathlib.Path(renderer.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in source.replace(
        "Kept free of PySide6 so the rendering can be tested on a headless machine", ""
    )


def test_both_palettes_define_every_colour() -> None:
    assert DARK_COLORS.background != LIGHT_COLORS.background
    for colors in (DARK_COLORS, LIGHT_COLORS):
        assert colors.stylesheet().strip()
        assert colors.keyword and colors.string and colors.comment and colors.number


def test_code_uses_only_the_restrained_palette() -> None:
    document = render_markdown(
        '```python\n# note\nif "text" in data:\n    print(42)\n```\n', "dark"
    )
    block = re.search(r'<pre class="codetext".*?</pre>', document, re.DOTALL)
    assert block, "блок кода не найден"

    colours = {
        c.lower()
        for c in re.findall(r"""[\s;"']color:\s*(#[0-9a-fA-F]{6})""", block.group(0))
    }
    allowed = {
        DARK_COLORS.text.lower(),
        DARK_COLORS.comment.lower(),
        DARK_COLORS.keyword.lower(),
        DARK_COLORS.string.lower(),
        DARK_COLORS.number.lower(),
    }
    assert colours
    assert colours <= allowed, f"лишние цвета: {colours - allowed}"
