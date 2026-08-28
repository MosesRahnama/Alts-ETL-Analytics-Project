"""Deterministic private-market analytics and portfolio construction."""

from importlib import import_module
from typing import Any

__all__ = [
    "ANALYSIS_RESULT_COLUMNS",
    "PORTFOLIO_ALLOCATION_COLUMNS",
    "AnalyticsError",
    "bounded_equal_weights",
    "build_portfolio_allocations",
    "calculate_fund_metrics",
    "calculate_pme_results",
    "run_round04",
]


def __getattr__(name: str) -> Any:
    """Load public helpers lazily so the command-line module runs without warnings."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("src.analytics.run_round04_analytics"), name)
    globals()[name] = value
    return value
