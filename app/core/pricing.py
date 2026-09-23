"""Price formatting and reserved-amount calculations.

Providers quote an estimated price range per image; the actual charge may differ.
Before a request the API freezes the maximum possible amount (``max_price * n``)
and refunds the difference afterwards.
"""

from __future__ import annotations

MONEY_PLACEHOLDER = "—"


def format_money(value: float | None) -> str:
    """Format a ruble amount with two decimals, or a placeholder when unknown."""
    if value is None:
        return MONEY_PLACEHOLDER
    return f"{value:.2f}"


def format_price(min_price: float | None, max_price: float | None) -> str:
    """Format a price range: a single value when flat, otherwise ``min…max``."""
    if min_price is None:
        return MONEY_PLACEHOLDER
    if max_price is None or abs(max_price - min_price) <= 0.005:
        return format_money(min_price)
    return f"{format_money(min_price)}…{format_money(max_price)}"


def reserved_amount(max_price: float | None, n: int) -> float | None:
    """Amount frozen on the balance for a request of ``n`` images."""
    if max_price is None:
        return None
    return max_price * max(1, n)


def can_afford(balance: float | None, reserved: float | None) -> bool:
    """Whether the current balance covers the reserved amount."""
    if balance is None or reserved is None:
        return True
    return balance >= reserved
