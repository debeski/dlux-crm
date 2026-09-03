"""Presentation helpers shared by tables, services and templates."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_money(value):
    """Render LYD prices, costs and totals at the stored two-decimal precision."""
    try:
        amount = Decimal(str(value or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return f"{amount:,.2f}"


def format_quantity(value):
    """Render a quantity without trailing zeros, whatever type it arrives as.

    ``f"{value:g}"`` cannot do this: Decimal's ``__format__`` keeps the stored
    exponent, so ``Decimal("4.00")`` formats as ``4.00`` while the float ``4.0``
    formats as ``4``. Aggregates return a float on SQLite and a Decimal on
    Postgres — which this project runs in dev and production respectively — so
    the same column rendered differently per backend. ``:g`` also switches to
    scientific notation past six significant digits, which a stock figure must
    never do.
    """
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if quantity == quantity.to_integral_value():
        return f"{quantity.to_integral_value():f}"
    return f"{quantity.normalize():f}"
