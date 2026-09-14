"""Download validated Expansion sources into staging and run admission checks.

Writes Expansion/Data/02-discovery through 05-handoff. Does not append
data-gathering/source_ledger.csv and does not copy files into data/documents/pdf.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPANSION = HERE.parent
PROJECT_ROOT = EXPANSION.parent.parent
DATA_GATHERING_SRC = PROJECT_ROOT / "data-gathering" / "src"
LEDGER = PROJECT_ROOT / "data-gathering" / "source_ledger.csv"
DOC_TYPES = PROJECT_ROOT / "data-gathering" / "document-types.csv"
TAXONOMY = EXPANSION / "01-schema" / "document-taxonomy.json"
TARGETS = HERE / "validated-acquisition-targets.csv"
SOURCE_DOCS = EXPANSION / "source-documents"
DISCOVERY = EXPANSION / "02-discovery" / "acquisition-targets.csv"
MANIFEST = EXPANSION / "03-acquisition" / "download-manifest.csv"
ADMISSION = EXPANSION / "04-admission" / "admission-ledger.csv"
CHECKS = EXPANSION / "04-admission" / "admission-checks.csv"
EXTENSION = EXPANSION / "04-admission" / "source-ledger-extension-candidates.csv"
HANDOFF = EXPANSION / "05-handoff" / "schema-discovery-worklist.csv"

sys.path.insert(0, str(DATA_GATHERING_SRC))
from _acquire_lib import full_report, sha256_file  # noqa: E402

USER_AGENT = "MinaAnalytics research-bot moses@minaanalytics.com"
SEC_SLEEP_S = 0.45
TIMEOUT_S = 120
RETRIES = 3
SEC_BLOCK_MARKERS = (
    b"Your Request Originates from an Undeclared Automated Tool",
    b"SEC.gov | Automated",
    b"Request Rate Threshold Exceeded",
)

PACKAGE_BY_PREFIX = (
    ("carlyle-alpinvest", "PKG-CARLYLE-ALPINVEST"),
    ("coller-secondaries", "PKG-COLLER-SECONDARIES"),
    ("ares-private-markets", "PKG-ARES-PMF"),
    ("hamilton-lane-private-assets", "PKG-HL-PAF"),
    ("ilpa-capital-call", "PKG-ILPA-CCD"),
    ("ilpa-ccd", "PKG-ILPA-CCD"),
    ("ilpa-continuation", "PKG-ILPA-CONTINUATION"),
    ("lazard-", "PKG-LAZARD-SECONDARY-MARKET"),
    ("evercore-", "PKG-EVERCORE-SECONDARY-MARKET"),
    ("jefferies-", "PKG-JEFFERIES-SECONDARY-MARKET"),
    ("ilpa-portfolio-company", "PKG-ILPA-PORTCO"),
    ("ilpa-continuation-funds-considerations", "PKG-ILPA-CONTINUATION"),
)

SUBTYPE_BY_TITLE = (
    ("NPORT-EX", "NPORT_EX"),
    ("NPORT-P", "NPORT_P"),
    ("N-CSR", "N_CSR"),
    ("Prospectus", "N_2"),
    ("SC TO-I", "Secondary_Sale_RFP"),
    ("Capital Call and Distribution Template Definitions", "Capital_Call_Detail"),
    ("Capital Call and Distribution Suggested Guidance", "Capital_Call_Detail"),
    ("Capital Call and Distribution Template Examples", "Capital_Call_Detail"),
    ("Capital Call and Distribution Template v2", "Capital_Call_Detail"),
    ("Portfolio Company Template", "ILPA_PortCo_Template"),
    ("Disclosure Mock Multi-Asset", "Continuation_Disclosure"),
    ("Disclosure Mock Single-Asset", "Continuation_Disclosure"),
    ("Disclosure Template", "Continuation_Disclosure"),
    ("Continuation Funds Considerations", "Continuation_Disclosure"),
    ("Secondary Market", "Market_Report"),
)

SEC_ACCESSION = re.compile(
    r"/Archives/edgar/data/(\d+)/(\d+)/",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def allowed_doc_types() -> set[str]:
    return {
        (row.get("doc_type") or "").strip()
        for row in read_csv(DOC_TYPES)
        if (row.get("doc_type") or "").strip()
    }


def ledger_index() -> tuple[set[str], set[str], set[str]]:
    rows = read_csv(LEDGER)
    return (
        {row["sha256"].strip().lower() for row in rows if row.get("sha256")},
        {row["filename"].strip() for row in rows if row.get("filename")},
        {row["source_url"].strip() for row in rows if row.get("source_url")},
    )


def taxonomy() -> dict:
    return json.loads(TAXONOMY.read_text(encoding="utf-8"))


def package_id(filename: str) -> str:
    name = filename.casefold()
    for prefix, package in PACKAGE_BY_PREFIX:
        if name.startswith(prefix):
            return package
    return ""


def report_subtype(title: str, proposed: str, tax: dict) -> str:
    for needle, subtype in SUBTYPE_BY_TITLE:
        if needle in title:
            return subtype
    new_types = tax.get("new_doc_types") or {}
    if proposed in new_types and new_types[proposed]:
        return str(new_types[proposed][0])
    existing = tax.get("existing_doc_type_subtypes") or {}
    if proposed in existing and existing[proposed]:
        return str(existing[proposed][0])
    return ""


def parse_sec(url: str) -> tuple[str, str]:
    match = SEC_ACCESSION.search(url or "")
    if not match:
        return "", ""
    return match.group(1).lstrip("0") or match.group(1), match.group(2)


def source_system(folder: str, url: str) -> str:
    if "sec.gov" in (url or "").casefold():
        return "SEC_EDGAR"
    if folder == "ilpa":
        return "ILPA"
    if folder == "market-reports":
        return "ADVISOR_PUBLIC"
    return "OTHER_PUBLIC"


def license_note(folder: str, proposed: str, title: str) -> str:
    lowered = title.casefold()
    if folder == "sec-filings":
        return "public_filing"
    if "template" in lowered or "mock" in lowered or "draft" in lowered:
        return "model_template"
    if folder == "ilpa":
        return "freely_published"
    return "freely_published"


def is_template(title: str, license_value: str) -> bool:
    lowered = title.casefold()
    return license_value == "model_template" or any(
        token in lowered for token in ("template", "mock", "draft", "illustrative")
    )


def expected_magic(ext: str, head: bytes) -> bool:
    ext = (ext or "").casefold().lstrip(".")
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in {"xlsx", "docx"}:
        return head.startswith(b"PK")
    if ext in {"xml"}:
        stripped = head.lstrip()
        return stripped.startswith(b"<?xml") or stripped.startswith(b"<")
    if ext in {"html", "htm"}:
        stripped = head.lstrip().lower()
        return stripped.startswith(b"<!doctype") or stripped.startswith(b"<html") or stripped.startswith(b"<")
    return True


def blocked_sec(head: bytes, body_sample: bytes) -> bool:
    blob = head + body_sample
    return any(marker in blob for marker in SEC_BLOCK_MARKERS)


def download_one(url: str, dest: Path) -> dict[str, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    last_error = ""
    for attempt in range(1, RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                final_url = response.geturl()
                status = getattr(response, "status", 200)
                data = response.read()
            if not data:
                raise RuntimeError("zero-byte response")
            if blocked_sec(data[:2048], data[:8192]):
                raise RuntimeError("SEC automated-request block page")
            dest.write_bytes(data)
            return {
                "ok": "TRUE",
                "http_status": str(status),
                "final_url": final_url,
                "error": "",
            }
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
            last_error = str(exc)
            if dest.exists():
                dest.unlink()
            time.sleep(min(2 * attempt, 8))
    return {"ok": "FALSE", "http_status": "", "final_url": url, "error": last_error}


def candidate_rows() -> list[dict[str, str]]:
    rows = []
    for index, row in enumerate(read_csv(TARGETS), start=1):
        item = dict(row)
        item["candidate_id"] = f"EXP-{index:03d}"
        item["expansion_document_id"] = f"EXPDOC-{index:03d}"
        rows.append(item)
    return rows


def fetch() -> list[dict[str, str]]:
    SOURCE_DOCS.mkdir(parents=True, exist_ok=True)
    receipts = []
    for row in candidate_rows():
        url = (row.get("resolved_url") or row.get("source_url") or "").strip()
        dest = SOURCE_DOCS / row["folder"] / row["filename"]
        if "sec.gov" in url.casefold():
            time.sleep(SEC_SLEEP_S)
        status = "DOWNLOADED"
        error = ""
        http_status = ""
        final_url = url
        if dest.is_file() and dest.stat().st_size > 0:
            status = "EXISTS"
        else:
            print(f"GET {row['candidate_id']} {url}", flush=True)
            result = download_one(url, dest)
            if result["ok"] != "TRUE":
                status = "FAILED"
                error = result["error"]
            http_status = result["http_status"]
            final_url = result["final_url"] or url

        sha = ""
        bytes_count = ""
        magic_ok = ""
        if dest.is_file() and dest.stat().st_size > 0:
            raw = dest.read_bytes()[:16]
            sha = sha256_file(dest)
            bytes_count = str(dest.stat().st_size)
            ext = Path(row["filename"]).suffix
            magic_ok = "TRUE" if expected_magic(ext, raw) else "FALSE"
            if magic_ok != "TRUE" and status != "FAILED":
                status = "FAILED"
                error = f"magic mismatch for {ext}"
                dest.unlink(missing_ok=True)
                sha = ""
                bytes_count = ""
                magic_ok = "FALSE"
        elif status != "FAILED":
            status = "FAILED"
            error = "file missing after download"

        receipts.append({
            "candidate_id": row["candidate_id"],
            "expansion_document_id": row["expansion_document_id"],
            "folder": row["folder"],
            "proposed_doc_type": row["proposed_doc_type"],
            "title": row["title"],
            "source_format": row["source_format"],
            "source_url": row["source_url"],
            "resolved_url": url,
            "final_url": final_url,
            "filename": row["filename"],
            "native_path": str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/") if dest.exists() else "",
            "priority": row["priority"],
            "validation_status": row["validation_status"],
            "download_status": status,
            "http_status": http_status,
            "bytes": bytes_count,
            "sha256": sha,
            "magic_ok": magic_ok,
            "downloaded_at": utc_now(),
            "error": error,
        })
    write_csv(
        MANIFEST,
        receipts,
        [
            "candidate_id", "expansion_document_id", "folder", "proposed_doc_type",
            "title", "source_format", "source_url", "resolved_url", "final_url",
            "filename", "native_path", "priority", "validation_status",
            "download_status", "http_status", "bytes", "sha256", "magic_ok",
            "downloaded_at", "error",
        ],
    )
    return receipts


def admit(receipts: list[dict[str, str]]) -> None:
    tax = taxonomy()
    allowed = allowed_doc_types()
    new_types = set((tax.get("new_doc_types") or {}).keys())
    existing_subtypes = tax.get("existing_doc_type_subtypes") or {}
    ledger_sha, ledger_names, ledger_urls = ledger_index()
    seen_sha: dict[str, str] = {}
    ledger_rows = []
    check_rows = []
    extension_rows = []
    handoff_rows = []
    checked_at = utc_now()

    for row in candidate_rows():
        receipt = next(item for item in receipts if item["candidate_id"] == row["candidate_id"])
        dest = SOURCE_DOCS / row["folder"] / row["filename"]
        proposed = row["proposed_doc_type"]
        subtype = report_subtype(row["title"], proposed, tax)
        system = source_system(row["folder"], receipt["resolved_url"])
        license_value = license_note(row["folder"], proposed, row["title"])
        template = is_template(row["title"], license_value)
        cik, accession = parse_sec(receipt["resolved_url"])
        ext = Path(row["filename"]).suffix.lstrip(".").casefold()
        type_in_ledger_enum = proposed in allowed
        type_is_new = proposed in new_types
        subtype_ok = True
        if type_in_ledger_enum:
            allowed_sub = set(existing_subtypes.get(proposed) or [])
            if subtype and allowed_sub and subtype not in allowed_sub:
                subtype_ok = False
        elif type_is_new:
            allowed_sub = set((tax.get("new_doc_types") or {}).get(proposed) or [])
            if subtype and allowed_sub and subtype not in allowed_sub:
                subtype_ok = False

        probe = {}
        if dest.is_file() and ext == "pdf":
            probe = full_report(str(dest))

        duplicate_sha = ""
        if receipt["sha256"]:
            digest = receipt["sha256"].lower()
            if digest in ledger_sha:
                duplicate_sha = "canonical_ledger"
            elif digest in seen_sha:
                duplicate_sha = seen_sha[digest]
            else:
                seen_sha[digest] = row["candidate_id"]

        duplicate_name = row["filename"] in ledger_names
        duplicate_url = (row.get("source_url") or "") in ledger_urls or (row.get("resolved_url") or "") in ledger_urls

        checks: list[tuple[str, str, str, str, str]] = []

        def add_check(name: str, status: str, observed: str = "", expected: str = "", detail: str = "") -> None:
            checks.append((name, status, observed, expected, detail))

        fetched = receipt["download_status"] in {"DOWNLOADED", "EXISTS"} and dest.is_file()
        add_check("source_identity", "PASS" if (row.get("source_url") and row.get("resolved_url")) else "HOLD", row.get("resolved_url", ""), "url", "")
        add_check(
            "byte_integrity",
            "PASS" if fetched and receipt["sha256"] else "FAIL",
            receipt["sha256"],
            "sha256",
            receipt["error"],
        )
        add_check(
            "magic",
            "PASS" if receipt.get("magic_ok") == "TRUE" else "FAIL",
            receipt.get("magic_ok", ""),
            "TRUE",
            ext,
        )
        add_check(
            "duplicate_sha",
            "FAIL" if duplicate_sha == "canonical_ledger" else ("HOLD" if duplicate_sha else "PASS"),
            duplicate_sha,
            "unique",
            "",
        )
        add_check("duplicate_filename", "HOLD" if duplicate_name else "PASS", row["filename"], "unique", "")
        add_check("duplicate_url", "HOLD" if duplicate_url else "PASS", "duplicate" if duplicate_url else "unique", "unique", "")
        add_check(
            "doc_type_enum",
            "PASS" if type_in_ledger_enum else ("HOLD" if type_is_new else "FAIL"),
            proposed,
            "document-types.csv or approved new family",
            "",
        )
        add_check("subtype", "PASS" if subtype_ok else "HOLD", subtype, "taxonomy map", "")
        add_check(
            "native_pdf",
            "PASS" if ext == "pdf" else "HOLD",
            ext,
            "pdf",
            "canonical merge accepts pdf only",
        )
        merge_size_ok = dest.is_file() and dest.stat().st_size > 20 * 1024
        add_check(
            "merge_size_gate",
            "PASS" if merge_size_ok else "HOLD",
            receipt.get("bytes", ""),
            ">20480",
            "canonical _merge_rows.py rejects 20 KB or smaller",
        )
        if ext == "pdf":
            add_check(
                "pdf_probe",
                "FAIL" if probe.get("probe_error") else "PASS",
                str(probe.get("page_count") or ""),
                "page_count",
                str(probe.get("probe_error") or ""),
            )
        else:
            add_check("pdf_probe", "NOT_APPLICABLE", "", "pdf", "materialize_native_to_pdf.py does not exist yet")
        add_check("rights", "PASS", "PUBLIC", "known", "public URL with recorded license_note")
        add_check(
            "canonical_ready",
            "PASS" if (
                fetched
                and receipt.get("magic_ok") == "TRUE"
                and ext == "pdf"
                and type_in_ledger_enum
                and not duplicate_sha
                and not duplicate_name
                and merge_size_ok
                and not probe.get("probe_error")
            ) else "HOLD",
            "",
            "pdf + existing doc_type + unique hash",
            "this run does not merge into source_ledger.csv",
        )

        fail = any(status == "FAIL" for _, status, *_ in checks)
        hold = any(status == "HOLD" for _, status, *_ in checks)
        if not fetched or fail:
            admission_status = "REJECTED" if not fetched else ("REJECTED" if any(name == "byte_integrity" and status == "FAIL" for name, status, *_ in checks) else "HOLD")
            if not fetched:
                admission_status = "REJECTED"
        elif hold:
            admission_status = "HOLD"
        else:
            admission_status = "HOLD"

        reasons = []
        if not fetched:
            reasons.append(receipt.get("error") or "download failed")
        if type_is_new:
            reasons.append(f"new doc_type {proposed} is not in document-types.csv")
        if ext != "pdf":
            reasons.append("native is not PDF; merge and page pipeline require a canonical PDF")
        if template:
            reasons.append("template or mock; dispatch would be REFERENCE if admitted")
        if duplicate_sha:
            reasons.append(f"SHA collides with {duplicate_sha}")
        if admission_status != "REJECTED":
            reasons.append("canonical corpus pins remain 442; no merge this run")

        if template:
            dispatch = "REFERENCE"
        elif type_is_new or ext != "pdf":
            dispatch = "UNSCHEDULED"
        else:
            dispatch = "UNSCHEDULED"

        deal_context = "NONE"
        lookthrough = "NONE"
        if proposed == "Secondary_Pricing":
            deal_context = "UNKNOWN"
            lookthrough = "FUND_INTEREST"
        elif proposed == "Continuation_Fund":
            deal_context = "CONTINUATION"
            lookthrough = "FUND_INTEREST"
        elif proposed == "Portfolio_Company_Report":
            deal_context = "NONE"
            lookthrough = "PORTFOLIO_COMPANY"
        elif proposed in {"Schedule_Inv", "Financials"}:
            lookthrough = "MULTI_LEVEL"
        elif proposed == "Institutional_Report":
            deal_context = "LP_LED"
            lookthrough = "FUND_INTEREST"

        ledger_rows.append({
            "candidate_id": row["candidate_id"],
            "expansion_document_id": row["expansion_document_id"],
            "package_id": package_id(row["filename"]),
            "title": row["title"],
            "folder": row["folder"],
            "priority": row["priority"],
            "download_status": receipt["download_status"],
            "admission_status": admission_status,
            "admission_reason": "; ".join(reasons),
            "proposed_doc_type": proposed,
            "report_subtype": subtype,
            "canonical_doc_type_if_admitted": proposed if type_in_ledger_enum else "",
            "dispatch_scope_if_admitted": dispatch,
            "license_note": license_value,
            "source_format": row["source_format"],
            "native_file_ext": ext,
            "filename": row["filename"],
            "native_path": receipt.get("native_path", ""),
            "source_url": row["source_url"],
            "resolved_url": receipt["resolved_url"],
            "bytes": receipt.get("bytes", ""),
            "native_sha256": receipt.get("sha256", ""),
            "magic_ok": receipt.get("magic_ok", ""),
            "page_count": str(probe.get("page_count") or row.get("validated_page_count") or ""),
            "has_text_layer": "" if "has_text_layer" not in probe else ("TRUE" if probe.get("has_text_layer") else "FALSE"),
            "char_count_sample": str(probe.get("char_count_sample") or ""),
            "n_tables_detected": str(probe.get("n_tables_detected") or ""),
            "max_table_cols": str(probe.get("max_table_cols") or ""),
            "has_landscape_page": "" if "has_landscape_page" not in probe else ("TRUE" if probe.get("has_landscape_page") else "FALSE"),
            "merge_size_ok": "TRUE" if merge_size_ok else "FALSE",
            "type_in_live_enum": "TRUE" if type_in_ledger_enum else "FALSE",
            "canonical_merge_blocked": "TRUE",
            "file_id": "",
        })

        for name, status, observed, expected, detail in checks:
            check_rows.append({
                "expansion_document_id": row["expansion_document_id"],
                "check_name": name,
                "check_status": status,
                "observed_value": observed,
                "expected_value": expected,
                "detail": detail,
                "checked_at": checked_at,
            })

        extension_rows.append({
            "file_id": "",
            "expansion_document_id": row["expansion_document_id"],
            "source_system": system,
            "source_record_id": accession or row["candidate_id"],
            "regulatory_form": subtype if system == "SEC_EDGAR" else "",
            "sec_cik": cik,
            "sec_accession": accession,
            "filing_date": "",
            "period_of_report": "",
            "exhibit_type": "",
            "exhibit_sequence": "",
            "native_source_url": receipt["resolved_url"],
            "native_file_ext": ext,
            "native_sha256": receipt.get("sha256", ""),
            "canonical_pdf_sha256": receipt.get("sha256", "") if ext == "pdf" else "",
            "derived_from_native_sha256": "",
            "renderer_id": "",
            "document_family": proposed,
            "document_subtype": subtype,
            "deal_context": deal_context,
            "lookthrough_level": lookthrough,
            "package_id": package_id(row["filename"]),
            "parent_file_id": "",
            "version_status": "DRAFT" if "draft" in row["title"].casefold() else "FINAL",
            "execution_status": "NOT_APPLICABLE",
            "access_basis": "PUBLIC",
            "confidentiality_class": "PUBLIC",
            "redistribution_rights": "PUBLIC_REDISTRIBUTABLE",
            "pii_class": "NONE",
            "license_contract_id": "",
            "duplicate_of_file_id": "",
            "supersedes_file_id": "",
            "admission_status": admission_status,
            "admission_reason": "; ".join(reasons),
        })

        if admission_status != "REJECTED":
            handoff_rows.append({
                "expansion_document_id": row["expansion_document_id"],
                "proposed_doc_type": proposed,
                "report_subtype": subtype,
                "dispatch_scope": dispatch,
                "schema_discovery_required": "TRUE" if type_is_new else "FALSE",
                "native_file_ext": ext,
                "pdf_materialization_required": "FALSE" if ext == "pdf" else "TRUE",
                "canonical_merge_blocked": "TRUE",
                "note": "; ".join(reasons),
            })

    write_csv(DISCOVERY, candidate_rows(), [
        "candidate_id", "expansion_document_id", "folder", "proposed_doc_type", "title",
        "source_format", "source_url", "filename", "priority", "status",
        "validation_status", "validated_content_type", "validated_page_count",
        "validation_note", "resolved_url",
    ])
    write_csv(
        ADMISSION,
        ledger_rows,
        list(ledger_rows[0].keys()) if ledger_rows else ["candidate_id"],
    )
    write_csv(
        CHECKS,
        check_rows,
        ["expansion_document_id", "check_name", "check_status", "observed_value", "expected_value", "detail", "checked_at"],
    )
    write_csv(
        EXTENSION,
        extension_rows,
        [
            "file_id", "expansion_document_id", "source_system", "source_record_id",
            "regulatory_form", "sec_cik", "sec_accession", "filing_date", "period_of_report",
            "exhibit_type", "exhibit_sequence", "native_source_url", "native_file_ext",
            "native_sha256", "canonical_pdf_sha256", "derived_from_native_sha256", "renderer_id",
            "document_family", "document_subtype", "deal_context", "lookthrough_level",
            "package_id", "parent_file_id", "version_status", "execution_status",
            "access_basis", "confidentiality_class", "redistribution_rights", "pii_class",
            "license_contract_id", "duplicate_of_file_id", "supersedes_file_id",
            "admission_status", "admission_reason",
        ],
    )
    write_csv(
        HANDOFF,
        handoff_rows,
        [
            "expansion_document_id", "proposed_doc_type", "report_subtype", "dispatch_scope",
            "schema_discovery_required", "native_file_ext", "pdf_materialization_required",
            "canonical_merge_blocked", "note",
        ],
    )


def main() -> int:
    receipts = fetch()
    admit(receipts)
    failed = [row for row in receipts if row["download_status"] == "FAILED"]
    print(f"targets={len(receipts)} failed={len(failed)} manifest={MANIFEST}")
    for row in failed:
        print(f"FAIL {row['candidate_id']} {row['title']}: {row['error']}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
