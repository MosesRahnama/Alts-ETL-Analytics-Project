"""Fund-level quality controls."""

from __future__ import annotations

from typing import Any

__all__ = ["run_quality_checks"]


def run_quality_checks(*args: Any, **kwargs: Any) -> Any:
    """Load the checker lazily to keep its command-line module warning-free."""
    from .run_fund_checks import run_quality_checks as implementation

    return implementation(*args, **kwargs)
