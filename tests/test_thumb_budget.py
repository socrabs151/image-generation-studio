"""Tests for how much of a generated image the result grid keeps.

No PySide6 import here on purpose: the CI runner has no ``libEGL``, and a test
that imports Qt fails at collection. The numbers live in
:mod:`app.ui.thumb_budget` and the widgets use them, so this checks the rule the
app follows rather than a copy of it.
"""

from __future__ import annotations

from app.ui.thumb_budget import (
    RETAINED_SIZE,
    THUMB_SIZE,
    approx_bytes,
    retained_size,
    saving_factor,
)

# ---------- the rule ----------


def test_a_big_image_is_reduced() -> None:
    assert retained_size(4096, 4096) == (RETAINED_SIZE, RETAINED_SIZE)


def test_the_proportions_are_kept() -> None:
    # 4096x2048 is landscape, so the width is the long side.
    width, height = retained_size(4096, 2048)
    assert width == RETAINED_SIZE
    assert abs(width / height - 2.0) < 0.01


def test_a_small_image_is_left_alone() -> None:
    """Scaling it up would cost memory and blur the thumbnail."""
    assert retained_size(64, 64) == (64, 64)
    assert retained_size(320, 240) == (320, 240)


def test_the_boundary_is_inclusive() -> None:
    assert retained_size(RETAINED_SIZE, RETAINED_SIZE) == (
        RETAINED_SIZE,
        RETAINED_SIZE,
    )
    assert retained_size(RETAINED_SIZE + 1, RETAINED_SIZE + 1) == (
        RETAINED_SIZE,
        RETAINED_SIZE,
    )


def test_a_portrait_image_keeps_its_shape() -> None:
    width, height = retained_size(2048, 4096)
    assert height == RETAINED_SIZE
    assert height > width


def test_nothing_becomes_zero_or_negative() -> None:
    for size in ((1, 1), (3, 10000), (10000, 3), (0, 100), (100, 0)):
        width, height = retained_size(*size)
        assert width >= 0 and height >= 0, size


def test_the_thumbnail_is_smaller_than_what_is_kept() -> None:
    """The grid draws THUMB_SIZE; keeping anything smaller would blur it."""
    assert RETAINED_SIZE > THUMB_SIZE


# ---------- what it buys ----------


def test_six_4k_results_do_not_sit_in_memory() -> None:
    """The defect: six 4K images were held at full size, 384 MiB, for a grid
    that draws 180 px thumbnails."""
    full = approx_bytes(4096, 4096) * 6
    kept = approx_bytes(*retained_size(4096, 4096)) * 6

    assert full > 300 * 1024 * 1024, "the problem was measured in hundreds of MiB"
    assert kept < 10 * 1024 * 1024, f"the grid still holds {kept / 1024 / 1024:.0f} MiB"
    assert saving_factor(4096, 4096) > 60


def test_a_typical_generation_is_reduced_too() -> None:
    """1024 is the resolution the catalogs offer, so it is the common case."""
    assert saving_factor(1024, 1024) > 3


def test_nothing_is_saved_for_an_image_that_already_fits() -> None:
    assert saving_factor(320, 320) == 1.0


def test_the_kept_copy_is_never_larger_than_the_original() -> None:
    for width, height in ((4096, 4096), (1024, 1024), (320, 240), (8, 8)):
        kept_width, kept_height = retained_size(width, height)
        assert approx_bytes(kept_width, kept_height) <= approx_bytes(width, height)
