"""Rules for how much of a generated image the result grid keeps.

Qt-free on purpose: the CI runner has no ``libEGL``, so a test that imports Qt
fails at collection. The numbers live here and the widgets use them.
"""

from __future__ import annotations

#: The grid draws a thumbnail of this size.
THUMB_SIZE = 180

#: How much of the original the grid keeps. Large enough for a sharp thumbnail
#: and for the file size shown next to it; small enough that six 4K results cost
#: about 6 MiB instead of 384.
RETAINED_SIZE = 480


def retained_size(width: int, height: int) -> tuple[int, int]:
    """The size a copy should be reduced to, keeping the proportions.

    An image already small enough is left alone: scaling it up would cost memory
    and blur the thumbnail.
    """
    longest = max(width, height)
    if longest <= RETAINED_SIZE or longest <= 0:
        return width, height
    scale = RETAINED_SIZE / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def approx_bytes(width: int, height: int) -> int:
    """Rough resident size of a 32-bit pixmap, for comparing before and after."""
    return width * height * 4


def saving_factor(width: int, height: int) -> float:
    """How many times less memory the grid keeps for one image."""
    kept = approx_bytes(*retained_size(width, height))
    if kept <= 0:
        return 1.0
    return approx_bytes(width, height) / kept
