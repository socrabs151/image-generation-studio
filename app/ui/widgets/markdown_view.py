"""Markdown rendering for the documentation window.

Documents are rendered to HTML and shown in a :class:`QTextBrowser`. Code blocks are
highlighted with Pygments and the stylesheet follows the application theme, so the
viewer matches the rest of the interface in both light and dark mode.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.style import Style
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
from pygments.util import ClassNotFound
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

_CODE_FONT = '"Cascadia Mono", Consolas, monospace'

# Vendor documentation starts with a banner pointing back at its own index page.
_INDEX_BANNER = re.compile(
    r"[ \t]*>[ \t]*##[ \t]*Documentation Index.*?(?=\n[ \t]*\n|\Z)",
    re.DOTALL,
)
_NO_LANGUAGE = {"text", "txt", "plaintext", "none", ""}

# A code block is emitted as this tag so markdown-it inserts it verbatim instead of
# wrapping it into a default <pre><code>, which Qt is unable to shrink.
_CODE_BLOCK = re.compile(
    r'<pre class="codetext" data-lang="([^"]*)"([^>]*)>(.*?)</pre>',
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ViewerColors:
    """Colours used to render a Markdown document."""

    background: str
    text: str
    muted: str
    link: str
    rule: str
    code_background: str
    inline_code_background: str
    quote_background: str
    quote_border: str
    table_header_background: str
    table_stripe_background: str
    comment: str
    keyword: str
    string: str
    number: str
    code_style: type[Style]

    def stylesheet(self) -> str:
        """The Qt stylesheet for rendered Markdown.

        Only typography lives here: Qt honours element selectors for sizes and
        margins, but reliably paints backgrounds and colours from inline styles,
        which the renderer emits directly.
        """
        return f"""
            body {{ color: {self.text}; }}
            h1, h2, h3, h4, h5, h6 {{ color: {self.text}; }}
            h1 {{ font-size: 19pt; margin-top: 2px; margin-bottom: 12px; }}
            h2 {{ font-size: 14pt; margin-top: 20px; margin-bottom: 8px; }}
            h3 {{ font-size: 12pt; margin-top: 16px; margin-bottom: 6px; }}
            h4 {{ font-size: 11pt; margin-top: 14px; margin-bottom: 4px; }}
            a {{ text-decoration: none; }}
            code {{ font-family: {_CODE_FONT}; }}
            pre {{
                font-family: {_CODE_FONT};
                font-size: 9pt;
                white-space: pre-wrap;
                margin-top: 0;
                margin-bottom: 0;
            }}
            .codelabel {{ font-size: 8pt; }}
        """


# Restrained code palette: the body text of a snippet stays in the theme colour and
# only four token types are tinted, which keeps long listings calm to read.
LIGHT_SYNTAX = {
    "comment": "#8a93a3",
    "keyword": "#2f6fed",
    "string": "#0a7d55",
    "number": "#b5561f",
}
DARK_SYNTAX = {
    "comment": "#6f6f8a",
    "keyword": "#7aa2f7",
    "string": "#8fbf7f",
    "number": "#d7a06a",
}


class _LightCodeStyle(Style):
    """Restrained palette for code in the light theme."""

    name = "studio-light"
    background_color = "#f4f5f8"
    highlight_color = "#e6ecff"
    styles = {
        Token: "#1f2430",
        Comment: f"italic {LIGHT_SYNTAX['comment']}",
        Keyword: f"bold {LIGHT_SYNTAX['keyword']}",
        String: LIGHT_SYNTAX["string"],
        Number: LIGHT_SYNTAX["number"],
        Name.Function: "#1f2430",
        Operator: "#1f2430",
    }


class _DarkCodeStyle(Style):
    """Restrained palette for code in the dark theme."""

    name = "studio-dark"
    background_color = "#101018"
    highlight_color = "#232338"
    styles = {
        Token: "#e6e6f0",
        Comment: f"italic {DARK_SYNTAX['comment']}",
        Keyword: f"bold {DARK_SYNTAX['keyword']}",
        String: DARK_SYNTAX["string"],
        Number: DARK_SYNTAX["number"],
        Name.Function: "#e6e6f0",
        Operator: "#e6e6f0",
    }

LIGHT_COLORS = ViewerColors(
    background="#ffffff",
    text="#1f2430",
    muted="#5a6472",
    link="#2f6fed",
    rule="#d5d9e0",
    code_background="#f4f5f8",
    inline_code_background="#eef0f4",
    quote_background="#f4f7ff",
    quote_border="#6c8cff",
    table_header_background="#eef0f4",
    table_stripe_background="#fafbfc",
    comment=LIGHT_SYNTAX["comment"],
    keyword=LIGHT_SYNTAX["keyword"],
    string=LIGHT_SYNTAX["string"],
    number=LIGHT_SYNTAX["number"],
    code_style=_LightCodeStyle,
)

DARK_COLORS = ViewerColors(
    background="#1e1e2e",
    text="#e6e6f0",
    muted="#9a9ab0",
    link="#8aa4ff",
    rule="#3a3a52",
    code_background="#101018",
    inline_code_background="#2b2b42",
    quote_background="#232338",
    quote_border="#6c8cff",
    table_header_background="#2b2b42",
    table_stripe_background="#22222f",
    comment=DARK_SYNTAX["comment"],
    keyword=DARK_SYNTAX["keyword"],
    string=DARK_SYNTAX["string"],
    number=DARK_SYNTAX["number"],
    code_style=_DarkCodeStyle,
)


THEME_COLORS = {"light": LIGHT_COLORS, "dark": DARK_COLORS}


def _lexer_for(code: str, language: str):
    """Find a Pygments lexer for a code block, guessing when the hint is useless."""
    name = (language or "").strip()
    if name.lower() not in _NO_LANGUAGE:
        try:
            return get_lexer_by_name(name, stripall=False)
        except ClassNotFound:
            pass
    try:
        return guess_lexer(code)
    except ClassNotFound:
        return None


def _inner_markup(fragment: str) -> str:
    """Strip the ``<div class="highlight"><pre>`` wrapper Pygments adds.

    Only the highlighted spans are wanted: a second ``<pre>`` would be the one Qt
    lays out, and that one is not the tag carrying the ``pre-wrap`` rule.
    """
    match = re.search(r"<pre[^>]*>(.*)</pre>", fragment, re.DOTALL)
    return match.group(1) if match else fragment


def _render_code_block(code: str, language: str, colors: ViewerColors) -> str:
    """Return the HTML for one fenced code block.

    The fragment must start with ``<pre`` so that markdown-it inserts it as is. The
    stylesheet turns that tag into ``white-space: pre-wrap``: a plain ``<pre>`` cannot
    be narrower than its longest line, so a single long line would stretch the whole
    document and add a horizontal scrollbar to every page.
    """
    lexer = _lexer_for(code, language)
    if lexer is None:
        body = html.escape(code)
    else:
        formatter = HtmlFormatter(
            style=colors.code_style,
            noclasses=True,
            nowrap=True,
            fontfamily=_CODE_FONT,
        )
        body = _inner_markup(pygments_highlight(code, lexer, formatter))
    label = html.escape((language or "").strip() or "text")
    style = (
        f"background-color:{colors.code_background};color:{colors.text};"
        "padding:8px;"
    )
    return f'<pre class="codetext" data-lang="{label}" style="{style}">{body}</pre>'


def _build_parser(colors: ViewerColors) -> MarkdownIt:
    """Create a Markdown parser that highlights code through Pygments."""
    parser = MarkdownIt(
        "commonmark",
        {
            "highlight": lambda code, language, _attrs: _render_code_block(
                code, language, colors
            )
        },
    )
    return parser.enable("table").enable("strikethrough")


def _wrap_code_blocks(document: str, colors: ViewerColors) -> str:
    """Add the tinted background and the language caption to each code block."""

    def wrap(match: re.Match[str]) -> str:
        label, style, body = match.group(1), match.group(2), match.group(3)
        caption = (
            f'<div class="codelabel" style="color:{colors.muted};padding:6px 8px 2px 8px;">'
            f"{label}</div>"
        )
        panel = f'<div style="background-color:{colors.code_background};margin-bottom:14px;">'
        return f'{panel}{caption}<pre class="codetext"{style}>{body}</pre></div>'

    return _CODE_BLOCK.sub(wrap, document)


def _mark_inline_code(document: str, colors: ViewerColors) -> str:
    """Tag inline code spans; code blocks are inserted before this step."""

    def mark(match: re.Match[str]) -> str:
        style = (
            f"background-color:{colors.inline_code_background};color:{colors.text};"
            "padding:1px 4px;"
        )
        return f'<code style="{style}">{match.group(1)}</code>'

    return re.sub(r"<code>(.*?)</code>", mark, document, flags=re.DOTALL)


def _mark_table_rows(document: str, colors: ViewerColors) -> str:
    """Tint the header row and every other body row so tables are readable."""

    def header(match: re.Match[str]) -> str:
        return match.group(0).replace(
            "<th>",
            f'<th style="background-color:{colors.table_header_background};">',
        )

    def stripe(match: re.Match[str]) -> str:
        return match.group(0).replace(
            "<td>",
            f'<td style="background-color:{colors.table_stripe_background};">',
            1,
        )

    document = re.sub(r"<th>.*?</tr>", header, document, flags=re.DOTALL)
    return re.sub(r"<tr>\s*<td>.*?</tr>", stripe, document, flags=re.DOTALL)


def _mark_links(document: str, colors: ViewerColors) -> str:
    """Colour links; Qt does not paint colours coming from a class selector."""
    return re.sub(
        r"<a href=",
        f'<a style="color:{colors.link};text-decoration:none;" href=',
        document,
    )


def _mark_blockquotes(document: str, colors: ViewerColors) -> str:
    """Give quotes a tinted panel with an accent bar on the left."""
    style = (
        f"background-color:{colors.quote_background};"
        f"border-left:3px solid {colors.quote_border};"
        f"color:{colors.muted};padding:6px 10px;margin-top:8px;margin-bottom:12px;"
    )
    return document.replace("<blockquote>", f'<blockquote style="{style}">')


def _strip_index_banner(text: str) -> str:
    """Remove the vendor's own documentation-index banner."""
    return _INDEX_BANNER.sub("", text, count=1).lstrip("\n")


def render_markdown(text: str, theme: str = "light") -> str:
    """Render Markdown into a complete themed HTML document."""
    colors = THEME_COLORS.get(theme, LIGHT_COLORS)
    body = _build_parser(colors).render(_strip_index_banner(text))
    body = _wrap_code_blocks(body, colors)
    body = _mark_table_rows(body, colors)
    body = _mark_inline_code(body, colors)
    body = _mark_links(body, colors)
    body = _mark_blockquotes(body, colors)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        "<div style='margin: 16px 20px;'>"
        f"{body}</div><style>{colors.stylesheet()}</style></body></html>"
    )


class MarkdownView(QTextBrowser):
    """Markdown document rendered as themed rich text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setMinimumHeight(220)
        self._theme = "light"
        self._content = ""
        self.document().setDefaultStyleSheet(LIGHT_COLORS.stylesheet())
        self.anchorClicked.connect(self._open_link)

    def theme(self) -> str:
        """The theme the document is currently rendered with."""
        return self._theme

    def set_theme(self, theme: str) -> None:
        """Switch the palette and re-render the document that is on screen."""
        theme = theme if theme in THEME_COLORS else "light"
        if theme == self._theme:
            return
        self._theme = theme
        self.set_markdown(self._content)

    def set_markdown(self, content: str) -> None:
        """Render Markdown text and return the view to the top."""
        self._content = content
        colors = THEME_COLORS[self._theme]
        self.setHtml(render_markdown(content, self._theme))
        self.document().setDefaultStyleSheet(colors.stylesheet())
        self.verticalScrollBar().setValue(0)

    def show_placeholder(self, message: str) -> None:
        """Show a muted hint while no document is selected."""
        self._content = ""
        colors = THEME_COLORS[self._theme]
        self.setHtml(
            f"<p style='color:{colors.muted}; margin: 40px; text-align:center;'>"
            f"{html.escape(message)}</p>"
        )

    def set_error(self, message: str) -> None:
        """Show a failure message instead of a document."""
        self._content = ""
        accent = DARK_COLORS.quote_border if self._theme == "dark" else "#d93636"
        self.setHtml(
            f"<p style='color:{accent}; margin: 16px;'>{html.escape(message)}</p>"
        )

    @staticmethod
    def _open_link(url) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
