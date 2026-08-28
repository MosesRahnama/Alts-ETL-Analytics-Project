# Review files

[`dashboard.html`](../dashboard.html) lists the published extraction, fund model, controls, and analytics. Its tables define each row and column and cite the underlying file.

## Review areas

| Area | Artifact | Evidence |
|---|---|---|
| Data groups | [`README.md`](../README.md), [`docs/STATUS.md`](../docs/STATUS.md) | Source observations, the completed fund model, and the separate regression fixture |
| Extraction results | [`document-summary.csv`](../data/extracted/review/document-summary.csv) | 29 documents, A/B rows, physical pairs, agreement, conflicts, decisions, and final rows |
| Observation origin record | [`trace-sample.csv`](../data/extracted/review/trace-sample.csv), [`observation-lineage.csv`](../data/extracted/review/observation-lineage.csv) | A printed value through both proposals, comparison, resolution, final row, and fact row |
| Fund periods | [`reviewer-fund-periods.csv`](../data/extracted/review/reviewer-fund-periods.csv) | `EXTRACTED` and `SYNTHETIC` periods separated by the origin column |
| Completion | [`reviewer-cell-lineage.csv`](../data/extracted/review/reviewer-cell-lineage.csv), [`reviewer-gap-ledger.csv`](../data/extracted/review/reviewer-gap-ledger.csv) | Source, formula, or parameter for each added cell |
| Source-only analytics | [`fund_metrics.csv`](../data/extracted/fund-level/fund_metrics.csv) | 804 multiples on 268 printed periods, all `EXTRACTED` |
| Completed analytics | [`fund_metrics.csv`](../data/csv/fund_metrics.csv), [`pme_results.csv`](../data/csv/pme_results.csv) | 3,736 metrics and 1,868 PME rows, all `SYNTHETIC` |
| Release audit | [`FINAL-RELEASE-AUDIT.csv`](../docs/FINAL-RELEASE-AUDIT.csv) | 25 entries: four upstream controls, 19 rebuild stages, and two closing checks |

## Observation origin record

| Layer | Link |
|---|---|
| Sample | `trace-sample.csv` identifies selected `observation_id` values |
| Extraction comparison | `observation-lineage.csv` joins each ID to the A/B proposals, pair, resolution, and final paths and rows |
| Published evidence | `fact_observation.csv` retains the same ID, source location, value, unit, and quote |
| Verification fields | File ID, source hash, physical page, table, row, column, occurrence, value, unit, and quote |

## Release checks

| Command | Result |
|---|---|
| `python -m src.pipeline.publish_review_release` | Runs 19 data-changing stages and records one receipt per stage |
| `python -m src.pipeline.reviewer_check` | Verifies rows are kept, origin records, financial results, database parity, and disclosed review items |
| `python -m pytest -q` | Runs the test suite |
| `python -m src.repository.check_project_structure --verify-hashes` | Verifies folder guides, the manifest, and source hashes |
| `python -m src.catalog.simple_pdf_extraction.name_normalization conflicts --strict` | Requires zero identity conflicts |
| `python -m src.pipeline.build_extraction_review --check` | Confirms that the review tables match the working tree |

## Data groups

| Population | Location | Content |
|---|---|---|
| Source observations | `data/extracted/tables/`, `extracted.duckdb` | One row per printed value, with page, quote, agents, and decision |
| Fund model | `data/csv/`, `alts.duckdb` | Promoted printed rows labelled `EXTRACTED` beside completion rows labelled `SYNTHETIC`, on the same fund IDs, with cell fill records |
| Regression fixture | `data/synthetic/`, `alts_mock.duckdb` | 800 generated funds for rule and generator tests; they share only the table shapes |

DPI, RVPI, and TVPI derive from printed fund periods. XIRR, KS-PME, and Direct Alpha require dated cash flows; the filled fund-date table supplies those flows and labels the results `SYNTHETIC`.

Extraction review tables: [`../data/extracted/review/README.md`](../data/extracted/review/README.md).
