# Rebuild stages

In release order.

| File | Role |
|---|---|
| `__init__.py` | Pipeline package marker. |
| `publish_review_release.py` | Run release stages 3 to 140 with input/output receipts |
| `release_checks.py` | Record each executed check result, including failed checks and checks without data outputs |
| `combine_extracted_raw.py` | Stage 10: verify and concatenate the approved route files |
| `build_extraction_review.py` | Stage 40: attach A/B and source review references; refresh the published page-image index |
| `build_extracted_database.py` | Flatten, pivot, and load the evidence database in one call |
| `build_integrated_universe.py` | Stages 95 and 100: write the copy taken before fill, then fill gaps on the same fund IDs with a fill record |
| `build_reviewer_publication.py` | Stage 130: publish the flat reviewer files |
| `transformation_lineage.py` | Receipts with input and output SHA-256; prior bytes go to the external archive |
| `reviewer_check.py` | Closing checks for current assignments, source preservation, analytics, and database parity |
| `migration_gate.py` | Compare a migration batch with its prior tag; require all 424 sites to have matrix evidence or a structure disposition |
| `build_calibration_candidates.py` | Retain four single-schedule calibration statistics as audit evidence excluded from release |
| `build_mock_universe.py` | Build the standalone 800-fund regression fixture |
