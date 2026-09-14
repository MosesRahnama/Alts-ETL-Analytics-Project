"""Expansion PDFs enter the corpus; non-PDF natives stay in staging."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data-gathering" / "source_ledger.csv"
PDF_DIR = ROOT / "data" / "documents" / "pdf"
TYPES = ROOT / "data-gathering" / "document-types.csv"
TARGETS = ROOT / "Expansion" / "Data" / "Expansion-Data-Scrape-validated" / "validated-acquisition-targets.csv"
MANIFEST = ROOT / "Expansion" / "Data" / "03-acquisition" / "download-manifest.csv"
ADMISSION = ROOT / "Expansion" / "Data" / "04-admission" / "admission-ledger.csv"
MERGE = ROOT / "Expansion" / "Data" / "04-admission" / "reviewed-merge-rows.json"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_canonical_corpus_includes_the_admitted_pdfs() -> None:
    ledger = _rows(LEDGER)
    pdfs = {path.name for path in PDF_DIR.glob("*.pdf")}
    types = {row["doc_type"] for row in _rows(TYPES) if row.get("doc_type")}
    assert len(ledger) == 452
    assert {row["filename"] for row in ledger} == pdfs
    assert len(types) == 20
    assert {"Secondary_Pricing", "Continuation_Fund", "Portfolio_Company_Report"} <= types
    assert {row["doc_type"] for row in ledger} <= types
    assert sum(int(float(row["page_count"])) for row in ledger) == 40965
    admitted = {
        "Secondary_Pricing_Lazard_Interim_2026.pdf",
        "Secondary_Pricing_Lazard_2025.pdf",
        "Secondary_Pricing_Lazard_2024.pdf",
        "Secondary_Pricing_Lazard_Interim_2024.pdf",
        "Secondary_Pricing_Evercore_PCA_2025.pdf",
        "Continuation_Fund_ILPA_Considerations_2023.pdf",
        "Continuation_Fund_ILPA_Disclosure_Mock_Multi_Asset.pdf",
        "Continuation_Fund_ILPA_Disclosure_Mock_Single_Asset.pdf",
        "Capital_Call_ILPA_Template_Definitions.pdf",
        "Capital_Call_ILPA_Suggested_Guidance_2025.pdf",
    }
    assert admitted <= pdfs


def test_expansion_native_receipts_cover_the_validated_queue() -> None:
    targets = _rows(TARGETS)
    manifest = _rows(MANIFEST)
    assert len(targets) == 31
    assert len(manifest) == 31
    assert {row["filename"] for row in targets} == {row["filename"] for row in manifest}
    assert Counter(row["download_status"] for row in manifest)["FAILED"] == 0
    assert all(row["sha256"] and row["magic_ok"] == "TRUE" for row in manifest)
    for row in manifest:
        path = ROOT / row["native_path"]
        assert path.is_file()
        assert path.stat().st_size == int(row["bytes"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == row["sha256"]


def test_non_pdf_expansion_natives_stay_out_of_the_corpus() -> None:
    pdfs = {path.name for path in PDF_DIR.glob("*.pdf")}
    admission = _rows(ADMISSION)
    non_pdf = [row for row in admission if row["native_file_ext"] != "pdf"]
    assert len(non_pdf) == 21
    assert not {row["filename"] for row in non_pdf} & pdfs
    assert MERGE.is_file()
