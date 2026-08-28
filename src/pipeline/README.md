# Rebuild stages

In release order.

| File | Role |
|---|---|
| `publish_review_release.py` | Run stages 10 to 140 and write one receipt per command |
| `combine_extracted_raw.py` | Stage 10: verify and concatenate the adjudicated route files |
| `build_extraction_review.py` | Stage 40: attach A/B pair and third-reader origin records to each published observation |
| `build_extracted_database.py` | Flatten, pivot, and load the evidence database in one call |
| `build_integrated_universe.py` | Stages 95 and 100: write the copy taken before fill, then fill gaps on the same fund IDs with a fill record |
| `build_reviewer_publication.py` | Stage 130: publish the flat reviewer files |
| `transformation_lineage.py` | Receipts with input and output SHA-256; prior bytes go to the external archive |
| `reviewer_check.py` | Close: the 144 release checks |
| `build_calibration_candidates.py` | Retain four single-schedule calibration statistics as audit evidence excluded from release |
| `build_mock_universe.py` | Build the standalone 800-fund regression fixture |
