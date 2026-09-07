"""Shared utilities for the alternative-investment data pipeline."""

from typing import Any

__all__ = ["xirr", "xnpv"]


def __getattr__(name: str) -> Any:
    """Load the finance exports without importing them during package setup."""

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .finance import xirr, xnpv

    return {"xirr": xirr, "xnpv": xnpv}[name]
