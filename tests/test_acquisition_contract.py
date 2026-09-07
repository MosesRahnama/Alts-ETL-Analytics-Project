from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACQUISITION = ROOT / "data-gathering" / "src"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_all_acquisition_routes_share_the_pdf_cache() -> None:
    acquire = load_module("acquire_contract", ACQUISITION / "_acquire_lib.py")
    fetch = load_module("fetch_contract", ACQUISITION / "fetch_corpus.py")
    merge = load_module("merge_contract", ACQUISITION / "_merge_rows.py")
    expected = (ROOT / "data" / "documents" / "pdf").resolve()
    assert Path(acquire.CORPUS_ROOT).resolve() == expected
    assert Path(fetch.CORPUS_ROOT).resolve() == expected
    assert Path(merge.CORPUS).resolve() == expected


def test_document_type_contract_is_ledger_derived() -> None:
    merge = load_module("merge_document_types", ACQUISITION / "_merge_rows.py")
    with (ROOT / "data-gathering" / "document-types.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        expected = {row["doc_type"] for row in csv.DictReader(handle)}
    assert len(expected) == 17
    assert merge.valid_doc_types() == expected


def test_fetch_dry_run_never_uses_network(tmp_path: Path) -> None:
    fetch = load_module("fetch_dry_run", ACQUISITION / "fetch_corpus.py")
    fetch.CORPUS_ROOT = str(tmp_path)
    row = {
        "filename": "missing.pdf",
        "source_url": "https://invalid.example/missing.pdf",
        "sha256": "0" * 64,
    }
    assert fetch.fetch_one(row, timeout=1, dry_run=True) == "would_fetch"
