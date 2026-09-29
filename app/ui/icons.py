"""The favourite star icon.

The app does not draw the star as a character: U+2605 and U+2606 are not in
Segoe UI, so they came from a fallback font whose size, weight and presence
the app does not control. The icons are built by ``scripts/make_star_icons.py``
from a picture generated with the app itself.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon

from app.config import STAR_ICON_DIR

# Qt scales the file down, so one size serves every place that shows a star.
BUTTON_ICON_SIZE = 18
LIST_ICON_SIZE = 14

_cache: dict[tuple[str, bool], QIcon] = {}


def favourite_icon(filled: bool, theme: str) -> QIcon:
    """The star icon for one state and theme, cached.

    A missing file gives an empty icon rather than an error: the rest of the
    interface keeps working, the star is simply not drawn.
    """
    key = (theme, filled)
    if key not in _cache:
        state = "filled" if filled else "outline"
        _cache[key] = QIcon(str(STAR_ICON_DIR / f"star-{state}-{theme}.png"))
    return _cache[key]
