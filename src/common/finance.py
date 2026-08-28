"""Financial calculations shared by generation, quality, and analytics code."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from math import isfinite
from typing import Iterable

CashFlow = tuple[date, float]


def _as_date(value: date | datetime) -> date:
    """Return a date, rejecting values that fail to define a cash-flow day."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"cash-flow date must be date or datetime, got {type(value).__name__}")


def _normalize_cashflows(cashflows: Iterable[CashFlow]) -> list[CashFlow]:
    """Aggregate same-day values and return them in chronological order."""
    by_date: dict[date, float] = defaultdict(float)
    for cashflow_date, amount in cashflows:
        parsed_date = _as_date(cashflow_date)
        parsed_amount = float(amount)
        if not isfinite(parsed_amount):
            raise ValueError("cash-flow amounts must be finite")
        by_date[parsed_date] += parsed_amount
    return sorted(by_date.items())


def _spaced(normalized: list[CashFlow]) -> tuple[list[float], list[float]]:
    """Return year offsets and amounts, both indexed against the first cash flow."""
    origin = normalized[0][0]
    years = [(cashflow_date - origin).days / 365.0 for cashflow_date, _ in normalized]
    amounts = [amount for _, amount in normalized]
    return years, amounts


def _npv(rate: float, years: list[float], amounts: list[float]) -> float:
    """Discount pre-spaced amounts; the caller guarantees rate is above -1."""
    base = 1.0 + rate
    total = 0.0
    for offset, amount in zip(years, amounts):
        try:
            total += amount / (base**offset)
        except OverflowError:
            return float("inf") if amount > 0 else float("-inf")
    return total


def _npv_derivative(rate: float, years: list[float], amounts: list[float]) -> float:
    """Return d(NPV)/d(rate) for the same pre-spaced amounts."""
    base = 1.0 + rate
    total = 0.0
    for offset, amount in zip(years, amounts):
        if offset == 0.0:
            continue
        try:
            total -= offset * amount / (base ** (offset + 1.0))
        except OverflowError:
            return float("-inf") if amount > 0 else float("inf")
    return total


def xnpv(rate: float, cashflows: Iterable[CashFlow]) -> float:
    """Calculate net present value using actual day spacing and a 365-day year."""
    rate = float(rate)
    if rate <= -1.0:
        raise ValueError("XNPV rate must be greater than -1")
    normalized = _normalize_cashflows(cashflows)
    if not normalized:
        raise ValueError("XNPV requires at least one cash flow")
    years, amounts = _spaced(normalized)
    return _npv(rate, years, amounts)


def xirr(
    cashflows: Iterable[CashFlow],
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 250,
) -> float:
    """Calculate an annualized IRR for irregularly dated cash flows.

    The routine uses a deterministic expanding bracket, then a Newton step that
    falls back to bisection whenever the step leaves the bracket. Cash flows are
    spaced once and reused across every iteration, so a long fund history costs
    a fraction of a repeated-normalization search. It is intended for
    conventional private-fund cash-flow patterns. A clear exception is raised
    when the values omit a negative amount or a positive amount, or when the
    expanding bracket fails to enclose a root.
    """
    normalized = _normalize_cashflows(cashflows)
    if len(normalized) < 2:
        raise ValueError("XIRR requires at least two dated cash flows")
    amounts = [amount for _, amount in normalized]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        raise ValueError("XIRR requires at least one negative and one positive value")

    years, spaced_amounts = _spaced(normalized)
    left = -0.999999
    right = 1.0
    left_value = _npv(left, years, spaced_amounts)
    right_value = _npv(right, years, spaced_amounts)

    while _same_sign(left_value, right_value) and right < 1_000_000.0:
        right = right * 2.0 + 1.0
        right_value = _npv(right, years, spaced_amounts)

    if _same_sign(left_value, right_value):
        raise ValueError("XIRR failed to bracket a unique conventional root")

    guess = (left + right) / 2.0
    guess_value = _npv(guess, years, spaced_amounts)
    for _ in range(max_iterations):
        if abs(guess_value) <= tolerance or (right - left) <= tolerance:
            return guess
        if _same_sign(left_value, guess_value):
            left = guess
            left_value = guess_value
        else:
            right = guess
            right_value = guess_value
        slope = _npv_derivative(guess, years, spaced_amounts)
        candidate = guess - guess_value / slope if slope not in (0.0, float("inf"), float("-inf")) else guess
        if not (left < candidate < right):
            candidate = (left + right) / 2.0
        guess = candidate
        guess_value = _npv(guess, years, spaced_amounts)
    return guess


def _same_sign(left: float, right: float) -> bool:
    """Return true when two nonzero values have the same sign."""
    return (left > 0 and right > 0) or (left < 0 and right < 0)
