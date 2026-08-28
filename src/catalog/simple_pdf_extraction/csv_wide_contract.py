"""Closed wide-row field list for deterministic PDF extraction.

One CSV row is one source observation or one bounded narrative provision.  The
module is the field list used by the prompt generator, validators,
pairing, third reader, migration, and tests.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Iterable, Mapping

CONTRACT_VERSION: Final = "2026-08-22.2"

ROUTES: Final[dict[str, tuple[str, ...]]] = {
    "01-financials": ("Financials",),
    "02-performance": ("Performance",),
    "03-institutional-report": ("Institutional_Report",),
    "04-quarterly-report": ("Quarterly_Report",),
    "05-fund-legal-docs": ("PPM", "LPA", "Subscription", "Side_Letter", "DDQ"),
    "06-statements-and-economics": (
        "Schedule_Inv",
        "Fee_Report",
        "Valuation",
        "NAV_Statement",
        "Cash_Flow_Notice",
        "PCAP",
    ),
    "07-institutional-mission": ("Foundations_Annual", "Stewardship_Proxy_Report"),
}

CANONICAL_DOC_TYPES: Final[tuple[str, ...]] = tuple(
    doc_type for doc_types in ROUTES.values() for doc_type in doc_types
)
DOC_TYPE_TO_ROUTE: Final[dict[str, str]] = {
    doc_type: route for route, doc_types in ROUTES.items() for doc_type in doc_types
}

PRODUCT_TIERS: Final = ("CORE", "SECONDARY", "REFERENCE")
DEFAULT_PRODUCT_TIER: Final[dict[str, str]] = {
    "Financials": "CORE",
    "Performance": "CORE",
    "Institutional_Report": "CORE",
    "Quarterly_Report": "CORE",
    "PPM": "CORE",
    "LPA": "CORE",
    "Subscription": "SECONDARY",
    "Side_Letter": "CORE",
    "DDQ": "CORE",
    "Schedule_Inv": "CORE",
    "Fee_Report": "CORE",
    "Valuation": "CORE",
    "NAV_Statement": "CORE",
    "Cash_Flow_Notice": "CORE",
    "PCAP": "CORE",
    "Foundations_Annual": "SECONDARY",
    "Stewardship_Proxy_Report": "SECONDARY",
}

# Field names that are not columns. Generated prose that names one
# tells an agent to fill a column that does not exist.
RETIRED_FIELDS: Final[tuple[str, ...]] = ("parent_subject_name",)

# Extraction lanes. These live here, not in the workflow, because the prompt
# generator and the validator both need them and the generator cannot import
# the workflow. One list keeps a dropped lane out of the prompts.
CANDIDATE_AGENTS: Final[tuple[str, ...]] = ("A", "B")
# Bench lanes are judged like A and B but never paired or adjudicated:
# they compare models on identical work, they do not produce final rows. Empty
# means no bake-off is running: name a lane here and a route in BENCH_ROUTES to
# start one, and the prompt, the candidate files, and the dashboard row follow.
BENCH_AGENTS: Final[tuple[str, ...]] = ()
EXTRACTOR_AGENTS: Final[tuple[str, ...]] = (*CANDIDATE_AGENTS, *BENCH_AGENTS)

RECORD_COLUMNS: Final[tuple[str, ...]] = (
    "contract_version",
    "file_id",
    "source_sha256",
    "canonical_doc_type",
    "route",
    "product_tier",
    "agent_role",
    "record_family",
    "source_page",
    "source_structure_type",
    "source_section",
    "source_table",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "subject_type",
    "subject_name",
    "asset_class",
    "strategy",
    "geography",
    "manager_name",
    "investor_name",
    "portfolio_name",
    "vintage_year",
    "period_start",
    "period_end",
    "as_of_date",
    "horizon",
    "currency_scale",
    "metric_category",
    "metric_name",
    "metric_value_raw",
    "unit",
    "term_category",
    "text_raw",
    "basis_raw",
    "condition_raw",
    "evidence_quote",
    "evidence_class",
    "notes",
    "source_agents",
    "adjudication_status",
)

COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "contract_version",
    "file_id",
    "source_sha256",
    "canonical_doc_type",
    "route",
    "product_tier",
    "agent_role",
    "source_page",
    "page_status",
    "layout_checked",
    "source_structures",
    "relevant_record_families",
    "expected_observation_count",
    "records_written",
    "notes",
)

WORKLIST_COLUMNS: Final[tuple[str, ...]] = (
    "work_order",
    "file_id",
    "filename",
    "page_count",
    "canonical_doc_type",
    "source_header_doc_type",
    "route",
    "product_tier",
    "routing_status",
    "routing_reason",
    "issuer",
    "source_sha256",
    "txt_path",
    "pdf_path",
    "image_dir",
    "grid_path",
)

PAIR_COLUMNS: Final[tuple[str, ...]] = (
    "pair_id",
    "pair_status",
    "requires_review",
    "source_page",
    "record_family",
    "source_table",
    "source_row_label",
    "source_column_label",
    "source_occurrence",
    "metric_category",
    "term_category",
    "a_row_number",
    "b_row_number",
    "difference_fields",
)

RESOLUTION_COLUMNS: Final[tuple[str, ...]] = (
    "pair_id",
    "decision",
    "reason",
    *RECORD_COLUMNS,
)

COVERAGE_DIFF_COLUMNS: Final[tuple[str, ...]] = (
    "source_page",
    "a_page_status",
    "b_page_status",
    "a_layout_checked",
    "b_layout_checked",
    "a_expected_observation_count",
    "b_expected_observation_count",
    "a_source_structures",
    "b_source_structures",
    "a_relevant_record_families",
    "b_relevant_record_families",
    "difference_fields",
)

COVERAGE_RESOLUTION_COLUMNS: Final[tuple[str, ...]] = (
    "source_page",
    "final_page_status",
    "final_expected_observation_count",
    "reason",
)

EVIDENCE_CLASSES: Final = (
    "actual",
    "illustrative",
    "template",
    "requirement",
    "definition",
    "redacted",
    "unknown",
)
CORE_EVIDENCE_CLASSES: Final = ("actual", "redacted")
REFERENCE_EVIDENCE_CLASSES: Final = (
    "illustrative",
    "template",
    "requirement",
    "definition",
    "redacted",
    "unknown",
)

SOURCE_STRUCTURE_TYPES: Final = (
    "DOCUMENT",
    "TABLE",
    "FIGURE",
    "NARRATIVE",
    "FORM",
    "FOOTNOTE",
    "SCHEDULE",
)

PAGE_STATUSES: Final = (
    "NO_ELIGIBLE_DATA",
    "ELIGIBLE_DATA_EXTRACTED",
    "DEFERRED_BY_SCOPE",
    "REFERENCE_ONLY",
    "UNREADABLE",
)

SUBJECT_TYPES: Final = (
    "document",
    "reporting_entity",
    "fund",
    "portfolio",
    "investment",
    "manager",
    "investor",
    "asset_class",
    "benchmark",
    "peer_group",
    "market_series",
    "fee_scope",
    "cash_flow",
    "valuation_subject",
    "foundation",
    "program_related_investment",
    "service_provider",
    "clause_party",
    "subscription",
    "other_printed_scope",
)

# The vocabulary: one row per name, once. `record_family` is the table grain
# (statement, holdings, capital account, allocation, and so on) and owns no
# private list; a metric family accepts any metric name and a term family any
# term name. The preferred family is guidance for a mixed table, and the
# validator does not enforce it. Names are the printed measures and terms of
# the 442-document corpus.
#
# (category, definition, unit_hint, preferred_family)
METRIC_VOCABULARY: Final[tuple[tuple[str, str, str, str], ...]] = (
    # Fund economics: the capital account of one fund or one LP position.
    ("commitment", "Capital committed to the fund by the investor or in total.", "currency", "fund_economics_observation"),
    ("paid_in_capital", "Capital contributed to date (PIC, paid-in, contributed capital).", "currency", "fund_economics_observation"),
    ("contribution", "One contribution or a period's contributions, as a flow.", "currency", "fund_economics_observation"),
    ("distribution", "Capital distributed to date or in a period, including a printed component such as preferred return when the page lists it inside distributions.", "currency", "fund_economics_observation"),
    ("nav", "Residual value of one fund, LP position, or share class at a date, printed as NAV, remaining value, reported value, or ending market value at that grain.", "currency", "fund_economics_observation"),
    ("unfunded_commitment", "Commitment not yet called (unfunded, remaining, uncalled).", "currency", "fund_economics_observation"),
    ("recallable_distribution", "Distributed capital the fund may call again.", "currency", "fund_economics_observation"),
    ("tvpi", "Total value to paid-in: (distributions + NAV) / paid-in.", "x", "fund_economics_observation"),
    ("dpi", "Distributions to paid-in.", "x", "fund_economics_observation"),
    ("rvpi", "Residual value to paid-in: NAV / paid-in.", "x", "fund_economics_observation"),
    ("moic", "Multiple of invested capital: total value / invested cost, gross or as printed.", "x", "fund_economics_observation"),
    ("ownership_percentage", "Share of a vehicle, firm, or partnership held by the subject.", "%", "fund_economics_observation"),
    ("income", "Investment, dividend, interest, or net income of a fund or capital account for a period, recorded as a currency amount; percent-based distribution and investment yields use yield.", "currency", "fund_economics_observation"),
    ("fee", "A fee amount charged to a fund or account when the page states no finer kind (management fees, commissions, advisor fees).", "currency", "fund_economics_observation"),
    ("carried_interest", "Carried interest accrued, realized, or unrealized, as an amount.", "currency", "fund_economics_observation"),
    ("beginning_capital", "Opening balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement.", "currency", "financial_statement_observation"),
    ("ending_capital", "Closing balance of a capital account, partners' capital, or net assets for a period, at the entity or partner grain printed by the statement. A residual closing balance may also represent NAV.", "currency", "financial_statement_observation"),
    # Performance: returns and risk statistics.
    ("return", "The return printed for a period or horizon, as a percent, under the method, fee basis, and hedge treatment stated by the report. Methods include time-weighted, Modified Dietz, holding-period, annualized, and money-weighted. Data/schemas/RETURN-METHOD-BY-DOCUMENT.csv records the applicable basis. A figure labelled IRR uses irr.", "%", "performance_observation"),
    ("irr", "Internal rate of return, net or gross, since inception or for a horizon, where the page labels it IRR. A money-weighted return printed under another label stays return, with its method recorded.", "%", "performance_observation"),
    ("alpha", "Return minus the stated benchmark's return (value added, excess return).", "%", "performance_observation"),
    ("pme", "Public market equivalent ratio (Kaplan-Schoar or as printed).", "x", "performance_observation"),
    ("direct_alpha", "Direct alpha against a stated public index.", "%", "performance_observation"),
    ("sharpe_ratio", "Sharpe ratio as printed.", "ratio", "performance_observation"),
    ("tracking_error", "Tracking error against the stated benchmark.", "%", "performance_observation"),
    ("yield", "A rate of income as a percent: distribution rate, income yield, or investment yield. Total-period performance uses return.", "%", "performance_observation"),
    ("aum", "Assets under management or total assets at manager, plan, endowment, pool, fund, or asset-class scope.", "currency", "performance_observation"),
    # Financial statements: line items of a statement or note.
    ("cash", "Cash and cash equivalents at a date or a period's opening or closing balance.", "currency", "financial_statement_observation"),
    ("total_assets", "Total assets.", "currency", "financial_statement_observation"),
    ("total_liabilities", "Total liabilities.", "currency", "financial_statement_observation"),
    ("net_assets", "Net assets of the reporting entity as printed, restricted or unrestricted: total assets less total liabilities at statement grain.", "currency", "financial_statement_observation"),
    ("partners_capital", "Partners' capital by partner class or in total, and its change from operations, at the entity grain of the statement. Position-level closing capital uses ending_capital.", "currency", "financial_statement_observation"),
    ("net_investment_income", "Net investment income or loss for a period.", "currency", "financial_statement_observation"),
    ("investment_fair_value", "Investments at fair value as a line of a financial statement or note, including the Level 1, 2, and 3 hierarchy lines. The amount precedes the entity's other assets and liabilities in the NAV build-up.", "currency", "financial_statement_observation"),
    ("investment_cost", "Cost basis of investments on a statement.", "currency", "financial_statement_observation"),
    ("fund_expense", "An expense line or an expense ratio of the fund (professional fees, organizational expenses, total expenses).", "currency or %", "financial_statement_observation"),
    ("interest_expense", "Interest expense for a period.", "currency", "financial_statement_observation"),
    ("realized_gain_loss", "Realized gain or loss on investments for a period.", "currency", "financial_statement_observation"),
    ("unrealized_gain_loss", "Change in unrealized gain or loss for a period.", "currency", "financial_statement_observation"),
    # Positions: one named holding.
    ("quantity", "Shares, units, or par held.", "count", "position_observation"),
    ("cost", "Cost of a holding.", "currency", "position_observation"),
    ("fair_value", "Fair or market value of one named holding on a schedule of investments. Fund residual value uses nav; statement investment lines use investment_fair_value.", "currency", "position_observation"),
    ("market_value", "Market value under that printed heading for one holding or one allocation bucket. The same measure as fair_value at holding grain; at fund grain the residual value is nav.", "currency", "position_observation"),
    ("notional", "Notional, par, purchase, or sale amount of a contract or security.", "currency", "position_observation"),
    ("portfolio_weight", "A holding's share of the portfolio or of partners' capital.", "%", "position_observation"),
    ("interest_rate", "Coupon or yield printed on a holding.", "%", "position_observation"),
    ("maturity_date", "Maturity or settlement date printed on a holding.", "date", "position_observation"),
    # Allocation: buckets of a portfolio.
    ("actual_allocation", "Actual share of a portfolio in an asset class, strategy, vintage, geography, or industry bucket.", "%", "allocation_observation"),
    ("target_allocation", "Target or policy weight of a bucket or benchmark component.", "%", "allocation_observation"),
    # Fees: fee reports and fee lines.
    ("management_fee", "Management fee as an amount or as a rate; the unit column says which. The contractual clause is the term-vocabulary management_fee.", "currency or %", "fee_observation"),
    ("performance_fee", "Incentive or performance fee rate or amount.", "% or currency", "fee_observation"),
    ("cost_bps", "Fee or cost expressed in basis points.", "bps", "fee_observation"),
    ("offset", "A fee offset, adjustment, or rebate amount.", "currency", "fee_observation"),
    ("fee_benchmark", "A peer or benchmark fee level the report compares against.", "bps or currency", "fee_observation"),
    ("nav_aum_denominator", "The asset base a fee is measured on.", "currency", "fee_observation"),
    # Cash flows: dated calls, distributions, and their components.
    ("capital_call", "A dated capital call amount.", "currency", "cash_flow_observation"),
    ("return_of_capital", "The return-of-capital component of a distribution.", "currency", "cash_flow_observation"),
    ("preferred_return", "The preferred-return component of a distribution.", "currency", "cash_flow_observation"),
    ("expense", "An expense or tax charge in a capital-account or cash-flow statement.", "currency", "cash_flow_observation"),
    ("interest", "Interest paid or charged in a capital-account statement.", "currency", "cash_flow_observation"),
    ("net_cash_flow", "Net cash movement after the page combines cash inflows and outflows.", "currency", "cash_flow_observation"),
    # NAV statements.
    ("nav_per_share", "NAV per share or unit by class.", "currency", "nav_observation"),
    ("shares_units", "Shares or units outstanding, issued, or sold.", "count", "nav_observation"),
    ("transaction_price", "Transaction price per share by class.", "currency", "nav_observation"),
    ("nav_component", "A line of the NAV build-up: investments, cash, debt, other assets and liabilities.", "currency", "nav_observation"),
    ("repurchase_limit", "A repurchase or redemption limit as a share of NAV or an amount.", "% or currency", "nav_observation"),
    ("request_satisfaction", "Share or amount of repurchase requests satisfied.", "% or currency", "nav_observation"),
    ("valuation_assumption", "A discount rate, exit capitalization rate, or other valuation input.", "%", "nav_observation"),
    ("valuation_sensitivity", "Change in value for a stated change in an assumption.", "%", "nav_observation"),
    # Valuation policy: printed wording, not numbers.
    ("method", "The valuation method or principle stated.", "text", "valuation_observation"),
    ("frequency", "How often NAV or appraisals are produced.", "text", "valuation_observation"),
    ("valuer", "Who values or calculates NAV.", "text", "valuation_observation"),
    ("oversight", "Who approves or oversees valuations.", "text", "valuation_observation"),
    ("independent_review", "Independent review or appraisal of valuations.", "text", "valuation_observation"),
    ("enterprise_value", "Enterprise value of a company or portfolio company.", "currency", "valuation_observation"),
    # Financing.
    ("outstanding_balance", "Balance drawn on a credit facility or loan.", "currency", "financing_observation"),
    # Due diligence answers: operational facts about a manager or fund.
    ("staff_count", "Employees or investment professionals at the firm.", "count", "ddq_quantitative_observation"),
    ("lockup", "Lock-up period.", "years or months", "ddq_quantitative_observation"),
    ("redemption_notice", "Redemption notice period or fee.", "days or %", "ddq_quantitative_observation"),
    ("position_limit", "Position or exposure limit.", "%", "ddq_quantitative_observation"),
    ("leverage", "Leverage ratio or policy limit.", "x", "ddq_quantitative_observation"),
    ("liquidity", "Redemption proceeds timing in days, or a withdrawal size as a percent of proceeds or of NAV; the unit column says which.", "% or days", "ddq_quantitative_observation"),
    ("minimum_investment", "Minimum initial investment.", "currency", "ddq_quantitative_observation"),
    ("service_provider_count", "Number of service providers or counterparties stated.", "count", "ddq_quantitative_observation"),
    # Stewardship reports: counts and proportions of engagement and voting.
    ("meeting_count", "Meetings held or voted at.", "count", "stewardship_observation"),
    ("vote_count", "Proposals, directors, or votes counted.", "count", "stewardship_observation"),
    ("engagement_count", "Engagements, milestones, or companies engaged.", "count", "stewardship_observation"),
    ("coverage", "Share or count of a universe covered, held, or voted.", "% or count", "stewardship_observation"),
    ("score", "Support percentage or assessment score.", "%", "stewardship_observation"),
    ("target", "A stated target year or level.", "year", "stewardship_observation"),
)

# (category, definition, preferred_family)
TERM_VOCABULARY: Final[tuple[tuple[str, str, str], ...]] = (
    # Economic terms of a fund.
    ("management_fee", "Management fee rate, basis, and step-downs.", "legal_term"),
    ("carried_interest", "Carried interest rate and basis.", "legal_term"),
    ("catch_up", "GP catch-up provision.", "legal_term"),
    ("waterfall", "Distribution waterfall, including the preferred return hurdle.", "legal_term"),
    ("clawback", "GP clawback provision.", "legal_term"),
    ("fee_offset", "Offset of transaction or monitoring fees against the management fee.", "legal_term"),
    ("organizational_expense", "Organizational expense cap or treatment.", "legal_term"),
    ("recycling", "Reinvestment or recycling of proceeds.", "legal_term"),
    # Term and governance.
    ("fund_term", "Term of the fund or agreement.", "legal_term"),
    ("term_extension", "Extension of the term.", "legal_term"),
    ("commitment_period", "Commitment period.", "legal_term"),
    ("investment_period", "Investment period.", "legal_term"),
    ("key_person", "Key-person provision.", "legal_clause"),
    ("gp_removal", "Removal of the general partner, for cause or without.", "legal_clause"),
    ("no_fault_termination", "Termination without cause.", "legal_clause"),
    ("mfn", "Most-favoured-nation provision.", "legal_clause"),
    ("reporting", "Reporting obligations.", "legal_clause"),
    ("transfer", "Transfer or assignment of interests.", "legal_clause"),
    ("tax", "Tax provisions and certifications.", "legal_clause"),
    ("governing_law", "Governing law.", "legal_clause"),
    ("confidentiality", "Confidentiality.", "legal_clause"),
    ("notice", "Notice provisions.", "legal_clause"),
    # Subscription documents.
    ("subscription_fund", "The fund subscribed to.", "subscription_reference"),
    ("general_partner", "The general partner named.", "subscription_reference"),
    ("requested_commitment", "Commitment requested.", "subscription_reference"),
    ("accepted_commitment", "Commitment accepted.", "subscription_reference"),
    ("subscriber_entity_type", "Entity type of the subscriber.", "subscription_reference"),
    ("fund_jurisdiction", "Jurisdiction of the fund.", "subscription_reference"),
    ("execution_date", "Execution date.", "subscription_reference"),
    # Stewardship.
    ("stewardship_policy", "A stewardship or voting policy statement.", "stewardship_policy"),
)

METRIC_CATEGORIES: Final[tuple[str, ...]] = tuple(row[0] for row in METRIC_VOCABULARY)
TERM_CATEGORIES: Final[tuple[str, ...]] = tuple(row[0] for row in TERM_VOCABULARY)
METRIC_DEFINITIONS: Final[dict[str, tuple[str, str]]] = {row[0]: (row[1], row[2]) for row in METRIC_VOCABULARY}
TERM_DEFINITIONS: Final[dict[str, str]] = {row[0]: row[1] for row in TERM_VOCABULARY}
PREFERRED_METRIC_FAMILY: Final[dict[str, str]] = {row[0]: row[3] for row in METRIC_VOCABULARY}
PREFERRED_TERM_FAMILY: Final[dict[str, str]] = {row[0]: row[2] for row in TERM_VOCABULARY}
# Metric names whose printed value is wording, not a number.
TEXT_METRICS: Final[frozenset[str]] = frozenset(
    name for name, (_, unit) in METRIC_DEFINITIONS.items() if unit in {"text", "date"}
)
assert len(set(METRIC_CATEGORIES)) == len(METRIC_CATEGORIES), "a metric name is listed twice"
assert len(set(TERM_CATEGORIES)) == len(TERM_CATEGORIES), "a term name is listed twice"


def preferred_categories(record_family: str) -> tuple[str, ...]:
    """The vocabulary names whose preferred home is this family, in vocabulary order."""

    metrics = tuple(name for name, family in PREFERRED_METRIC_FAMILY.items() if family == record_family)
    terms = tuple(name for name, family in PREFERRED_TERM_FAMILY.items() if family == record_family)
    return (*metrics, *terms)


PROVENANCE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "contract_version",
        "file_id",
        "source_sha256",
        "canonical_doc_type",
        "route",
        "product_tier",
        "agent_role",
        "record_family",
        "source_page",
        "source_structure_type",
        "source_section",
        "source_table",
        "source_row_label",
        "source_column_label",
        "source_occurrence",
        "evidence_quote",
        "evidence_class",
        "notes",
        "source_agents",
        "adjudication_status",
    }
)
BUSINESS_COLUMNS: Final[frozenset[str]] = frozenset(RECORD_COLUMNS) - PROVENANCE_COLUMNS

COMMON_METRIC_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subject_type",
        "subject_name",
        "asset_class",
        "strategy",
        "geography",
        "vintage_year",
        "period_start",
        "period_end",
        "as_of_date",
        "horizon",
        "currency_scale",
        "metric_category",
        "metric_name",
        "metric_value_raw",
        "unit",
    }
)
COMMON_TERM_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subject_type",
        "subject_name",
        "manager_name",
        "investor_name",
        "portfolio_name",
        "period_start",
        "period_end",
        "as_of_date",
        "currency_scale",
        "term_category",
        "text_raw",
        "basis_raw",
        "condition_raw",
    }
)
CONTEXT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "subject_type",
        "subject_name",
        "asset_class",
        "strategy",
        "geography",
        "manager_name",
        "investor_name",
        "portfolio_name",
        "vintage_year",
        "period_start",
        "period_end",
        "as_of_date",
        "currency_scale",
        "text_raw",
    }
)


@dataclass(frozen=True)
class FamilyContract:
    """The grain of one table shape. `kind` says which category column the
    family fills: a metric family fills `metric_category` from the whole metric
    vocabulary, a term family fills `term_category` from the whole term
    vocabulary, and the context family fills neither."""

    description: str
    grain: str
    required_fields: frozenset[str]
    allowed_fields: frozenset[str]
    kind: str = "context"
    tabular: bool = False

    @property
    def metric_categories(self) -> tuple[str, ...]:
        return METRIC_CATEGORIES if self.kind == "metric" else ()

    @property
    def term_categories(self) -> tuple[str, ...]:
        return TERM_CATEGORIES if self.kind == "term" else ()


FAMILY_CONTRACTS: Final[dict[str, FamilyContract]] = {
    "document_context": FamilyContract(
        "One source-backed document identity and reporting context row.",
        "one row per document",
        frozenset({"subject_type", "subject_name"}),
        CONTEXT_FIELDS,
    ),
    "financial_statement_observation": FamilyContract(
        "A whitelisted alternative-investment financial-statement value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "performance_observation": FamilyContract(
        "A printed return, multiple, risk, valuation, or benchmark value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_type", "subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "fund_economics_observation": FamilyContract(
        "A printed commitment, paid-in, distribution, NAV, unfunded, multiple, or capital-account value cell.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "position_observation": FamilyContract(
        "A printed holding or private-market position measure.",
        "one populated allowed source value cell for one named position",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "allocation_observation": FamilyContract(
        "A printed portfolio allocation amount or percentage.",
        "one populated allowed source value cell for one allocation bucket",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "fee_observation": FamilyContract(
        "A printed fee, carry, expense, offset, cost, rate, or benchmark value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "cash_flow_observation": FamilyContract(
        "A printed call, contribution, distribution, fee, expense, or other investor cash-flow value.",
        "one populated allowed source value cell or one notice component the page states in words",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "nav_observation": FamilyContract(
        "A printed NAV, share-class, transaction-price, component, repurchase, assumption, or sensitivity value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "valuation_observation": FamilyContract(
        "A printed valuation result, method, input, adjustment, frequency, or governance fact.",
        "one printed valuation fact or one populated value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "financing_observation": FamilyContract(
        "A printed borrowing, facility, balance, rate, availability, or maturity value.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "legal_term": FamilyContract(
        "A whitelisted fund, economic, liquidity, governance, or investor-protection term.",
        "one printed term or one numbered provision whose primary meaning matches the whitelist",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "legal_clause": FamilyContract(
        "A listed operative right, duty, restriction, waiver, or trigger.",
        "one numbered or separately headed operative provision whose primary meaning matches the whitelist",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "ddq_quantitative_observation": FamilyContract(
        "A selected quantitative due-diligence fact; narrative question-and-answer transcription is excluded.",
        "one printed quantitative answer or table value",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "stewardship_observation": FamilyContract(
        "A printed stewardship, voting, engagement, climate, or governance metric.",
        "one populated allowed source value cell",
        frozenset({"subject_name", "metric_category", "metric_name", "metric_value_raw"}),
        COMMON_METRIC_FIELDS,
        kind="metric",
        tabular=True,
    ),
    "stewardship_policy": FamilyContract(
        "A concise operative stewardship policy from a named framework or policy section.",
        "one separately headed operative policy statement",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
    "subscription_reference": FamilyContract(
        "A non-sensitive subscription-document reference fact; qualification narratives and personal identifiers are excluded.",
        "one whitelisted subscription reference fact",
        frozenset({"term_category", "text_raw"}),
        COMMON_TERM_FIELDS,
        kind="term",
    ),
}

DOC_TYPE_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "Financials": (
        "document_context",
        "financial_statement_observation",
        "fund_economics_observation",
        "position_observation",
        "fee_observation",
        "financing_observation",
    ),
    "Performance": (
        "document_context",
        "performance_observation",
        "fund_economics_observation",
        "cash_flow_observation",
    ),
    "Institutional_Report": (
        "document_context",
        "performance_observation",
        "fund_economics_observation",
        "position_observation",
        "allocation_observation",
    ),
    "Quarterly_Report": (
        "document_context",
        "performance_observation",
        "fund_economics_observation",
        "allocation_observation",
        "cash_flow_observation",
        "position_observation",
    ),
    "PPM": ("document_context", "legal_term"),
    "LPA": ("document_context", "legal_term", "legal_clause"),
    "Subscription": ("document_context", "subscription_reference"),
    "Side_Letter": ("document_context", "legal_term", "legal_clause"),
    "DDQ": ("document_context", "ddq_quantitative_observation"),
    "Schedule_Inv": ("document_context", "position_observation"),
    "Fee_Report": ("document_context", "fee_observation", "fund_economics_observation"),
    "Valuation": ("document_context", "valuation_observation"),
    "NAV_Statement": ("document_context", "nav_observation", "valuation_observation"),
    "Cash_Flow_Notice": (
        "document_context",
        "cash_flow_observation",
        "fund_economics_observation",
    ),
    "PCAP": (
        "document_context",
        "fund_economics_observation",
        "cash_flow_observation",
    ),
    "Foundations_Annual": ("document_context",),
    "Stewardship_Proxy_Report": (
        "document_context",
        "stewardship_observation",
        "stewardship_policy",
    ),
}

NULL_LIKE_VALUES: Final[frozenset[str]] = frozenset(
    {"", "-", "—", "–", "$ -", "$-", "n/a", "na", "not applicable", "nil", "none"}
)
TEMPLATE_PATTERN: Final = re.compile(
    r"(?:[$£€]\s*)?(?:x{2,}(?:[,\.]?x{2,})*|_{2,}|\[[^\]]*(?:name|amount|date|fund|manager|investor|__)[^\]]*\])",
    re.IGNORECASE,
)
WHITESPACE_PATTERN: Final = re.compile(r"\s+")


def route_for_doc_type(doc_type: str) -> str:
    try:
        return DOC_TYPE_TO_ROUTE[doc_type]
    except KeyError as exc:
        raise ValueError(f"Unknown ratified document type: {doc_type!r}") from exc


def normalize_key_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.replace("\u00a0", " ")
    return WHITESPACE_PATTERN.sub(" ", normalized).strip().casefold()


def record_key(row: Mapping[str, str]) -> tuple[str, ...]:
    """Physical address of the printed cell, used for A/B pairing.

    Identity is *where the value is printed*, never what an extractor decided it
    means. `record_family`, `metric_category`, `term_category`, and
    `source_table` are chosen by the reader, so they sit in
    `comparison_payload` rather than in this key: a classification disagreement
    is a conflict on one row, not two unpaired readings of the same cell.

    `source_table` is excluded for the same reason: on a page carrying a report
    title, a section heading and a table caption, two readers legitimately
    transcribe different titles for the same table.
    """

    return (
        row.get("file_id", ""),
        str(row.get("source_page", "")),
        normalize_key_text(row.get("source_row_label", "")),
        normalize_key_text(row.get("source_column_label", "")),
        str(row.get("source_occurrence", "")),
    )


def record_pair_id(row: Mapping[str, str]) -> str:
    material = "\x1f".join(record_key(row)).encode("utf-8")
    return "PAIR_" + hashlib.sha256(material).hexdigest()[:24].upper()


def comparison_payload(row: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Everything two candidates must agree on once they point at the same cell.

    Semantic fields sit here, so a classification difference is a conflict on
    one row rather than two unpaired readings.
    """
    ignored = {"agent_role", "notes", "source_agents", "adjudication_status"}
    return tuple((column, normalize_key_text(row.get(column, ""))) for column in RECORD_COLUMNS if column not in ignored)


def is_null_like(value: str) -> bool:
    return normalize_key_text(value) in NULL_LIKE_VALUES


def is_template_placeholder(value: str) -> bool:
    return bool(TEMPLATE_PATTERN.search(value or ""))


def allowed_business_columns(record_family: str) -> frozenset[str]:
    return FAMILY_CONTRACTS[record_family].allowed_fields


def required_business_columns(record_family: str) -> frozenset[str]:
    return FAMILY_CONTRACTS[record_family].required_fields


def allowed_metric_categories(record_family: str) -> tuple[str, ...]:
    """The whole metric vocabulary for a metric family, nothing for the rest."""

    return FAMILY_CONTRACTS[record_family].metric_categories


def allowed_term_categories(
    record_family: str, canonical_doc_type: str | None = None
) -> tuple[str, ...]:
    """The whole term vocabulary for a term family, nothing for the rest. The
    document type is accepted for call compatibility; routing is by family."""

    return FAMILY_CONTRACTS[record_family].term_categories


def deterministic_sample(pair_id: str, *, modulus: int = 10) -> bool:
    """Stable 10% sample used to source-check otherwise matching A/B pairs."""

    digest = int(hashlib.sha256(pair_id.encode("ascii")).hexdigest()[:8], 16)
    return digest % modulus == 0


def header_line(columns: Iterable[str]) -> str:
    return ",".join(f'"{column}"' for column in columns)


def empty_record() -> dict[str, str]:
    return {column: "" for column in RECORD_COLUMNS}


def empty_coverage() -> dict[str, str]:
    return {column: "" for column in COVERAGE_COLUMNS}
