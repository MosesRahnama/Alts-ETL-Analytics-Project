"""Read existing coordinate grids into table-row blocks."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_grid(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def row_blocks(path: Path, file_id: str, source_version: str) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    cells = load_grid(path)
    grouped: dict[tuple[int, str, str], list[dict[str, str]]] = defaultdict(list)
    for cell in cells:
        try:
            page = int(cell.get("source_page") or 0)
        except ValueError:
            continue
        label = cell.get("source_row_label") or f"row-{cell.get('row_index', '')}"
        row_index = (cell.get("row_index") or "").strip()
        if not row_index:
            row_index = "label-" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
        grouped[(page, row_index, label)].append(cell)
    blocks: list[dict[str, Any]] = []
    relations: list[tuple[str, str, str]] = []
    for (page, row_index, label), group in grouped.items():
        headers = []
        values = []
        uncertain = False
        for cell in group:
            header = (cell.get("source_column_label") or "").strip()
            value = (cell.get("value_raw") or "").strip()
            if header:
                headers.append(header)
            if value:
                values.append(f"{header}: {value}" if header else value)
            if not header:
                uncertain = True
        original = f"{label} | " + " | ".join(values)
        parent_id = f"{file_id}:p{page}:page:0"
        label_key = hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]
        block_id = f"{file_id}:p{page}:row:{row_index}:{label_key}"
        blocks.append(
            {
                "block_id": block_id,
                "file_id": file_id,
                "source_version": source_version,
                "physical_page": page,
                "printed_page": None,
                "block_kind": "table_row",
                "original_text": original,
                "search_text": original.lower(),
                "parent_id": parent_id,
                "layout_uncertain": int(uncertain),
                "source_representation": "grid",
                "text_start": None,
                "text_end": None,
            }
        )
        relations.append((block_id, parent_id, "row_of_page"))
    return blocks, relations
