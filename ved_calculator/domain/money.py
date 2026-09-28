"""Decimal arithmetic helpers shared by every service.

Every monetary quantity inside the engine is a :class:`decimal.Decimal`.  Floats
are converted through their shortest ``repr`` so that ``0.1`` becomes
``Decimal("0.1")`` and never ``0.1000000000000000055…``.  Rounding is applied
only at the presentation boundary (``q2``/``q4``); intermediate results keep the
full 28-digit context precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "BASIS",
    "CENT",
    "HUNDRED",
    "ONE",
    "ZERO",
    "D",
    "DecimalLike",
    "apply_percent",
    "clamp",
    "fmt",
    "pct",
    "q2",
    "q4",
    "safe_div",
]

DecimalLike = Decimal | int | float | str

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")
BASIS = Decimal("0.0001")


def D(value: DecimalLike) -> Decimal:  # noqa: N802 - deliberately short constructor name
    """Coerce ``value`` to :class:`Decimal` without binary-float artefacts."""
    if isinstance(value, bool):  # bool is an int subclass; never a monetary value
        raise TypeError("bool is not a monetary value")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def q2(value: DecimalLike) -> Decimal:
    """Round half-up to 2 decimal places (money presentation)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value: DecimalLike) -> Decimal:
    """Round half-up to 4 decimal places (rates, coefficients, scores)."""
    return D(value).quantize(BASIS, rounding=ROUND_HALF_UP)


def fmt(value: DecimalLike) -> str:
    """Shortest plain-notation string (``Decimal("10").normalize()`` would give ``1E+1``)."""
    return format(D(value).normalize(), "f")


def pct(percent: DecimalLike) -> Decimal:
    """Convert a percentage (``12``) into a multiplier fraction (``0.12``)."""
    return D(percent) / HUNDRED


def apply_percent(amount: DecimalLike, percent: DecimalLike) -> Decimal:
    """Return ``amount × percent / 100``."""
    return D(amount) * pct(percent)


def clamp(
    value: DecimalLike,
    minimum: DecimalLike | None = None,
    maximum: DecimalLike | None = None,
) -> Decimal:
    """Clamp ``value`` into ``[minimum, maximum]`` (either bound may be ``None``)."""
    result = D(value)
    if minimum is not None:
        result = max(result, D(minimum))
    if maximum is not None:
        result = min(result, D(maximum))
    return result


def safe_div(numerator: DecimalLike, denominator: DecimalLike) -> Decimal:
    """Divide, raising a descriptive :class:`ZeroDivisionError` on a zero divisor."""
    den = D(denominator)
    if den == ZERO:
        raise ZeroDivisionError("division by zero in monetary calculation")
    return D(numerator) / den
