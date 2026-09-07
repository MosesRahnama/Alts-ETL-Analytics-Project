# Release verification

| Check | Result |
|---|---|
| End-to-end data rebuild | All 21 ordered release stages passed |
| Complete process table | Four source-preparation, extraction, and review steps precede 21 automated stages and two closing checks; consecutive display numbers remain separate from execution IDs |
| Check evidence | Generated results cite executed checks and their times; retained A/B proposal checks do not certify the original proposals under later field rules |
| Source preservation | All 8,190 previously published raw and normalized evidence records remain unchanged |
| Closing data checks | 157 passed across current assignments, source attributes, accounting scope, and database contents |
| Active extraction | 36 documents, 693 covered pages, 8,613 evidence records |
| Added documents | SRC373: 226 records and 188 pages; SRC421: 197 records and 135 pages; both final validators passed |
| Source corrections | 3,187 field decisions; SR3185 corrects a tax-line classification, SR3186 resolves the prospectus fund shorthand, and SR3187 restores two printed apostrophes from page 92 |
| Original extraction | A/B proposal values and pairing retained; reviewed changes remain in the correction matrix and resolution files |
| Legal terms | CSV rules provide database-valid clause categories and fund scope; printed narrative and zero values survive promotion; the regression test inserts them under the database constraints |
| Assignment checks | Published, deferred, reference, and unscheduled source IDs reconcile against current worklists |
| Upstream controls | Shared candidate/final omission checks; date, owner, scope, fee, method, definition-reference and complete-number checks; unreadable characters in finals require page-image review |
| Currency | Named denominations govern bare dollar symbols; period rows retain currency; mixed currencies and unconverted foreign completion inputs are refused |
| Source quality | Two negative amounts printed in SRC060 remain flagged |
| Clean regression fixture | 617,849 passing checks; zero failures |
| Planted fixture defects | All 144 detected by their expected rules |
| Analytics | 804 source-only metric rows; 3,780 completed-data metric rows and 1,890 public-market comparison rows, with source classes retained |
| Databases | Both source documents appear in extracted.duckdb; the fund-model database contains the promoted legal terms and rebuilt analytics |
| Dashboard | All 12 sections opened locally; document counts, evidence totals, and agent agreement use the current corpus |
| Regression suite | The recorded repository-and-tests result includes source-error replays, legal-term loading, current assignments, source preservation, and complete release-table checks |
| Repository checks | File and directory counts appear in the recorded repository-and-tests result; structure, manifest, folder guides, and file types are checked for that checkout |

Unpromoted statement, holding, and policy facts remain in the evidence tables; their dispositions distinguish model coverage from extraction failure. Missing source sub-strategy labels remain blank. Demonstration benchmark data retain their usage restrictions.

[Stage evidence](FINAL-RELEASE-AUDIT.csv) · [Transformation records](../ledgers/pipeline/transformation-receipts.csv) · [Current counts](RELEASE-COUNTS.csv) · [Reviewer observations](../data/extracted/review/reviewer-observations.csv) · [Reviewer fund periods](../data/extracted/review/reviewer-fund-periods.csv) · [Correction matrix](../data/normalization/source-review-corrections.csv)
