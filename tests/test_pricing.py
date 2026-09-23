"""Tests for the domain models and pricing helpers."""

from __future__ import annotations

from app.core.models import ModelInfo
from app.core.pricing import (
    can_afford,
    format_money,
    format_price,
    reserved_amount,
)


def test_format_money() -> None:
    assert format_money(None) == "—"
    assert format_money(3.4) == "3.40"


def test_format_price_flat_and_range() -> None:
    assert format_price(None, None) == "—"
    assert format_price(5.0, 5.0) == "5.00"
    assert format_price(0.85, 42.5) == "0.85…42.50"


def test_reserved_amount() -> None:
    assert reserved_amount(None, 3) is None
    assert reserved_amount(20.4, 1) == 20.4
    assert reserved_amount(20.4, 3) == 20.4 * 3


def test_can_afford() -> None:
    assert can_afford(None, 10.0) is True
    assert can_afford(5.0, 10.0) is False
    assert can_afford(10.0, 10.0) is True


def test_price_range_and_display_name() -> None:
    flat = ModelInfo(id="m", provider_id="aitunnel", min_price=5.0, max_price=5.0, max_n=1)
    assert flat.price_range is False

    ranged = ModelInfo(
        id="gpt-image-1",
        provider_id="aitunnel",
        min_price=0.85,
        max_price=42.5,
        resolutions=["1K", "2K"],
        max_input_references=5,
        max_n=4,
    )
    assert ranged.price_range is True
    label = ranged.display_name()
    assert "gpt-image-1" in label
    assert "aitunnel" in label
    assert "0.85…42.50" in label
