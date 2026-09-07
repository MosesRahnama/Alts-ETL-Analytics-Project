"""Thin CLI wrapper for the deterministic wide-row extraction workflow."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.simple_pdf_extraction.csv_workflow import main


if __name__ == "__main__":
    main()
