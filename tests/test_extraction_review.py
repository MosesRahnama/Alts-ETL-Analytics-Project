from __future__ import annotations

import csv
import io

from src.pipeline import build_extraction_review as review


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_review_outputs_tie_to_published_facts() -> None:
    outputs = review.build_outputs(review.PROJECT_ROOT)
    documents = rows(outputs["document-summary.csv"])
    lineage = rows(outputs["observation-lineage.csv"])
    facts = review.read_rows(review.FACT_PATH)

    published = len(facts)
    assert published > 7_000
    assert len(documents) == 29
    assert sum(int(row["final_rows"]) for row in documents) == published
    assert len(lineage) == published
    assert len({row["observation_id"] for row in lineage}) == published
    assert all(row["source_sha256"] for row in lineage)
    assert all(row["resolution_decision"] for row in lineage)


def test_document_summary_separates_value_and_context_agreement() -> None:
    outputs = review.build_outputs(review.PROJECT_ROOT)
    documents = rows(outputs["document-summary.csv"])

    physical_pairs = sum(int(row["physical_pairs"]) for row in documents)
    value_agreements = sum(int(row["raw_value_agreements"]) for row in documents)
    value_conflicts = sum(int(row["value_conflicts"]) for row in documents)

    assert physical_pairs > 0
    assert value_agreements + value_conflicts == physical_pairs
    assert value_agreements / physical_pairs > 0.90


def test_database_lineage_is_rebuilt_from_the_reviewer_lineage() -> None:
    outputs = review.build_outputs(review.PROJECT_ROOT)
    reviewer_rows = rows(outputs["observation-lineage.csv"])
    table_text = review.table_lineage_text(outputs["observation-lineage.csv"])
    table_rows = rows(table_text)

    assert next(csv.reader(io.StringIO(table_text))) == list(review.TABLE_LINEAGE_COLUMNS)
    assert len(table_rows) == len(reviewer_rows)
    assert {row["observation_id"] for row in table_rows} == {
        row["observation_id"] for row in reviewer_rows
    }
    assert all(row["source_sha256"] for row in table_rows)
    assert all(row["resolution_decision"] != "REJECT" for row in table_rows)
    assert any(row["difference_fields"] for row in table_rows)

    manifest = rows(review.table_manifest_text(review.PROJECT_ROOT, len(table_rows)))
    lineage_entry = [row for row in manifest if row["table"] == "observation_lineage"]
    assert lineage_entry == [
        {
            "table": "observation_lineage",
            "file": "observation_lineage.csv",
            "rows": str(len(table_rows)),
        }
    ]
