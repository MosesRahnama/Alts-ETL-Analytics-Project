"""What each table is and what each column means, for the dashboard.

Every table the page shows carries a description of what one row is and
where the rows came from, and every column carries a definition a reader can
hover on. The definitions are keyed by column name, with a `table.column` key
where one name means something different in one table. A test asserts that
every column on the page resolves here, so a new column cannot reach a
reviewer undefined.
"""

from __future__ import annotations


# ---------------------------------------------------------------- tables

TABLE_NOTES: dict[str, str] = {
    # corpus
    "data-gathering/source_ledger.csv": (
        "One row per public PDF. It records who published the report, what type of report it is, "
        "the covered period, page count, source address, and reuse note. The file_id links the PDF "
        "to its extraction and review records."
    ),
    "data/documents/txt/MANIFEST.csv": (
        "One row per report read to text. Pages with a text layer went through pdfplumber; "
        "Pages with empty stored text went through RapidOCR on the page picture."
    ),
    # extraction
    "data/extracted/review/document-summary.csv": (
        "One row per reviewed PDF. It counts the fields each reader typed, "
        "how many matched or clashed, and which decisions produced the kept evidence."
    ),
    "data/extracted/tables/observation_lineage.csv": (
        "One row per retained PDF field. It identifies Extractor A's proposal, Extractor B's "
        "proposal, their difference, and the review decision that produced the evidence row."
    ),
    "data/extracted/tables/fact_observation.csv": (
        "One row per field retained from a PDF, such as NAV, TVPI, a fund name, a date, or a legal "
        "term. The row records the subject, value, page, table position, quote, and review outcome."
    ),
    "data/extracted/review/reviewer-observations.csv": (
        "One row per retained PDF field, joined to its extractor proposals, review decision, resolved "
        "fund identity, inherited attributes, quality results, and analytical links."
    ),
    "data/extracted/review/reviewer-fund-periods.csv": (
        "One row per fund and date, with field origins, attribute sources, quality results, and "
        "reported and recomputed performance measures."
    ),
    # schema
    "data/schemas/EXTRACTION-RECORD-FAMILIES.csv": (
        "One row per allowed kind of PDF table line, such as a capital-account line, holding, "
        "allocation, or cash flow. The category keeps the line's role. The measure name states the quantity."
    ),
    "data/schemas/EXTRACTION-METRIC-CATEGORIES.csv": (
        "One row per approved field label. Metric labels identify numeric measures; term labels "
        "identify legal or policy provisions. A label off the list stays out of the kept files. "
        "A shared name such as return still follows the method printed on that report."
    ),
    "data/schemas/EXTRACTION-DOC-TYPE-MAP.csv": (
        "One row per report type, naming its reading steps, the line kinds those steps may write, "
        "and the fields those steps leave out."
    ),
    "data/schemas/EXTRACTION-ROUTING.csv": (
        "One row per catalogued PDF, showing its assigned extraction workflow and the reason for "
        "that assignment. Reports outside the available workflows remain listed with that status."
    ),
    # fund model
    "data/csv/fund_master.csv": (
        "One row per standardized fund, including manager, strategy, vintage, currency, size, and "
        "status. PDF-reported attributes are retained; missing attributes are added with a separate "
        "origin label and value-lineage row."
    ),
    "data/csv/fund_periods.csv": (
        "One performance row per fund or LP position and date, containing commitment, paid-in "
        "capital, distributions, NAV, multiples, and IRR where available. EXTRACTED rows use only "
        "PDF evidence; SYNTHETIC rows are added on the same fund IDs for demonstration analytics."
    ),
    "data/csv/fund_cashflows.csv": (
        "One dated cash flow per row. A capital call is negative to the investor and a "
        "distribution positive; that sign convention is what the IRR and PME calculations rely on."
    ),
    "data/csv/fund_terms.csv": (
        "One economic term set per fund: management fee, carry, hurdle, catch-up, waterfall, "
        "and fund life. All rows are made. The published legal papers name the fund only as the Fund."
    ),
    "data/csv/fund_holdings.csv": (
        "One holding per fund, asset, and date, with cost and fair value. Printed holdings come "
        "from schedules of investments. Made holdings fill empty cells on the same fund IDs."
    ),
    "data/csv/fund_metrics.csv": (
        "One calculated measure per period: DPI, RVPI, TVPI, and XIRR. Each row names the "
        "formula that produced it and the record IDs it read, so the number can be recomputed."
    ),
    "data/csv/pme_results.csv": (
        "One public-market-equivalent result per period and benchmark: the Kaplan-Schoar "
        "multiple and Direct Alpha, each against the SPY proxy series. Row detail lists every "
        "cash flow and benchmark observation used by the calculation."
    ),
    "data/csv/portfolio_allocations.csv": (
        "One target weight per fund in the demonstration portfolio. The method begins with equal "
        "weights and applies the configured minimum and maximum. Volatility and liquidity remain "
        "blank. The PDFs print none."
    ),
    "data/csv/quality_results.csv": (
        "One row per quality rule and one fund record the rule can test, on the filled tables. PASS and FAIL "
        "show the reported value, recomputed value, difference, and tolerance; SKIP names the "
        "required input that was absent."
    ),
    "data/extracted/fund-level/quality_results.csv": (
        "One row per quality rule and one printed fund record the rule can test, before fill."
    ),
    "data/csv/defect_injections.csv": (
        "One deliberate test error per row: the original value, the changed value, and the rule "
        "expected to catch it. These errors exist only in an isolated test copy."
    ),
    "data/csv/synthetic_parameters.csv": (
        "One row per parameter used to complete missing fund data. DERIVED parameters summarize "
        "PDF-reported values; ASSUMED parameters are declared fallbacks with their basis recorded."
    ),
    "data/integrated/cell-lineage.csv": (
        "One row per field value in the completed fund model. It identifies the fund-model row, "
        "column, written value, origin label, and the source or method that produced it."
    ),
    "data/integrated/gap-ledger.csv": (
        "One row per blank the completion filled: what the field held before, what it holds "
        "after, and how the fill was decided."
    ),
    "data/integrated/reconciliation-results.csv": (
        "One comparison for each PDF-based field carried into the completed fund data. A passing "
        "row confirms the fill left the printed value as it was."
    ),
    "data/integrated/detection-scorecard.csv": (
        "One row per deliberate test-error type, showing how many errors were inserted into the "
        "isolated copy and how many the intended rule detected."
    ),
    "data/integrated/benchmark-policy.csv": (
        "One row for the benchmark used by PME, including its date coverage, reuse-rights status, "
        "and whether it is approved for demonstration or production use."
    ),
    # market
    "data/public_markets/audit/source_file_inventory.csv": (
        "One row per retained market-data file, including its series family, date range, row count, "
        "rights status, and whether it goes into PME or supplies market background."
    ),
    "data/public_markets/audit/source_family_summary.csv": (
        "One row per market-file family in the retained store, showing how many files and rows it holds, "
        "its analytical role, the system the data came from, and its rights status."
    ),
    "data/public_markets/audit/quality_results.csv": (
        "The ten checks on the market package: population, keys, dates, levels, bounds, and the "
        "reconciliation of every return to the two levels it was computed from."
    ),
    "data/public_markets/staging/benchmark_master_candidates.csv": (
        "One row per benchmark series built from the retained files, with its instrument, "
        "return basis, date range, reuse-rights status, and allowed analytical use."
    ),
    # release
    "docs/FINAL-RELEASE-AUDIT.csv": (
        "One row per release stage: the script that ran it, what it read, what it wrote, the "
        "test that guards it, and the result."
    ),
    "ledgers/pipeline/transformation-receipts.csv": (
        "One row per data-changing command, recording its stage, input, output, output row count, "
        "result, and error message if it failed. Checksums remain in row detail as audit metadata."
    ),
    "docs/PROJECT-MANIFEST.csv": (
        "One row per tracked file or folder, showing whether it belongs in the public repository, "
        "which folder guide owns it, and the role it serves. Size and checksum remain in row detail."
    ),
    "costs/extraction-runs.csv": (
        "One row per timed extraction run: the document it read, its page and row counts, the "
        "number of model turns it took, and what it cost. These rows are the basis of the cost law."
    ),
    "docs/CSV-LINEAGE.csv": (
        "One row per CSV in the repository. It names the source CSV, the module that wrote the file, "
        "and any agent operation and instruction file used to create its rows."
    ),
    "src/catalog/simple_pdf_extraction/field_guide.py": (
        "One definition for each of the 42 columns every extractor writes. The dashboard reads the "
        "definitions from the same code that validates extraction files."
    ),
}

# The database explorer keys on the table name inside the database file.
DATABASE_TABLE_NOTES: dict[str, str] = {
    "fact_observation": TABLE_NOTES["data/extracted/tables/fact_observation.csv"],
    "observation_lineage": TABLE_NOTES["data/extracted/tables/observation_lineage.csv"],
    "fact_holding": "One holding per row from a PDF investment schedule, with the evidence-row IDs behind its name, cost, fair value, and other extracted fields.",
    "dim_document": "One row per reviewed PDF, including its document type, extraction route, issuer, page count, and number of evidence rows produced.",
    "dim_page": "One row per physical PDF page. Marks allowed fields, reference material, or a cover or contents page with zero allowed values.",
    "dim_entity": "One row per resolved fund, manager, plan, LP, or company, with its standardized name and entity type.",
    "entity_alias": "One row per spelling of a fund, manager, plan, LP, or company name found in a PDF, linked to its standardized entity where resolved.",
    "dim_metric": "One row per source-row category and field label used by the evidence, with its value type and frequency.",
    "unresolved_names": "A table that must stay empty: printed names that still lack a standard ID. This release has zero rows.",
    "bridge_pivot_observation": "One link from a reconstructed source-table row to each evidence-row ID used to populate it.",
    "fund_master": TABLE_NOTES["data/csv/fund_master.csv"],
    "fund_periods": TABLE_NOTES["data/csv/fund_periods.csv"],
    "fund_cashflows": TABLE_NOTES["data/csv/fund_cashflows.csv"],
    "fund_terms": TABLE_NOTES["data/csv/fund_terms.csv"],
    "fund_term_clauses": "One clause per term set: the printed or generated wording behind a term.",
    "fund_holdings": TABLE_NOTES["data/csv/fund_holdings.csv"],
    "fund_metrics": TABLE_NOTES["data/csv/fund_metrics.csv"],
    "pme_results": TABLE_NOTES["data/csv/pme_results.csv"],
    "portfolio_allocations": TABLE_NOTES["data/csv/portfolio_allocations.csv"],
    "quality_results": TABLE_NOTES["data/csv/quality_results.csv"],
    "defect_injections": TABLE_NOTES["data/csv/defect_injections.csv"],
    "synthetic_parameters": TABLE_NOTES["data/csv/synthetic_parameters.csv"],
    "benchmark_returns": "One dated SPY return per row. DEMO_PROXY_ONLY: the series supports this demo. A live run uses a licensed series.",
    "fund_observations": "One PDF-reported metric per fund, date, and source after identity resolution places it at fund level.",
    "manager_observations": "One PDF-reported metric per manager and date when the source reports at manager level, not fund level.",
    "manager_master": "One row per manager organization identified in the reviewed PDFs.",
    "document_fund_map": "One row per fund named in a PDF, with the page and quote that support the identity.",
    "document_manager_map": "One row per manager named in a PDF, with the page and quote that support the identity.",
    "vw_fund_period_math": "One fund-period row with each stored multiple beside the value recomputed from paid-in capital, distributions, and NAV.",
    "vw_analytics_ready_fund_periods": "Fund-period rows whose status and required fields allow the analytics to use them.",
    "vw_quality_scorecard": "PASS, FAIL, and SKIP counts for each quality rule and pipeline run.",
    "vw_observation_scaled": "Evidence rows with reported numeric values converted from printed thousands or millions into base units.",
    "vw_observation_resolved": "Evidence rows joined to the standardized fund, manager, investor, plan, or company named by the PDF.",
    "vw_manager_coverage": "Fund counts by source-row category and the number with a resolved manager.",
    "vw_document_coverage": "Physical pages, extracted evidence rows, and holdings per reviewed PDF.",
}

# ---------------------------------------------------------------- columns

COLUMN_NOTES: dict[str, str] = {
    # identity and provenance, shared across the fund model
    "fund_id": "The fund's stable identifier. FUND_ prefixed IDs are real funds the extraction identified.",
    "fund_name": "The fund's own name as the corpus prints it, standardized across spellings.",
    "legal_name": "The fund's legal name where a document states one.",
    "fund_manager_id": "Identifier of the general partner or manager.",
    "fund_manager_name": "The general partner or manager, from the printed page or the manager search round.",
    "manager_id": "Identifier of a manager organization, separate from any fund ID.",
    "manager_name": "The manager's printed name.",
    "strategy": "The fund's strategy, such as buyout, venture, or core real estate.",
    "sub_strategy": "A finer strategy label where one is stated.",
    "vintage_year": "The year the fund began investing.",
    "domicile": "The jurisdiction the fund is organized in.",
    "headquarters": "Where the manager is based.",
    "website": "The manager's public site, where recorded.",
    "base_currency": "The currency the fund reports in.",
    "fund_size": "Total committed capital of the fund.",
    "fund_size_currency": "The currency fund_size is stated in.",
    "first_close_date": "Date of the fund's first closing.",
    "final_close_date": "Date of the fund's final closing.",
    "termination_date": "The fund's scheduled end date.",
    "fund_status": "Whether the fund is investing, harvesting, or closed.",
    "provenance_type": "Origin of the value. EXTRACTED: printed on a cited page. DERIVED: copied inside a fund from a printed value. IMPUTED: filled from the median of like printed funds. SYNTHETIC: made from the stated settings. SYNTHETIC periods sit on real FUND_ IDs.",
    "source_document_id": "The source-ledger identifier that links this value to its PDF.",
    "source_page": "The physical page number the value is printed on.",
    "source_anchor": "The quote or locator on that page that carries the value.",
    "source_quote": "The printed words the value was read from.",
    "synthetic_parameter_set_id": "The parameter set a generated row was produced from.",
    "record_status": "ACTIVE rows take part in the analytics; other statuses are retained for review.",
    "created_at": "When the row was written.",
    "formula_id": "The identifier of the calculation that produced the value. The same identifier appears in the code.",
    "input_observation_ids": "The PDF evidence rows used to assemble this fund-period row, listed by observation ID.",
    "input_record_ids": "Every record the calculation read, by ID: the period, its cash flows, and the benchmark observations.",
    "imputation_method": "The method that supplied a fund-model field value absent from the reviewed PDFs.",
    "defect_expected": "TRUE on a row containing a deliberate error in the isolated test copy.",
    "confidence": "The extractor's stated confidence in the row.",
    "notes": "Extra words on the row. Prefixes a checker will see: IMAGE_ONLY (read from the picture), NO_ELIGIBLE_REASON (zero allowed values), and a note that the allowed gap grew with printed rounding.",
    "note": "Free text attached to the row.",
    "extractor_version": "The field-list version the row was read under.",
    # positions and dates
    "fund_period_id": "Identifier of one performance snapshot.",
    "lp_id": "Identifier of the limited partner, where the row is a single investor's position.",
    "lp_name": "The limited partner's printed name.",
    "share_class_name": "The share class, where the row is a class-level figure.",
    "perspective": "Whose figure this is: fund_total, lp_position, or share_class.",
    "date_role": "What the printed date means: as-of, report, period end, or cash-flow date.",
    "date_raw": "The date as the page prints it.",
    "date_precision": "The printed date unit: day, month, quarter, or year.",
    "as_of_date": "The date the values are stated as of.",
    "report_date": "The date the document was issued.",
    "period_start_date": "Start of the period a flow figure covers.",
    "period_end_date": "End of the period a flow figure covers.",
    "effective_date": "The date a term or clause takes effect.",
    "effective_end_date": "The date a term or clause stops applying.",
    "currency": "The currency the amount is stated in.",
    # capital account
    "commitment": "Capital the investor committed to the fund.",
    "paid_in_capital_itd": "Capital drawn from the investor since inception.",
    "distributions_itd": "Capital returned to the investor since inception.",
    "nav": "Net asset value: the manager's valuation of the remaining position.",
    "unfunded_commitment": "Committed capital the fund has yet to draw.",
    "recallable_distributions_itd": "Distributions the fund may call again.",
    "dpi": "Distributions to paid-in: cash returned per unit of cash drawn.",
    "rvpi": "Residual value to paid-in: NAV per unit of cash drawn.",
    "tvpi": "Total value to paid-in: distributions plus NAV, per unit of cash drawn.",
    "reported_irr": "The internal rate of return the document prints.",
    "calculated_irr": "An IRR computed by the pipeline where the document prints none.",
    "beginning_nav": "NAV at the start of the period.",
    "contributions_period": "Capital drawn during the period.",
    "distributions_period": "Capital returned during the period.",
    "realized_gain_period": "Gains on positions sold during the period.",
    "unrealized_gain_period": "Change in value of positions still held.",
    "net_income_period": "Income less expenses for the period.",
    "management_fee_period": "Management fee charged in the period.",
    "other_expenses_period": "Other expenses charged in the period.",
    "ending_nav": "NAV at the end of the period.",
    "period_return": "The return for the period, where printed.",
    "benchmark_return": "The benchmark's return over the same period, where printed.",
    # cash flows
    "cashflow_id": "Identifier of one dated cash flow.",
    "file_id": "The corpus ID of the source document.",
    "cashflow_event_id": "Groups the flows of one event, such as a call and its fee.",
    "cashflow_date": "The date the cash moved.",
    "due_date": "The date a call was due.",
    "cashflow_type": "capital_call, distribution, fee, or return_of_capital.",
    "amount": "The amount in the stated currency. Calls are negative to the investor, distributions positive.",
    "amount_base_currency": "The amount converted to the fund's base currency.",
    "fx_rate": "The rate used for that conversion.",
    "recallable_amount": "The part of a distribution the fund may call again.",
    # analytics
    "analysis_result_id": "Identifier of one calculated result.",
    "entity_id": "The fund or position the result belongs to.",
    "metric_id": "Which measure the row holds: dpi, rvpi, tvpi, xirr, ks_pme, or direct_alpha.",
    "value_numeric": "The calculated value, in the unit the unit column names.",
    "value_text": "A text value, where the measure is not numeric.",
    "value_raw": "The value as the page prints it, with its symbols and separators.",
    "unit": "How to read the value: multiple (times paid-in), decimal_rate (0.02 is 2 percent), currency, or percent.",
    "benchmark_id": "The benchmark the result was computed against.",
    "benchmark_name": "The benchmark's name.",
    "quality_population": "The quality run and outcome the input period passed before it was allowed into the calculation.",
    "return_date": "The date of the benchmark return.",
    "periodicity": "DAILY, MONTHLY, or QUARTERLY.",
    "return_value": "The benchmark return over the period, as a decimal rate.",
    "return_basis": "Price or total return, and whether adjusted.",
    "measure_basis": "Whether the value is a point-in-time balance, a period flow, a ratio, or a rate.",
    "fee_basis": "What a fee rate is charged on.",
    # allocations
    "allocation_id": "Identifier of one allocation row.",
    "portfolio_id": "The portfolio the allocation belongs to.",
    "target_weight": "The weight assigned to the fund, summing to one across the portfolio.",
    "minimum_weight": "The floor the weight was bounded by.",
    "maximum_weight": "The cap the weight was bounded by.",
    "commitment_amount": "The fund's commitment at the allocation date.",
    "nav_amount": "The fund's NAV at the allocation date.",
    "unfunded_amount": "The fund's unfunded commitment at the allocation date.",
    "expected_return": "Blank by design: the corpus prints no forward return.",
    "expected_volatility": "Blank by design: the corpus prints no volatility.",
    "liquidity_score": "Blank by design: the corpus prints no liquidity measure.",
    "optimization_run_id": "The allocation method and version that produced the weights.",
    # terms
    "fund_term_id": "Identifier of one term set.",
    "fund_term_clause_id": "Identifier of one clause.",
    "term_scope": "Whether the terms apply to the whole fund or to one position or class.",
    "overrides_fund_term_id": "The fund-level term set this position-level set overrides.",
    "management_fee_rate": "Annual management fee as a decimal rate.",
    "management_fee_basis": "What the fee is charged on: committed or invested capital.",
    "carry_rate": "The manager's share of profits, as a decimal rate.",
    "hurdle_rate": "The return investors receive before carry begins.",
    "catch_up_rate": "The share of profit the manager takes while catching up to its carry.",
    "catch_up_present": "Whether the waterfall has a catch-up.",
    "waterfall_type": "European (whole fund) or American (deal by deal).",
    "fund_term_years": "The fund's scheduled life in years.",
    "extension_years": "Extensions the manager may take beyond the term.",
    "preferred_return_compounding": "How the hurdle compounds.",
    "expense_cap_rate": "A cap on fund expenses, as a decimal rate, where one applies.",
    "maximum_offering": "The most the fund may raise.",
    "clause_title": "The heading of the clause.",
    # holdings
    "holding_id": "Identifier of one holding snapshot.",
    "portfolio_company_id": "Identifier of the company held.",
    "portfolio_company_name": "The company held, as printed.",
    "instrument_id": "Identifier of the instrument.",
    "instrument_name": "The instrument held: equity, loan, bond.",
    "security_type": "The kind of security.",
    "sector": "The company's sector.",
    "geography": "The geographic scope, as printed.",
    "cost": "What the fund paid for the holding.",
    "fair_value": "The holding's current valuation.",
    "market_value": "The holding's market value, where printed apart from fair value.",
    "principal_amount": "Face value of a debt instrument.",
    "interest_rate": "Coupon or interest rate of a debt instrument.",
    "spread_bps": "Spread over the reference rate, in basis points.",
    "maturity_date": "When a debt instrument matures.",
    "maturity_date_raw": "The maturity date as printed.",
    "ownership_percent": "The fund's ownership share of the company.",
    "notional_amount": "Notional of a derivative position.",
    "quantity": "Units held.",
    "portfolio_weight": "The holding's share of the portfolio.",
    # quality
    "quality_result_id": "Identifier of one rule outcome.",
    "run_id": "Which quality run produced the row.",
    "record_table": "The table the tested record lives in.",
    "record_id": "The tested record's ID.",
    "rule_id": "The rule applied. Its formula is in config/quality_rules.yml.",
    "severity": "error: the row stays out of the fund tables. warning: the row is kept and shown.",
    "status": "The row mark. Use the table-specific status note: PASS, FAIL, SKIP on quality; PASS on receipts; TRACK on the file map.",
    "actual_value": "The value stored on the tested fund record.",
    "expected_value": "The value the rule recomputed from the record's components.",
    "difference": "actual minus expected.",
    "tolerance": "How far actual may sit from expected and still pass. A widened tolerance and its reason appear in the notes.",
    "checked_at": "When the rule ran.",
    "defect_id": "Identifier of one deliberate error in the isolated test copy.",
    "defect_type": "The type of deliberate test error.",
    "field_name": "The fund-model field changed for the test.",
    "clean_value": "The correct value before the deliberate test change.",
    "injected_value": "The incorrect value written into the isolated test copy.",
    "expected_rule_id": "The quality rule expected to detect the deliberate error.",
    "seed": "The reproducibility seed used to choose the test record.",
    "injected": "The number of deliberate errors inserted for this type.",
    "detected": "How many the rule caught.",
    "missed": "How many it did not.",
    "detection_rate": "The share of inserted test errors detected by the intended rule.",
    "check_id": "Identifier of one check.",
    "scope": "What the check covers.",
    "rule": "The check applied.",
    "actual": "The value observed.",
    "expected": "The value required.",
    # parameters
    "parameter_id": "Identifier of one generation parameter.",
    "parameter_set_id": "The set the parameter belongs to.",
    "parameter_name": "What the parameter sets.",
    "assumption_basis": "Where the value came from: a median of printed values, or a declared fallback.",
    "adjudication_status": "Whether the parameter or row has been reviewed and approved.",
    "active": "TRUE where the parameter is in use.",
    # lineage
    "lineage_id": "Identifier of one completed fund-model field value.",
    "target_table": "The fund-model table that received the value.",
    "target_record_id": "The fund-model row that received the value.",
    "target_field": "The column that received the value.",
    "target_value": "The value written.",
    "source_table": "The table from which a DERIVED value was copied.",
    "source_record_id": "The row it was copied from.",
    "precedence": "The order of preference the completion applied: extracted, then derived, then imputed, then generated.",
    "gap_id": "Identifier of one filled blank.",
    "original_value": "What the field held before the completion.",
    "resolution_value": "What it holds after.",
    "resolution_type": "The label the fill carries.",
    # extraction evidence
    "observation_id": "Identifier of one evidence row, representing one field read from one PDF location.",
    "document_id": "The source-ledger ID of the PDF from which the field was read.",
    "canonical_doc_type": "The document's ratified type, settled by two blind typing agents and an audit.",
    "route": "The reading group the document ran through.",
    "product_tier": "CORE: numbers may go into fund tables. SECONDARY: extra facts. REFERENCE: sample form, listed only.",
    "page_id": "Identifier of the physical page.",
    "source_structure_type": "The layout the value came from: TABLE, FIGURE, NARRATIVE, FORM, FOOTNOTE, SCHEDULE, or DOCUMENT.",
    "source_section": "The printed section heading above the table.",
    "source_table": "The printed title of the table.",
    "source_row_label": "The printed row label the value sits on.",
    "source_column_label": "The printed column header the value sits under.",
    "source_occurrence": "Which instance, when the same row and column labels repeat on a page.",
    "record_family": "The kind of source row represented, such as a statement line, holding, allocation, or capital-account line.",
    "metric_category": "What the value measures, from the one vocabulary.",
    "term_category": "For a clause: what kind of provision it is, from the term vocabulary.",
    "metric_name": "The printed label for the measure, in the page's own words.",
    "subject_type": "What kind of thing the row measures: fund, portfolio, position, asset class, or benchmark.",
    "subject_name": "The printed name of the thing measured.",
    "subject_alias_id": "The alias row for the printed subject name.",
    "subject_entity_id": "The resolved entity the subject name maps to.",
    "subject_standardized_name": "The subject's standard name after identity resolution.",
    "subject_manager_name": "The subject's manager, where resolved.",
    "manager_alias_id": "The alias row for the printed manager name.",
    "manager_entity_id": "The resolved manager entity.",
    "investor_alias_id": "The alias row for the printed investor name.",
    "investor_entity_id": "The resolved investor entity.",
    "portfolio_name": "The portfolio or programme the document reports on.",
    "asset_class": "The printed asset class governing the row.",
    "horizon": "The measurement period of a return figure, such as 1-Yr or since inception.",
    "as_of_date_raw": "The as-of date as printed.",
    "period_start_raw": "The period start as printed.",
    "period_start": "The period start, parsed.",
    "period_end_raw": "The period end as printed.",
    "period_end": "The period end, parsed.",
    "value_kind": "number, currency, percent, multiple, text, or none.",
    "value_sign": "The sign the page gives the value, including parentheses for negatives.",
    "unit_scale": "The scale the page states: absolute, thousands, millions, billions.",
    "unit_scale_multiplier": "The factor that takes the printed value to base units.",
    "currency_scale_raw": "The printed currency and scale statement, verbatim.",
    "basis_raw": "The basis a clause states, as printed.",
    "condition_raw": "The condition a clause states, as printed.",
    "evidence_quote": "The printed text the value was read from. The validator requires the value to appear in it.",
    "evidence_class": "actual where the page prints the value; redacted where the page prints the label and withholds the number.",
    "source_agents": "Which extractors produced the row: A, B, or both.",
    "extractor_model": "The model of record for the published row.",
    "contract_version": "The field-list version the row was written under.",
    "pair_id": "Identifier of the A/B pair the row was settled from.",
    "pair_status": "Pair result: agreement, VALUE, CLASSIFICATION, CONTEXT, or one-sided.",
    "a_row_number": "The row in agent A's file.",
    "b_row_number": "The row in agent B's file.",
    "difference_fields": "The fields on which A and B disagreed.",
    "resolution_decision": "MERGE joins two readings that match the page. ACCEPT_A or ACCEPT_B keeps one reader. ADD types a missed field. REJECT drops a row empty of a printed fact.",
    "resolution_reason": "The adjudicator's stated reason.",
    "source_sha256": "SHA-256 of the source PDF the row is bound to.",
    "sha256": "SHA-256 of the file.",
    "adjudication_status": "Whether the row has been adjudicated.",
    "collision_note": "Filled when two evidence rows tried to populate the same field in a reconstructed source table.",
    "observation_ids": "The evidence-row IDs used to build this output row.",
    "observation_count": "The number of evidence rows used to build this output row.",
    "standard_measure": "A cross-document label for the quantity represented by a metric ID. Source labels, subjects, units, and notes retain each row's reported meaning.",
    "measure_scope": "The usual analytical grain. Mixed marks categories reported at several grains; subject_type and subject_name identify the grain of each observation.",
    "holding_label": "The printed label of the holding.",
    "holding_alias_id": "The alias row for the printed holding name.",
    "holding_entity_id": "The resolved entity for the holding.",
    # document summary
    "pages": "Physical pages in the document.",
    "physical_pages": "Physical pages in the document.",
    "pages_with_data": "Physical PDF pages that produced at least one evidence row.",
    "a_rows": "Candidate rows agent A produced.",
    "b_rows": "Candidate rows agent B produced.",
    "extractor_a_rows": "Candidate rows agent A produced.",
    "extractor_b_rows": "Candidate rows agent B produced.",
    "pairs": "One comparison row per PDF field proposed by either extractor, including fields proposed by only one reader.",
    "pair_rows": "One comparison row per PDF field proposed by either extractor, including fields proposed by only one reader.",
    "found_by_both": "PDF fields both readers typed.",
    "physical_pairs": "PDF fields both extractors placed at the same file, page, row label, column label, and repeated occurrence.",
    "value_agreements": "Matched PDF fields for which both extractors reported the same value.",
    "raw_value_agreements": "Matched PDF fields with the same printed value before review.",
    "raw_value_agreement_rate": "raw_value_agreements divided by physical_pairs.",
    "exact_all_field_pairs": "Pairs where the two agents agreed on every field, not the value alone.",
    "merge_decisions": "Pairs the adjudicator merged into one published row.",
    "accept_a_decisions": "Pairs settled in favour of agent A.",
    "accept_b_decisions": "Pairs settled in favour of agent B.",
    "add_decisions": "Rows the adjudicator added from the page image.",
    "reject_decisions": "Candidate rows the adjudicator rejected.",
    "difference_count": "How many pairs differed on this field.",
    "document_count": "How many documents the difference appeared in.",
    "field_name_difference": "The field the two agents disagreed on.",
    "resolution_row_number": "The row in the adjudicator's resolution file.",
    "final_row_number": "The row in the document's final published file.",
    "metric_value_raw": "The value as the page prints it.",
    "value_conflicts": "Matched PDF fields for which the extractors reported different values.",
    "classification_conflicts": "Matched PDF fields with the same value but a different metric name or source-row family.",
    "context_conflicts": "Matched PDF fields with the same value but a different date, subject, or unit.",
    "a_only": "PDF fields proposed only by Extractor A.",
    "b_only": "PDF fields proposed only by Extractor B.",
    "value_agreement_rate": "value_agreements divided by found_by_both.",
    "merge": "Pairs the adjudicator merged into one published row.",
    "accept_a": "Pairs settled in favour of agent A.",
    "accept_b": "Pairs settled in favour of agent B.",
    "adjudicator_addition": "Rows the adjudicator added from the page image.",
    "rejection": "Candidate rows the adjudicator rejected.",
    "final_rows": "Published rows for the document.",
    # corpus ledger
    "filename": "The file's name in the corpus.",
    "doc_type": "The document's ratified type.",
    "fund_type": "The kind of fund the document concerns.",
    "tier": "The document's product tier.",
    "issuer": "The organization that published the report.",
    "issuer_type": "Plan, manager, foundation, endowment, or other.",
    "jurisdiction": "Where the issuer is.",
    "period_covered": "The reporting period the document covers.",
    "source_url": "Where the file was fetched from.",
    "retrieved_at": "When the file was fetched.",
    "file_ext": "The file extension.",
    "file_size_bytes": "The file's size.",
    "page_count": "Physical pages in the file.",
    "has_text_layer": "Whether the PDF carries a text layer.",
    "license_note": "The terms the file was taken under.",
    "is_redacted": "Whether the document redacts values.",
    "expected_fields": "The fields the typing round expected the document to print.",
    "report_subtype": "A finer document type where one applies.",
    "wave": "The acquisition wave the file came in.",
    "txt_filename": "The page-aligned text file built from the PDF.",
    "native_pages": "Pages read from the text layer.",
    "ocr_pages": "Pages read from the page image.",
    "empty_pages": "Pages that yielded no text.",
    "chars": "Characters of text produced.",
    "seconds": "Time the text build took.",
    "error": "Any error the build recorded.",
    # schema
    "category": "The vocabulary name.",
    "kind": "metric or term.",
    "definition": "What the name means.",
    "unit_hint": "The unit the value usually carries.",
    "preferred_family": "The family the name usually sits in.",
    "description": "What the family is.",
    "grain": "What one row represents in this source-table family, such as one holding or one cash flow.",
    "category_kind": "Which vocabulary the family draws its names from.",
    "tabular": "Whether the family is read from tables.",
    "required_business_fields": "Fields a row of the family must fill.",
    "allowed_business_fields": "Fields a row of the family may fill.",
    "preferred_categories": "The names the family usually carries; the wide table lists these first.",
    "table_cell_rule": "How one extracted field is located within this type of source table.",
    "default_product_tier": "The tier documents of this type default to.",
    "allowed_record_families": "The line kinds this reading group may write for this type.",
    "excluded_scope": "Fields this reading group skips for this type.",
    "route_order": "The reading group's place in the run order.",
    "source_header_doc_type": "The type printed in the document's own header.",
    "routing_status": "Whether the document was routed, deferred, or excluded.",
    "routing_reason": "Reason the PDF was routed, deferred, or left out. Example: type PPM, group 05-fund-legal-docs.",
    "txt_path": "Path of the page-aligned text.",
    "pdf_path": "Path of the PDF.",
    "image_dir": "Folder of page images.",
    "grid_path": "Path of the document grid, used to identify items in the tables with ease in the page image files.",
    # market
    "source_relative_path": "Where the file sat in the source market corpus.",
    "destination_relative_path": "Where it sits in this repository.",
    "analysis_tier": "PME_CORE feeds the PME; ADVANCED_DAILY and MARKET_CONTEXT are retained for context.",
    "source_family": "The family of market data the file belongs to.",
    "promotion_status": "Whether the file's data was promoted into the benchmark tables.",
    "pme_role": "The part the file plays in the PME calculation.",
    "source_system": "The system the data was produced by.",
    "producer_script": "The script that produced the file inside the corpus it was acquired from. It names that file's origin and lives outside this repository.",
    "rights_status": "The permitted use of the data. DEMONSTRATION_ONLY excludes production use and redistribution.",
    "copy_action": "How the file was brought in.",
    "size_bytes": "The file's size.",
    "row_count": "Rows in the file.",
    "column_count": "Columns in the file.",
    "date_column": "Which column carries the date.",
    "date_min": "Earliest date in the file.",
    "date_max": "Latest date in the file.",
    "timezone_status": "Whether timestamps carry a timezone.",
    "schema_sha256": "SHA-256 of the file's column list.",
    "schema": "The file's columns.",
    "file_count": "Files of the family in the retained store.",
    "total_bytes": "Their combined size.",
    "analysis_tiers": "The tiers the family's files sit in.",
    "pme_roles": "The parts the family's files play in the PME calculation.",
    "source_systems": "The systems the family's data was produced by.",
    "PME role": "The part the family plays in the PME calculation.",
    "Source system": "The system the family's data was produced by.",
    "ticker": "The instrument's ticker.",
    "instrument_type": "ETF, index, or future.",
    "source_provider": "Who supplied the series.",
    "adjusted_flag": "Whether the series is adjusted for distributions.",
    "calendar": "The trading calendar.",
    "timezone": "The series' timezone.",
    "first_observation_date": "First date in the series.",
    "last_observation_date": "Last date in the series.",
    "source_priority": "Preference order where two sources cover one series.",
    "source_file_id": "The retained file the series was built from.",
    "source_column": "The column of that file.",
    "pme_use_status": "Whether the series may serve as a PME benchmark.",
    "use_status": "DEMO_PROXY_ONLY: the series runs this demo.",
    # release
    "order": "The stage's position in the run.",
    "stage": "The stage's name.",
    "source": "The script that runs it.",
    "input": "What it reads.",
    "output": "What it writes.",
    "test": "The check that guards it.",
    "next_readme": "The folder guide to read next.",
    "receipt_id": "Identifier of one receipt.",
    "stage_order": "The stage's position in the run.",
    "stage_id": "The stage's name.",
    "command": "The command that ran.",
    "output_path": "What it wrote.",
    "output_rows": "Rows in what it wrote.",
    "output_sha256": "SHA-256 of what it wrote.",
    "path": "The file's path in the repository.",
    "entry_type": "file or directory.",
    "repository_policy": "TRACK ships with the repository; LOCAL_ONLY stays on the machine that built it.",
    "local_readme": "The folder guide that describes the file.",
    "role": "What the file is for.",
    "rows": "Rows stored in the file.",
    "columns": "Fields stored in each row.",
    "contents": "Data held in the file.",
    "csv_path": "Path of the CSV in the repository.",
    "origin_csv": "CSV input used to build this file; blank where the input is a PDF, Parquet file, text page, code vocabulary, or direct review work.",
    "python_file": "Module that writes the CSV.",
    "agent_operation": "Agent task that produced or reviewed the rows, where one applied.",
    "instructions_file": "Instruction file governing the agent task, where one applied.",
    # wide tables
    "wide_row_id": "Identifier of one printed table row in the wide layer.",
    "column_group": "The printed source-table columns used to build this reconstructed row.",
    "scale_note": "The scale statement the page printed for the row, where one applied.",
    "unparsed_values": "Source fields kept as text because no numeric value could be read reliably.",
    # evidence dimensions
    "alias_id": "Identifier of one printed spelling of a name.",
    "raw_name": "The name as the page prints it.",
    "normalized_name": "The name with case, punctuation, and spacing settled, used to match spellings.",
    "standardized_name": "The one standard name the spelling resolves to.",
    "entity_kind": "fund, manager, plan, lp, or company.",
    "entity_type": "fund, manager, plan, lp, or company.",
    "match_method": "How the spelling was matched to its standard: mechanically on a single variant, or by a normalizer by hand.",
    "match_confidence": "The confidence recorded for the match.",
    "reviewed_by_human": "TRUE where a person settled the match.",
    "first_seen_document": "The first document the name appeared in.",
    "documents": "How many documents print the name.",
    "occurrences": "How many times the name is printed across the corpus.",
    "alias_count": "How many distinct spellings resolve to the entity.",
    "fund_family": "The sponsor family the fund belongs to, such as every fund a manager runs.",
    "manager_source": "Where the manager attribution came from: the page, the family, or the manager search round.",
    "resolution_status": "Whether the entity's identity is settled.",
    "parent_entity_id": "The entity this one belongs under, where one exists.",
    "canonical_name": "The entity's standard name.",
    "canonical_entity": "The standard entity the metric belongs to.",
    "in_catalogue": "TRUE where the name is in the vocabulary.",
    "identity_role": "The part the metric plays in the fund identities the rules recompute.",
    "default_measure_basis": "Whether the metric is a balance, a flow, a ratio, or a rate.",
    "unit_class": "The unit family the metric carries.",
    "page_status": "Coverage pass result: data, zero allowed values, or reference material.",
    "layout_checked": "TRUE where the page's layout was compared with its document grid.",
    "source_structures": "The layouts found on the page: tables, figures, narrative, forms.",
    "relevant_record_families": "The families the page's content belongs to.",
    "expected_observation_count": "How many PDF fields the coverage review expected this page to produce.",
    "records_written": "How many evidence rows were written from this page.",
    "holding_count": "Holdings read from the document.",
    "pages_covered": "Pages the coverage pass counted.",
    "pages_with_data": "Physical PDF pages that produced at least one evidence row.",
    "ledger_page_count": "Pages in the file, from the source ledger.",
    "period_covered_raw": "The reporting period as the document states it.",
    "fiscal_year_end_mmdd": "The issuer's fiscal year end, as month and day.",
    "char_count_sample": "Characters of text in a sample of the file, from the acquisition pass.",
    "has_landscape_page": "Whether the file has a wide page.",
    "layout_features": "Layout features the acquisition pass noted.",
    "max_table_cols": "The widest table the acquisition pass detected.",
    "n_tables_detected": "Tables the acquisition pass detected.",
    "pivot_table": "The wide table the row belongs to.",
    "pivot_row_id": "The wide-table row the observation was pivoted into.",
    "value_scaled": "The value carried to base units by its scale multiplier.",
    "expected_observations": "PDF fields the coverage review expected across the document.",
    "written_observations": "Evidence rows the document actually produced.",
    "pages_no_eligible_data": "Pages the coverage pass read that have zero allowed values.",
    "funds": "Funds in the family.",
    "with_manager": "Funds in the family that carry a manager.",
    "family_propagated": "Funds whose manager was carried from the family.",
    "checks": "Rule results counted.",
    "passes": "Results that passed.",
    "failures": "Results that failed.",
    "skips": "Results that were skipped.",
    "pass_rate_excluding_skips": "passes divided by passes plus failures.",
    "recomputed_dpi": "DPI recomputed from distributions and paid-in capital.",
    "recomputed_rvpi": "RVPI recomputed from NAV and paid-in capital.",
    "recomputed_tvpi": "TVPI recomputed from distributions, NAV, and paid-in capital.",
    "component_tvpi": "DPI plus RVPI.",
    "recomputed_ending_nav": "Ending NAV recomputed from the roll-forward components.",
    # document maps
    "document_fund_map_id": "Identifier of one document-to-fund link.",
    "document_manager_map_id": "Identifier of one document-to-manager link.",
    "census_item_id": "The census row the name was harvested from.",
    "fund_name_raw": "The fund name as the page prints it.",
    "fund_name_normalized": "The fund name with spelling settled.",
    "fund_manager_raw": "The manager as the page prints it.",
    "manager_name_raw": "The manager name as the page prints it.",
    "manager_name_normalized": "The manager name with spelling settled.",
    "manager_source_page": "The page the manager name is printed on.",
    "manager_pdf_page_number": "The physical page of the manager name.",
    "manager_source_anchor": "The quote that carries the manager name.",
    "manager_source_quote": "The printed words the manager name was read from.",
    "manager_source_bbox": "The position of the manager name on the page.",
    "relationship_role": "What the document is to the fund or manager: issuer, subject, reference.",
    "pdf_page_number": "The physical page number.",
    "source_bbox": "The position of the value on the page.",
    "agent_a_record_id": "The row in agent A's file the link came from.",
    "agent_b_record_id": "The row in agent B's file the link came from.",
    "manager_observation_id": "Identifier of one PDF-reported metric assigned to a manager, not a fund.",
    "benchmark_return_id": "Identifier of one benchmark return.",
    "investor_name": "The asset owner the document reports for.",
    "document_name": "The document's title.",
    # source links on an evidence row
    "source_pdf_path": "The source PDF, relative to the repository root; opens from the row detail.",
    "source_txt_path": "The page-aligned text of the source PDF, one page per block.",
    "source_grid_path": "The document grid of the source PDF, used to identify items in the tables with ease in the page image files.",
    "records_a_path": "Extractor A's candidate file for the document.",
    "records_b_path": "Extractor B's candidate file for the document.",
    "pair_index_path": "The A/B pair index for the document.",
    "resolution_path": "The adjudicator's decision file for the document.",
    "records_final_path": "The document's final published file.",
    # receipts
    "input_artifacts": "The files the command read.",
    "predecessor_receipt_ids": "The receipts of the commands whose outputs this one read.",
    "prior_output_sha256": "SHA-256 of what the output path held before the command ran.",
    "prior_output_object_path": "Where the prior bytes were archived.",
    "output_object_path": "Where the written bytes were archived.",
    "recorded_at_utc": "When the receipt was written.",
    "inputs": "How many records fed the calculation, with the first few named. The full list is in input_record_ids.",
    # regression-fixture extraction controls
    "adjudication_id": "Identifier of one adjudication in the fixture's extraction control.",
    "adjudicator_notes": "The adjudicator's note.",
    "agent_a_candidate_id": "Agent A's candidate row.",
    "agent_b_candidate_id": "Agent B's candidate row.",
    "agent_a_file_sha256": "SHA-256 of agent A's file.",
    "agent_b_file_sha256": "SHA-256 of agent B's file.",
    "agent_id": "Which extractor produced the row.",
    "agreement_class": "How the two agents' readings compared.",
    "allowed_metric_ids": "The metric names the assignment permits.",
    "assignment_id": "Identifier of one extraction assignment.",
    "assignment_status": "Where the assignment stands.",
    "attempt_id": "Identifier of one extraction attempt.",
    "attempted_at": "When the attempt ran.",
    "audit_adjudication_id": "The adjudication the audit ruled on.",
    "audit_agent_id": "The auditor.",
    "audit_family": "The family of check the audit applied.",
    "audit_id": "Identifier of one audit result.",
    "audit_ready_status": "Whether the adjudication is ready for audit.",
    "auditor_notes": "The auditor's note.",
    "batch_id": "The batch the row belongs to.",
    "candidate_id": "Identifier of one candidate row.",
    "canonical_fund_id": "The fund the adjudicated value belongs to.",
    "canonical_fund_name": "That fund's standard name.",
    "canonical_instrument_id": "The instrument the value belongs to.",
    "canonical_instrument_name": "That instrument's standard name.",
    "canonical_lp_id": "The limited partner the value belongs to.",
    "canonical_lp_name": "That limited partner's standard name.",
    "canonical_manager_id": "The manager the value belongs to.",
    "canonical_manager_name": "That manager's standard name.",
    "canonical_portfolio_company_id": "The company the value belongs to.",
    "canonical_portfolio_company_name": "That company's standard name.",
    "canonical_row_id": "The fund-model row the value was promoted into.",
    "canonical_row_key": "The fund-model row key the value targets.",
    "canonical_share_class_name": "The share class the value belongs to.",
    "canonical_table": "The fund-model table the value targets.",
    "canonical_tables": "The fund-model tables the assignment may write.",
    "canonical_value_numeric": "The adjudicated numeric value.",
    "canonical_value_raw": "The adjudicated value as printed.",
    "canonical_value_text": "The adjudicated text value.",
    "census_json": "The census entry behind the candidate, as JSON.",
    "check_family": "The family of check applied.",
    "conflict_class": "The kind of conflict the promotion found.",
    "container_route": "The reading group the assignment belongs to.",
    "date_roles": "The date roles the assignment expects.",
    "dates_audit_file_sha256": "SHA-256 of the dates audit file.",
    "dates_audit_id": "The dates audit the promotion cites.",
    "dates_coverage_pct": "Share of dates the audit covered.",
    "dates_result": "The dates audit's result.",
    "doc_type_batch_number": "The batch number within the document type.",
    "duplicate_gate_result": "Whether the duplicate gate passed.",
    "error_count": "Errors the promotion found.",
    "extracted_at": "When the row was extracted.",
    "extraction_method": "How the value was read: text layer, page image, or document grid.",
    "extraction_tier": "The tier the extraction ran at.",
    "field_family": "The family of fields the attempt targeted.",
    "final_decision": "The promotion's decision on the row.",
    "instrument_name_raw": "The instrument as the page prints it.",
    "issue_code": "The code of the issue the audit found.",
    "key_gate_result": "Whether the key gate passed.",
    "locations_attempted": "Where in the document the attempt looked.",
    "lp_name_raw": "The limited partner as the page prints it.",
    "module_batch_number": "The batch number within the module.",
    "module_folder": "The module's folder.",
    "module_id": "The module the row belongs to.",
    "module_name": "The module's name.",
    "module_sequence": "The module's position in the run.",
    "observed_value": "The value the audit observed.",
    "output_file_sha256": "SHA-256 of the attempt's output.",
    "parser_route": "The parser the assignment used.",
    "portfolio_company_name_raw": "The company as the page prints it.",
    "promoter_notes": "The promotion's note.",
    "promotion_run_id": "The promotion run the row belongs to.",
    "proposed_correction": "The correction the audit proposed.",
    "quality_gate_result": "Whether the quality gate passed.",
    "reason_code": "The code of the reason recorded.",
    "record_kind": "The kind of record the row is.",
    "round_id": "The extraction round the row belongs to.",
    "rows_emitted": "Rows the attempt produced.",
    "runtime_seconds": "How long the attempt ran.",
    "schema_audit_file_sha256": "SHA-256 of the schema audit file.",
    "schema_audit_id": "The schema audit the promotion cites.",
    "schema_coverage_pct": "Share of the schema the audit covered.",
    "schema_result": "The schema audit's result.",
    "sequence_in_batch": "The row's position in its batch.",
    "share_class_name_raw": "The share class as the page prints it.",
    "staging_sha256": "SHA-256 of the staging file.",
    "unresolved_count": "Printed names that lack a standard ID.",
    "violation_reason": "Why the lineage rule was violated.",
    "waived_warning_count": "Warnings a waiver cleared.",
    "waiver_id": "The waiver applied.",
    "warning_count": "Warnings the promotion found.",
    "documents_complete": "Documents fully extracted.",
    "documents_in_corpus": "Documents in the corpus.",
    "documents_manager_only": "Documents that name a manager and no fund.",
    "documents_no_data": "Documents with zero allowed values.",
    "documents_not_applicable": "Documents outside the lanes.",
    "documents_not_started": "Documents not yet extracted.",
    "documents_unreadable": "Documents the reader could not open.",
    "documents_unresolved": "Documents that have a printed name that lacks a standard ID.",
    "gold_id": "Identifier of one hand-verified value.",
    "entity_raw_name": "The entity as the page prints it.",
    "expected_text": "The text the verified value should match.",
    "layout_codes": "The layouts the verified value sits in.",
    "match_status": "Whether the extraction matched the verified value.",
    "matched_observation_id": "The observation that matched.",
    "verified_at": "When the value was verified.",
    "verified_by": "Who verified it.",
    "amount_raw": "The amount as the page prints it.",
    "beginning_balance": "Balance at the start of the period.",
    "ending_balance": "Balance at the end of the period.",
    "contributions": "Capital drawn in the period.",
    "distributions": "Capital returned in the period.",
    "net_income": "Income less expenses for the period.",
    "realized_gain": "Gains on positions sold in the period.",
    "unrealized_gain": "Change in value of positions still held.",
    "partnership_expense": "Partnership expenses for the period.",
    "rollforward_check": "Whether the balances roll forward.",
    "pcap_id": "Identifier of one capital-account period.",
    "flow_type": "The kind of cash flow.",
    "flow_subtype": "A finer kind of cash flow.",
    "is_recallable": "Whether the distribution may be called again.",
    "holder_alias_id": "The alias row for the holder's printed name.",
    "entity_alias_id": "The alias row for the entity's printed name.",
    "fund_alias_id": "The alias row for the fund's printed name.",
    "fund_entity_id": "The resolved fund entity.",
    "cost_amount": "What the fund paid for the holding.",
    "fair_value_amount": "The holding's valuation.",
    "industry": "The company's industry.",
    "interest_rate_pct": "The instrument's interest rate, as a percent.",
    "spread_pct": "The spread over the reference rate, as a percent.",
    "reference_rate": "The rate the spread is over.",
    "investment_type": "The kind of investment.",
    "is_non_accrual": "Whether the instrument has stopped accruing interest.",
    "pct_of_net_assets": "The holding's share of net assets.",
    "row_raw": "The printed row, verbatim.",
    "is_subtotal": "Whether the row is a subtotal.",
    "is_estimated": "Whether the page marks the value as an estimate.",
    "footnote_ref": "The footnote marker on the value.",
    "footnote_text": "The footnote's text.",
    "occurrence_seq": "Which instance of a repeated value this is.",
    "confidence_band": "A coarse band for the extractor's confidence.",
    "knowledge_date": "The date the value became known.",
    "first_document": "The first document that prints the value.",
    "other_document": "Another document that prints the same value.",
    "n_documents": "How many documents print the value.",
    "first_reported": "The value's first printed figure.",
    "last_reported": "The value's latest printed figure.",
    "n_observations": "How many times the value was printed.",
    "n_distinct_values": "How many different figures were printed for it.",
    "min_value": "The smallest figure printed for it.",
    "max_value": "The largest figure printed for it.",
    "spread": "max_value minus min_value.",
    "relative_spread": "spread divided by the smallest figure.",
    # the timed extraction runs
    "extraction-runs.run_id": "Identifier of one timed extraction run: the lane and the document it read.",
    "extraction-runs.document": "The source document the run extracted.",
    "extraction-runs.doc_type": "The document's ratified type.",
    "extraction-runs.pages": "Physical pages the run read.",
    "extraction-runs.rows": "Extracted rows the run wrote.",
    "extraction-runs.turns": "Model turns the run took. A turn is one request to the model, and it is the unit that bills.",
    "extraction-runs.cost_usd": "What the run cost, in US dollars, read from the session log.",
    "extraction-runs.dollars_per_turn": "Run cost divided by turns. It holds steady across documents, which is why cost reduces to counting turns.",
    "extraction-runs.basis": "measured where the figures come straight from the session log; halved where recoverable waste has been removed.",
    "extraction-runs.note": "What the run established, and any adjustment applied to its figures.",
    # table-specific states
    "quality_results.status": "PASS means the recomputed value agrees within tolerance; FAIL marks an inconsistency; SKIP means a required input is absent.",
    "FINAL-RELEASE-AUDIT.status": "PASS means the step finished and lists zero open exceptions; PASS_WITH_DISCLOSURES means it completed and names follow-up review items.",
    "transformation-receipts.status": "PASS or FAIL for this data-changing command; a failed row also records the error.",
    "gap-ledger.status": "Whether this previously blank fund-model field was filled and retained.",
    "PROJECT-MANIFEST.repository_policy": "Whether the path belongs in the public repository, remains local, or is excluded.",
    # headings used by the built tables
    "Funds": "Number of funds represented by this row.",
    "Weight": "Share of the demonstration portfolio assigned to this row.",
    "Tables": "Number of stored tables in the database.",
    "Quote": "The line of printed text the value was read from.",
    "Source PASS inside printed precision": "Passes on the printed-only copy where the allowed gap grew to the page rounding.",
    "Group": "A group of field-list columns that share one purpose.",
    "Purpose": "The information this column group preserves in each extraction row.",
    "Fields": "The extraction columns included in this group.",
    "Field": "The extraction or fund-model column being described.",
    "Meaning": "The information stored in that column.",
    "Table": "The CSV or DuckDB table name.",
    "File": "The database or source filename.",
    "Rows": "Number of records; the panel description states what one row represents.",
    "Columns": "Number of fields stored on each row.",
    "Views": "Number of saved SQL queries in the database.",
    "Collisions": "Reconstructed table fields claimed by two evidence rows; zero means every evidence row had a unique destination.",
    "Contents": "The role this database plays in the pipeline.",
    "View names": "Saved SQL queries available in the database.",
    "First columns": "The first six field names, shown as a quick structural preview.",
    "Metric": "The calculated measure, such as TVPI, XIRR, or Direct Alpha.",
    "Unit": "Whether the result is a currency amount, percentage, multiple, count, or text.",
    "Minimum": "The smallest value across the population.",
    "25th": "The 25th percentile: a quarter of the values sit below it.",
    "Median": "The middle value.",
    "75th": "The 75th percentile: three quarters of the values sit below it.",
    "Maximum": "The largest value.",
    "Rule": "Identifier of the financial or data-quality check.",
    "Severity": "Whether a failure blocks publication or remains a warning for review.",
    "Formula": "The equation or comparison the rule recomputes.",
    "Tolerance": "Largest permitted difference between the stored and recomputed values.",
    "Needed inputs": "Required fields that must be present before the rule can run.",
    "Source PASS": "PDF-only records that agree with the rule within tolerance.",
    "Source FAIL": "PDF-only records that disagree with the rule beyond tolerance.",
    "Source SKIP": "PDF-only records missing at least one input required by the rule.",
    "Completed PASS": "Completed-data records that agree with the rule within tolerance.",
    "Completed FAIL": "Completed-data records that disagree with the rule beyond tolerance.",
    "Completed SKIP": "Completed-data records missing at least one input required by the rule.",
    "Benchmark": "Stable identifier of the benchmark series used by PME.",
    "Name": "Human-readable name of the fund, benchmark, file, or category represented by the row.",
    "Rights": "Reuse-rights status recorded for the market series.",
    "Use": "Whether the series is allowed for demonstration or production analysis.",
    "First": "Earliest date included in the series.",
    "Last": "Latest date included in the series.",
    "Observations": "Dated values in the time series.",
    "Note": "Source or policy context attached to the row.",
    "Family": "Group of market files with the same source and structure.",
    "Files": "Number of source files reviewed in this family.",
    "Selected": "Number of files retained for benchmark construction or market context.",
    "Decision": "Whether the market-file family was retained, limited, or excluded.",
    "Tiers": "Analytical roles assigned to the retained files.",
    "Reason": "Evidence supporting the recorded decision or outcome.",
    "Ticker": "The instrument's ticker.",
    "Asset class": "The instrument's asset class.",
    "Currency": "Currency in which the market series is quoted.",
    "Basis": "Whether returns include price movement alone or total return with distributions.",
    "Defect": "Type of deliberate error inserted into the isolated test copy.",
    "Injected": "Number of deliberate errors inserted for this type.",
    "Detected": "Number of inserted errors caught by the intended quality rule.",
    "Missed": "Number of inserted errors not caught by the intended quality rule.",
    "Rate": "Detected errors divided by inserted errors.",
    "Run": "One timed extraction run of one document by one lane.",
    "Turns": "Model turns the run took. A turn is one request to the model, and it is the unit that bills.",
    "Cost": "What the run cost, or what the scope is estimated to cost.",
    "Cost per turn": "Run cost divided by turns. Stable across documents, which is why cost reduces to counting turns.",
    "Document type": "Report category from the source ledger.",
    "Documents": "Number of source documents of this type in the corpus.",
    "Rows per page": "Extracted rows per physical page for this document type, from the reviewed slice where it covers the type.",
    "Yield basis": "Whether rows per page is measured on this type or taken from the corpus pooled rate.",
    "Estimated rows": "Rows this type is expected to yield: its rows per page applied to its pages.",
    "Page-equivalents": "pages + rows / 182, the single unit the estimate prices. One page costs the same as 182 rows.",
    "Cost per document": "Estimated cost for one extraction lane, averaged over the documents of this type.",
    "Total cost": "Estimated cost for one extraction lane over all documents of this type.",
    "Scope": "How much of the pipeline the figure covers.",
    "Command": "Repository-root command used to rebuild or verify the release.",
    "Result": "Files or checks produced when the command completes.",
    "Extracted": "Fund-model field values printed on a cited PDF page.",
    "Derived": "Fund-model field values copied within the same fund from PDF evidence.",
    "Imputed": "Fund-model field values filled from the extracted cohort median.",
    "Synthetic": "Fund-model field values generated from the seeded parameter set.",
    "Cells": "All fund-model field values counted for this column.",
    "Fund values": "Fund-model field values counted for this column.",
    "Population": "Whether the result uses PDF-only rows or the completed fund data.",
    "Cause": "Reason the quality rule passed, failed, or skipped the record.",
    "Count": "Number of rows represented by this summary line.",
    "Fund": "Standardized fund name attached to the tested value.",
    "Document": "Source-ledger identifier of the PDF containing the value.",
    "Page": "Physical PDF page on which the value appears.",
    "Printed": "Value exactly as reported by the PDF.",
    "Recomputed": "Value calculated from the record's parts.",
    "Difference": "printed minus recomputed.",
    "Reading": "Plain-language interpretation of the reported and recomputed values.",
    "Date": "Date attached to the cash flow, period, or market observation.",
    "Value": "Amount, ratio, rate, date, or text stored for this result.",
    "Kind": "Whether the row represents a metric, term, cash flow, or other defined record type.",
    "Flow": "Cash-flow type, such as contribution, distribution, or terminal NAV.",
    "Amount": "Signed cash amount from the investor's perspective.",
    "Index level": "The benchmark level on that date.",
    "Scaled": "The amount carried forward at the index.",
}


def _vocabulary_definitions() -> dict[str, str]:
    """The metric and term names, defined once in the extraction contract.

    A wide table has one column per vocabulary name, so those columns take
    the contract's own definition rather than a second copy written here."""

    from src.catalog.simple_pdf_extraction import csv_wide_contract as contract

    definitions = {}
    for name, (definition, unit_hint) in contract.METRIC_DEFINITIONS.items():
        definitions[name] = f"{definition} Unit: {unit_hint}." if unit_hint else definition
    for name, definition in contract.TERM_DEFINITIONS.items():
        definitions.setdefault(name, definition)
    return definitions


_VOCABULARY: dict[str, str] | None = None


def column_note(column: str, table: str = "") -> str:
    """The definition for a column, preferring a table-specific one."""

    global _VOCABULARY
    if table and f"{table}.{column}" in COLUMN_NOTES:
        return COLUMN_NOTES[f"{table}.{column}"]
    if column in COLUMN_NOTES:
        return COLUMN_NOTES[column]
    lowered = column.lower()
    for key, value in COLUMN_NOTES.items():
        if key.lower() == lowered:
            return value
    if _VOCABULARY is None:
        _VOCABULARY = _vocabulary_definitions()
    if column in _VOCABULARY:
        return _VOCABULARY[column]
    return ""
