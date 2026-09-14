"""Read the source ledger and routing table; report identifier disagreements."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from .paths import PROJECT_ROOT


SOURCE_PATH_ROOTS = {
    "pdf_path": ("data", "documents", "pdf"),
    "txt_path": ("data", "documents", "txt"),
    "grid_path": ("data", "documents", "grids"),
    "image_dir": ("data", "documents", "images"),
}


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_document_path(document: Any, key: str, project_root: Path) -> Path | None:
    """Resolve an indexed source path inside the current project checkout."""

    if key not in SOURCE_PATH_ROOTS:
        raise ValueError(f"unsupported source path: {key}")
    root = project_root.resolve(strict=True)
    raw = str(document[key] or "")
    candidates: list[Path] = []
    if raw:
        stored = Path(raw)
        candidates.append(stored if stored.is_absolute() else root / stored)
        parts = stored.parts
        lowered = tuple(part.lower() for part in parts)
        marker = SOURCE_PATH_ROOTS[key]
        for index in range(len(parts) - len(marker) + 1):
            if lowered[index : index + len(marker)] == marker:
                candidates.append(root.joinpath(*parts[index:]))
                break

    filename = str(document["filename"] or "")
    if filename:
        source_name = Path(filename).name
        if key == "pdf_path":
            source_name = str(Path(source_name).with_suffix(".pdf"))
        elif key == "txt_path":
            source_name = str(Path(source_name).with_suffix(".txt"))
        elif key == "grid_path":
            source_name = str(Path(source_name).with_suffix(".csv"))
        elif key == "image_dir":
            source_name = Path(source_name).stem
        candidates.append(root.joinpath(*SOURCE_PATH_ROOTS[key], source_name))

    for candidate in dict.fromkeys(candidates):
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if key == "image_dir" and resolved.is_dir():
            return resolved
        if key != "image_dir" and resolved.is_file():
            return resolved
    return None


def load_catalogue(project_root: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    root = project_root or PROJECT_ROOT
    ledger = _rows(root / "data-gathering" / "source_ledger.csv")
    routing = {row["file_id"]: row for row in _rows(root / "data/schemas/EXTRACTION-ROUTING.csv")}
    types = {row["doc_type"] for row in _rows(root / "data-gathering" / "document-types.csv") if row.get("doc_type")}
    warnings: list[str] = []
    documents: list[dict[str, Any]] = []
    for row in ledger:
        file_id = row["file_id"]
        route = routing.get(file_id)
        filename = row["filename"]
        txt = root / "data/documents/txt" / filename.replace(".pdf", ".txt")
        pdf = root / "data/documents/pdf" / filename
        grid = root / "data/documents/grids" / filename.replace(".pdf", ".csv")
        images = root / "data/documents/images" / filename.replace(".pdf", "")
        disagreement = ""
        if route:
            if Path(route["txt_path"]).name != txt.name:
                disagreement = "routing txt filename differs from ledger filename"
            if route.get("source_sha256") and row.get("sha256") and route["source_sha256"] != row["sha256"]:
                disagreement = "routing sha256 differs from ledger sha256"
            txt = root / route["txt_path"] if route.get("txt_path") else txt
            pdf = root / route["pdf_path"] if route.get("pdf_path") else pdf
            grid = root / route["grid_path"] if route.get("grid_path") else grid
            images = root / route["image_dir"] if route.get("image_dir") else images
        elif file_id not in routing:
            warnings.append(f"{file_id} is in the ledger and absent from EXTRACTION-ROUTING.csv")
        if row["doc_type"] not in types:
            warnings.append(f"{file_id} uses unknown document type {row['doc_type']}")
            disagreement = disagreement or "unknown document type"
        if disagreement:
            warnings.append(f"{file_id}: {disagreement}")
        page_count = int(float(row["page_count"] or 0))
        text_state = "native" if row.get("has_text_layer", "").lower() == "true" else "missing"
        if txt.is_file() and txt.stat().st_size == 0:
            text_state = "missing"
        documents.append(
            {
                "file_id": file_id,
                "filename": filename,
                "doc_type": route["canonical_doc_type"] if route else row["doc_type"],
                "source_version": row.get("sha256") or "",
                "page_count": page_count,
                "txt_path": str(txt) if txt.is_file() else "",
                "pdf_path": str(pdf) if pdf.is_file() else "",
                "grid_path": str(grid) if grid.is_file() else "",
                "image_dir": str(images) if images.is_dir() else "",
                "text_state": text_state,
                "index_state": "pending",
                "routing_status": route["routing_status"] if route else "LEDGER_ONLY",
                "disagreement": disagreement,
                "product_tier": route["product_tier"] if route else "",
                "layout_features": row.get("layout_features") or "",
                "ledger_doc_type": row["doc_type"],
            }
        )
    extra = sorted(set(routing) - {row["file_id"] for row in ledger})
    for file_id in extra:
        warnings.append(f"{file_id} is in EXTRACTION-ROUTING.csv and absent from the ledger")
    return documents, warnings
