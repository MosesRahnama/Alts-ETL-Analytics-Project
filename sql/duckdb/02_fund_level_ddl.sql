-- Fund-level fund-model layer for the Private Markets ETL and Analytics project.
-- DuckDB 1.5 compatible. The only DDL of data/warehouse/alts.duckdb; the
-- document-faithful evidence layer lives in extracted.duckdb (03 and 04).

CREATE TABLE IF NOT EXISTS manager_master (
    manager_id                      VARCHAR PRIMARY KEY,
    manager_name                    VARCHAR NOT NULL,
    legal_name                      VARCHAR,
    domicile                        VARCHAR,
    headquarters                    VARCHAR,
    website                         VARCHAR,
    base_currency                   VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    created_at                      TIMESTAMP,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED'))
);

CREATE TABLE IF NOT EXISTS document_manager_map (
    document_manager_map_id         VARCHAR PRIMARY KEY,
    file_id                         VARCHAR NOT NULL,
    census_item_id                  VARCHAR,
    manager_id                      VARCHAR NOT NULL,
    manager_name_raw                VARCHAR,
    manager_name_normalized         VARCHAR,
    relationship_role               VARCHAR NOT NULL,
    source_page                     VARCHAR,
    pdf_page_number                 INTEGER,
    source_anchor                   VARCHAR,
    source_quote                    VARCHAR,
    source_bbox                     VARCHAR,
    provenance_type                 VARCHAR,
    agent_a_record_id               VARCHAR,
    agent_b_record_id               VARCHAR,
    adjudication_status             VARCHAR NOT NULL,
    confidence                      DOUBLE,
    notes                           VARCHAR,
    CHECK (provenance_type IS NULL OR provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    FOREIGN KEY (manager_id) REFERENCES manager_master(manager_id)
);

CREATE TABLE IF NOT EXISTS fund_master (
    fund_id                         VARCHAR PRIMARY KEY,
    fund_name                       VARCHAR, -- nullable at landing so QC can report and quarantine a deliberately missing name
    legal_name                      VARCHAR,
    fund_manager_id                 VARCHAR,
    fund_manager_name               VARCHAR,
    strategy                        VARCHAR,
    sub_strategy                    VARCHAR,
    vintage_year                    INTEGER,
    domicile                        VARCHAR,
    base_currency                   VARCHAR,
    fund_size                       DECIMAL(24, 6),
    fund_size_currency              VARCHAR,
    first_close_date                DATE,
    final_close_date                DATE,
    termination_date                DATE,
    fund_status                     VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    created_at                      TIMESTAMP,
    name_hint                       VARCHAR,
    canonical_strategy              VARCHAR,
    canonical_asset_class           VARCHAR,
    -- Column order follows the published header, which is the file's own header
    -- plus the promotion-schema-additions.csv columns in matrix order; the
    -- loader compares the two in order and refuses a table where they differ.
    sector                          VARCHAR, -- the printed company industry, where the corpus states one
    canonical_sub_strategy          VARCHAR,
    canonical_sector                VARCHAR,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_manager_id) REFERENCES manager_master(manager_id)
);

CREATE TABLE IF NOT EXISTS document_fund_map (
    document_fund_map_id            VARCHAR PRIMARY KEY,
    file_id                         VARCHAR NOT NULL,
    census_item_id                  VARCHAR,
    fund_id                         VARCHAR,
    fund_name_raw                   VARCHAR,
    fund_name_normalized            VARCHAR,
    fund_manager_raw                VARCHAR,
    manager_source_page             VARCHAR,
    manager_pdf_page_number         INTEGER,
    manager_source_anchor           VARCHAR,
    manager_source_quote            VARCHAR,
    manager_source_bbox             VARCHAR,
    relationship_role               VARCHAR NOT NULL,
    perspective                     VARCHAR,
    share_class_name                VARCHAR,
    lp_name                         VARCHAR,
    source_page                     VARCHAR,
    pdf_page_number                 INTEGER,
    source_anchor                   VARCHAR,
    source_quote                    VARCHAR,
    source_bbox                     VARCHAR,
    provenance_type                 VARCHAR,
    agent_a_record_id               VARCHAR,
    agent_b_record_id               VARCHAR,
    adjudication_status             VARCHAR NOT NULL,
    confidence                      DOUBLE,
    notes                           VARCHAR,
    CHECK (provenance_type IS NULL OR provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK (perspective IS NULL OR perspective IN (
        'fund_total', 'lp_position', 'plan_total', 'share_class',
        'portfolio_company', 'manager_total'
    )),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_observations (
    observation_id                  VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    lp_id                           VARCHAR,
    lp_name                         VARCHAR,
    share_class_name                VARCHAR,
    file_id                         VARCHAR,
    metric_id                       VARCHAR NOT NULL,
    date_role                       VARCHAR,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR,
    as_of_date                      DATE,
    report_date                     DATE,
    period_start_date               DATE,
    period_end_date                 DATE,
    cashflow_date                   DATE,
    effective_date                  DATE,
    due_date                        DATE,
    maturity_date                   DATE,
    value_raw                       VARCHAR,
    value_numeric                   DECIMAL(30, 10),
    value_text                      VARCHAR,
    currency                        VARCHAR,
    unit                            VARCHAR,
    perspective                     VARCHAR NOT NULL,
    measure_basis                   VARCHAR NOT NULL,
    fee_basis                       VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    extractor_version               VARCHAR,
    formula_id                      VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    imputation_method               VARCHAR,
    confidence                      DOUBLE,
    record_status                   VARCHAR NOT NULL,
    canonical_measure_id            VARCHAR,
    mapping_rule_id                 VARCHAR,
    -- What the printed number means, carried from the observation: a rate whose
    -- method and fee basis stayed behind cannot be compared with another.
    method                          VARCHAR,
    definition_keys                 VARCHAR,
    value_scope                     VARCHAR,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (perspective IN (
        'fund_total', 'lp_position', 'plan_total', 'share_class',
        'portfolio_company', 'manager_total'
    )),
    CHECK (
        perspective <> 'lp_position'
        OR COALESCE(NULLIF(lp_id, ''), NULLIF(lp_name, '')) IS NOT NULL
    ),
    CHECK (perspective <> 'share_class' OR NULLIF(share_class_name, '') IS NOT NULL),
    CHECK (measure_basis IN (
        'point_in_time', 'period_flow', 'inception_to_date', 'ratio', 'rate', 'static'
    )),
    CHECK (date_role IS NULL OR date_role IN (
        'as_of', 'report', 'period_start', 'period_end', 'cashflow',
        'effective', 'due', 'maturity', 'vintage_year', 'commitment_year', 'static_no_date'
    )),
    CHECK (date_precision IS NULL OR date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS manager_observations (
    manager_observation_id          VARCHAR PRIMARY KEY,
    manager_id                      VARCHAR NOT NULL,
    file_id                         VARCHAR NOT NULL,
    metric_id                       VARCHAR NOT NULL,
    date_role                       VARCHAR NOT NULL,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR NOT NULL,
    as_of_date                      DATE,
    report_date                     DATE,
    period_start_date               DATE,
    period_end_date                 DATE,
    cashflow_date                   DATE,
    effective_date                  DATE,
    due_date                        DATE,
    maturity_date                   DATE,
    value_raw                       VARCHAR,
    value_numeric                   DECIMAL(30, 10),
    value_text                      VARCHAR,
    currency                        VARCHAR,
    unit                            VARCHAR,
    perspective                     VARCHAR NOT NULL,
    measure_basis                   VARCHAR NOT NULL,
    provenance_type                 VARCHAR NOT NULL,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    extractor_version               VARCHAR,
    formula_id                      VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    imputation_method               VARCHAR,
    confidence                      DOUBLE,
    record_status                   VARCHAR NOT NULL,
    CHECK (perspective = 'manager_total'),
    CHECK (measure_basis IN ('point_in_time', 'period_flow', 'inception_to_date', 'ratio', 'rate', 'static')),
    CHECK (date_role IN (
        'as_of', 'report', 'period_start', 'period_end', 'cashflow',
        'effective', 'due', 'maturity', 'vintage_year', 'commitment_year', 'static_no_date'
    )),
    CHECK (date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    FOREIGN KEY (manager_id) REFERENCES manager_master(manager_id)
);

CREATE TABLE IF NOT EXISTS fund_cashflows (
    cashflow_id                     VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    lp_id                           VARCHAR,
    lp_name                         VARCHAR,
    share_class_name                VARCHAR,
    file_id                         VARCHAR,
    cashflow_event_id               VARCHAR,
    date_role                       VARCHAR,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR,
    cashflow_date                   DATE NOT NULL,
    report_date                     DATE,
    due_date                        DATE,
    cashflow_type                   VARCHAR NOT NULL,
    amount                          DECIMAL(24, 6) NOT NULL,
    currency                        VARCHAR NOT NULL,
    amount_base_currency            DECIMAL(24, 6),
    base_currency                   VARCHAR,
    fx_rate                         DECIMAL(20, 10),
    recallable_amount               DECIMAL(24, 6),
    provenance_type                 VARCHAR NOT NULL,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    defect_expected                 BOOLEAN,
    record_status                   VARCHAR NOT NULL,
    CHECK (cashflow_type IN (
        'capital_call', 'distribution', 'fee', 'recallable_distribution',
        'subscription', 'other'
    )),
    CHECK (date_role IS NULL OR date_role IN ('cashflow', 'due', 'report')),
    CHECK (date_precision IS NULL OR date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_periods (
    fund_period_id                  VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    lp_id                           VARCHAR,
    lp_name                         VARCHAR,
    share_class_name                VARCHAR,
    date_role                       VARCHAR NOT NULL,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR NOT NULL,
    as_of_date                      DATE,
    report_date                     DATE,
    period_start_date               DATE,
    period_end_date                 DATE,
    effective_date                  DATE,
    perspective                     VARCHAR NOT NULL,
    currency                        VARCHAR,
    commitment                      DECIMAL(24, 6),
    paid_in_capital_itd             DECIMAL(24, 6),
    distributions_itd               DECIMAL(24, 6),
    nav                             DECIMAL(24, 6),
    unfunded_commitment             DECIMAL(24, 6),
    recallable_distributions_itd    DECIMAL(24, 6),
    dpi                             DECIMAL(20, 10),
    rvpi                            DECIMAL(20, 10),
    tvpi                            DECIMAL(20, 10),
    reported_irr                    DECIMAL(20, 10),
    calculated_irr                  DECIMAL(20, 10),
    beginning_nav                   DECIMAL(24, 6),
    contributions_period            DECIMAL(24, 6),
    distributions_period            DECIMAL(24, 6),
    realized_gain_period            DECIMAL(24, 6),
    unrealized_gain_period          DECIMAL(24, 6),
    net_income_period               DECIMAL(24, 6),
    management_fee_period           DECIMAL(24, 6),
    other_expenses_period           DECIMAL(24, 6),
    ending_nav                      DECIMAL(24, 6),
    period_return                   DECIMAL(20, 10),
    benchmark_return                DECIMAL(20, 10),
    fund_size                       DECIMAL(24, 6),
    vintage_year                    INTEGER,
    strategy                        VARCHAR,
    sub_strategy                    VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    formula_id                      VARCHAR,
    input_observation_ids           VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    defect_expected                 BOOLEAN,
    record_status                   VARCHAR NOT NULL,
    -- The qualifiers travel under the name of the column they qualify, so a net
    -- and a gross money-weighted rate never share reported_irr unlabelled.
    reported_irr_fee_basis          VARCHAR,
    reported_irr_method             VARCHAR,
    period_return_fee_basis         VARCHAR,
    period_return_method            VARCHAR,
    -- The printed grouping the period's own observations carried, and what it
    -- reads as under context-grouping-map.csv.
    sector                          VARCHAR,
    canonical_asset_class           VARCHAR,
    canonical_strategy              VARCHAR,
    canonical_sub_strategy          VARCHAR,
    canonical_sector                VARCHAR,
    CHECK (perspective IN ('fund_total', 'lp_position', 'share_class', 'plan_total')),
    CHECK (
        perspective <> 'lp_position'
        OR COALESCE(NULLIF(lp_id, ''), NULLIF(lp_name, '')) IS NOT NULL
    ),
    CHECK (perspective <> 'share_class' OR NULLIF(share_class_name, '') IS NOT NULL),
    CHECK (date_role IN ('as_of', 'report', 'period_start', 'period_end', 'effective')),
    CHECK (date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_terms (
    fund_term_id                    VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    lp_id                           VARCHAR,
    lp_name                         VARCHAR,
    share_class_name                VARCHAR,
    perspective                     VARCHAR NOT NULL,
    term_scope                      VARCHAR NOT NULL,
    overrides_fund_term_id          VARCHAR,
    effective_date                  DATE,
    effective_end_date              DATE,
    management_fee_rate             DECIMAL(20, 10),
    management_fee_basis            VARCHAR,
    carry_rate                      DECIMAL(20, 10),
    hurdle_rate                     DECIMAL(20, 10),
    catch_up_rate                    DECIMAL(20, 10),
    catch_up_present                 BOOLEAN,
    waterfall_type                  VARCHAR,
    fund_term_years                 DECIMAL(10, 4),
    extension_years                 DECIMAL(10, 4),
    preferred_return_compounding    VARCHAR,
    expense_cap_rate                DECIMAL(20, 10),
    maximum_offering                DECIMAL(24, 6),
    currency                        VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (perspective IN ('fund_total', 'lp_position', 'share_class')),
    CHECK (term_scope IN ('base_fund', 'lp_override', 'share_class_override')),
    CHECK (term_scope <> 'base_fund' OR perspective = 'fund_total'),
    CHECK (
        term_scope <> 'lp_override'
        OR (perspective = 'lp_position' AND COALESCE(NULLIF(lp_id, ''), NULLIF(lp_name, '')) IS NOT NULL)
    ),
    CHECK (
        term_scope <> 'share_class_override'
        OR (perspective = 'share_class' AND NULLIF(share_class_name, '') IS NOT NULL)
    ),
    CHECK (effective_end_date IS NULL OR effective_date IS NULL OR effective_end_date >= effective_date),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_term_clauses (
    fund_term_clause_id             VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    lp_id                           VARCHAR,
    lp_name                         VARCHAR,
    share_class_name                VARCHAR,
    perspective                     VARCHAR NOT NULL,
    term_scope                      VARCHAR NOT NULL,
    overrides_fund_term_id          VARCHAR,
    effective_date                  DATE,
    effective_end_date              DATE,
    source_document_id              VARCHAR,
    metric_id                       VARCHAR NOT NULL,
    clause_title                    VARCHAR,
    value_raw                       VARCHAR NOT NULL,
    value_text                      VARCHAR,
    currency                        VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    extractor_version               VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    CHECK (metric_id IN ('terms.risk_factor', 'terms.special_term')),
    CHECK (perspective IN ('fund_total', 'lp_position', 'share_class')),
    CHECK (term_scope IN ('base_fund', 'lp_override', 'share_class_override')),
    CHECK (term_scope <> 'base_fund' OR perspective = 'fund_total'),
    CHECK (
        term_scope <> 'lp_override'
        OR (perspective = 'lp_position' AND COALESCE(NULLIF(lp_id, ''), NULLIF(lp_name, '')) IS NOT NULL)
    ),
    CHECK (
        term_scope <> 'share_class_override'
        OR (perspective = 'share_class' AND NULLIF(share_class_name, '') IS NOT NULL)
    ),
    CHECK (effective_end_date IS NULL OR effective_date IS NULL OR effective_end_date >= effective_date),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_holdings (
    holding_id                      VARCHAR PRIMARY KEY,
    fund_id                         VARCHAR NOT NULL,
    portfolio_company_id            VARCHAR,
    portfolio_company_name          VARCHAR,
    instrument_id                   VARCHAR,
    instrument_name                 VARCHAR,
    date_role                       VARCHAR,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR,
    as_of_date                      DATE,
    report_date                     DATE,
    period_start_date               DATE,
    period_end_date                 DATE,
    effective_date                  DATE,
    security_type                   VARCHAR,
    sector                          VARCHAR,
    geography                       VARCHAR,
    currency                        VARCHAR,
    cost                            DECIMAL(24, 6),
    fair_value                      DECIMAL(24, 6),
    principal_amount                DECIMAL(24, 6),
    interest_rate                   DECIMAL(20, 10),
    spread_bps                      DECIMAL(20, 6),
    maturity_date                   DATE,
    ownership_percent               DECIMAL(20, 10),
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    canonical_sector                VARCHAR, -- what the printed industry reads as under context-grouping-map.csv
    CHECK (
        COALESCE(
            NULLIF(portfolio_company_name, ''), NULLIF(instrument_id, ''),
            NULLIF(instrument_name, '')
        ) IS NOT NULL
    ),
    CHECK (date_role IS NULL OR date_role IN ('as_of', 'report', 'period_start', 'period_end', 'effective', 'maturity', 'static_no_date')),
    CHECK (date_precision IS NULL OR date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);



-- NORMALIZED HOLDINGS BEGIN
-- Normalized holdings model for Alts-ETL-Analytics-Project.
-- This block is also embedded in sql/duckdb/02_fund_level_ddl.sql.

CREATE TABLE IF NOT EXISTS investment_owner (
    owner_id                        VARCHAR PRIMARY KEY,
    owner_kind                      VARCHAR NOT NULL,
    owner_role                      VARCHAR NOT NULL,
    canonical_name                  VARCHAR NOT NULL,
    source_entity_id                VARCHAR,
    owner_fund_id                   VARCHAR,
    parent_owner_id                 VARCHAR,
    identity_status                 VARCHAR NOT NULL,
    identity_confidence             VARCHAR NOT NULL,
    identity_confidence_basis       VARCHAR,
    identity_confidence_reason      VARCHAR,
    decision_id                     VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    created_at                      TIMESTAMP,

    FOREIGN KEY (owner_fund_id) REFERENCES fund_master(fund_id),
    FOREIGN KEY (parent_owner_id) REFERENCES investment_owner(owner_id),

    CHECK (owner_kind IN ('fund', 'lp', 'plan', 'portfolio', 'other')),
    CHECK (owner_role IN (
        'REPORTING_FUND', 'REPORTING_PORTFOLIO', 'LEGAL_OWNER',
        'PLAN_OWNER', 'COMBINED_REPORTING_SCOPE', 'OTHER'
    )),
    CHECK (identity_status IN ('RESOLVED', 'PROVISIONAL', 'UNRESOLVED', 'CONFLICT')),
    CHECK (identity_confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (record_status IN ('ACTIVE', 'INACTIVE', 'UNKNOWN')),
    CHECK (owner_fund_id IS NULL OR owner_kind = 'fund'),
    CHECK (parent_owner_id IS NULL OR parent_owner_id <> owner_id),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR (
            NULLIF(TRIM(source_document_id), '') IS NOT NULL
            AND NULLIF(TRIM(source_anchor), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR synthetic_parameter_set_id IS NULL
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS investment_target (
    target_id                       VARCHAR PRIMARY KEY,
    target_kind                     VARCHAR NOT NULL,
    canonical_name                  VARCHAR,
    printed_name_primary            VARCHAR,
    legal_name                      VARCHAR,
    company_entity_id               VARCHAR,
    investee_fund_id                VARCHAR,
    parent_target_id                VARCHAR,
    sector                          VARCHAR,
    canonical_sector                VARCHAR,
    sub_sector                      VARCHAR,
    country                         VARCHAR,
    identity_status                 VARCHAR NOT NULL,
    identity_confidence             VARCHAR NOT NULL,
    identity_confidence_basis       VARCHAR,
    identity_confidence_reason      VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    created_at                      TIMESTAMP,

    FOREIGN KEY (investee_fund_id) REFERENCES fund_master(fund_id),
    FOREIGN KEY (parent_target_id) REFERENCES investment_target(target_id),

    CHECK (target_kind IN (
        'PORTFOLIO_COMPANY', 'COUNTERPARTY', 'FUND', 'SPV', 'PROJECT',
        'REAL_ASSET', 'OTHER', 'UNRESOLVED'
    )),
    CHECK (identity_status IN ('RESOLVED', 'PROVISIONAL', 'UNRESOLVED', 'CONFLICT')),
    CHECK (identity_confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (record_status IN ('ACTIVE', 'EXITED', 'INACTIVE', 'UNKNOWN')),
    CHECK (company_entity_id IS NULL OR target_kind IN ('PORTFOLIO_COMPANY', 'COUNTERPARTY', 'SPV', 'UNRESOLVED')),
    CHECK (investee_fund_id IS NULL OR target_kind = 'FUND'),
    CHECK (NOT (company_entity_id IS NOT NULL AND investee_fund_id IS NOT NULL)),
    CHECK (
        identity_status <> 'RESOLVED'
        OR target_kind <> 'FUND'
        OR investee_fund_id IS NOT NULL
    ),
    CHECK (
        target_kind <> 'UNRESOLVED'
        OR identity_status IN ('UNRESOLVED', 'CONFLICT', 'PROVISIONAL')
    ),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR synthetic_parameter_set_id IS NULL
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    ),
    CHECK (parent_target_id IS NULL OR parent_target_id <> target_id)
);

CREATE TABLE IF NOT EXISTS investment_instrument (
    instrument_id                   VARCHAR PRIMARY KEY,
    target_id                       VARCHAR NOT NULL,
    instrument_kind                 VARCHAR NOT NULL,
    security_title_raw              VARCHAR,
    security_type_raw               VARCHAR,
    currency                        VARCHAR,
    seniority                       VARCHAR,
    secured_status                  VARCHAR,
    stated_rate                     DECIMAL(20, 10),
    rate_type                       VARCHAR,
    rate_basis_raw                  VARCHAR,
    spread_bps                      DECIMAL(20, 6),
    maturity_date_raw               VARCHAR,
    maturity_date                   DATE,
    identifier_type                 VARCHAR,
    identifier_value                VARCHAR,
    instrument_status               VARCHAR NOT NULL,
    classification_confidence       VARCHAR NOT NULL,
    classification_confidence_basis VARCHAR,
    classification_confidence_reason VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,

    FOREIGN KEY (target_id) REFERENCES investment_target(target_id),

    CHECK (instrument_kind IN (
        'COMMON_EQUITY', 'PREFERRED_EQUITY', 'OTHER_EQUITY',
        'FUND_INTEREST', 'COINVEST_EQUITY',
        'LOAN', 'BOND', 'MEZZANINE_DEBT', 'REVOLVER', 'OTHER_DEBT',
        'WARRANT', 'DERIVATIVE', 'REAL_ASSET_INTEREST',
        'OTHER', 'UNCLASSIFIED'
    )),
    CHECK (secured_status IS NULL OR secured_status IN ('SECURED', 'UNSECURED', 'UNKNOWN')),
    CHECK (rate_type IS NULL OR rate_type IN ('FIXED', 'FLOATING', 'COUPON', 'SPREAD', 'OTHER', 'UNKNOWN')),
    CHECK (instrument_status IN ('ACTIVE', 'MATURED', 'EXITED', 'UNKNOWN')),
    CHECK (classification_confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (record_status IN ('ACTIVE', 'EXITED', 'INACTIVE', 'UNKNOWN')),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR synthetic_parameter_set_id IS NULL
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    ),
    CHECK (
        (identifier_type IS NULL AND identifier_value IS NULL)
        OR (NULLIF(TRIM(identifier_type), '') IS NOT NULL AND NULLIF(TRIM(identifier_value), '') IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS fund_position (
    position_id                     VARCHAR PRIMARY KEY,
    source_holding_id               VARCHAR,
    owner_id                        VARCHAR NOT NULL,
    owner_fund_id                   VARCHAR,
    instrument_id                   VARCHAR NOT NULL,
    position_class                  VARCHAR NOT NULL,
    accounting_scope                VARCHAR NOT NULL,
    date_role                       VARCHAR,
    date_raw                        VARCHAR,
    date_precision                  VARCHAR,
    as_of_date                      DATE,
    report_date                     DATE,
    period_start_date               DATE,
    period_end_date                 DATE,
    effective_date                  DATE,
    quantity_raw                    VARCHAR,
    quantity                        DECIMAL(30, 10),
    quantity_unit                   VARCHAR,
    currency                        VARCHAR,
    cost                            DECIMAL(24, 6),
    fair_value                      DECIMAL(24, 6),
    market_value                    DECIMAL(24, 6),
    reported_value                  DECIMAL(24, 6),
    realized_proceeds               DECIMAL(24, 6),
    commitment                      DECIMAL(24, 6),
    unfunded_commitment             DECIMAL(24, 6),
    principal_amount                DECIMAL(24, 6),
    notional_amount                 DECIMAL(24, 6),
    fund_ownership_fraction         DECIMAL(20, 10),
    portfolio_weight_fraction       DECIMAL(20, 10),
    initial_investment_date         DATE,
    exit_date                       DATE,
    classification_confidence       VARCHAR NOT NULL,
    classification_confidence_basis VARCHAR,
    classification_confidence_reason VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    origin_type                     VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,

    FOREIGN KEY (owner_id) REFERENCES investment_owner(owner_id),
    FOREIGN KEY (owner_fund_id) REFERENCES fund_master(fund_id),
    FOREIGN KEY (instrument_id) REFERENCES investment_instrument(instrument_id),

    CHECK (position_class IN (
        'DIRECT_COMPANY', 'FUND_INTEREST', 'DEBT_INVESTMENT',
        'DIRECT_ASSET', 'DERIVATIVE', 'OTHER', 'UNCLASSIFIED'
    )),
    CHECK (accounting_scope IN (
        'fund_total', 'lp_position', 'share_class', 'plan_total', 'portfolio_total'
    )),
    CHECK (date_role IS NULL OR date_role IN (
        'as_of', 'report', 'period_start', 'period_end',
        'effective', 'maturity', 'static_no_date'
    )),
    CHECK (date_precision IS NULL OR date_precision IN ('day', 'month', 'quarter', 'year', 'unknown')),
    CHECK (classification_confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (origin_type IN (
        'DIRECT_SOURCE', 'SOURCE_NORMALIZED', 'MATRIX_NORMALIZATION',
        'DETERMINISTIC_DERIVATION', 'COMPLETION', 'SYNTHETIC_FIXTURE', 'OTHER'
    )),
    CHECK (record_status IN ('ACTIVE', 'EXITED', 'INACTIVE', 'UNKNOWN')),
    CHECK (fund_ownership_fraction IS NULL OR (fund_ownership_fraction >= 0 AND fund_ownership_fraction <= 1)),
    CHECK (portfolio_weight_fraction IS NULL OR (portfolio_weight_fraction >= 0 AND portfolio_weight_fraction <= 1)),
    CHECK (period_end_date IS NULL OR period_start_date IS NULL OR period_end_date >= period_start_date),
    CHECK (exit_date IS NULL OR initial_investment_date IS NULL OR exit_date >= initial_investment_date),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR (
            NULLIF(TRIM(source_holding_id), '') IS NOT NULL
            AND NULLIF(TRIM(source_document_id), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR synthetic_parameter_set_id IS NULL
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS lookthrough_edge (
    lookthrough_id                  VARCHAR PRIMARY KEY,
    root_fund_id                    VARCHAR NOT NULL,
    parent_position_id              VARCHAR NOT NULL,
    underlying_fund_id              VARCHAR,
    child_position_id               VARCHAR,
    child_target_id                 VARCHAR,
    as_of_date                      DATE NOT NULL,
    depth                           INTEGER NOT NULL,
    relationship_type               VARCHAR NOT NULL,
    weight_raw                      VARCHAR,
    weight_fraction                 DECIMAL(20, 10),
    weight_basis                    VARCHAR NOT NULL,
    effective_exposure_value        DECIMAL(24, 6),
    effective_exposure_fraction     DECIMAL(20, 10),
    coverage_status                 VARCHAR NOT NULL,
    coverage_fraction               DECIMAL(20, 10),
    relationship_confidence         VARCHAR NOT NULL,
    relationship_confidence_basis   VARCHAR,
    relationship_confidence_reason  VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    formula_id                      VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,

    FOREIGN KEY (root_fund_id) REFERENCES fund_master(fund_id),
    FOREIGN KEY (parent_position_id) REFERENCES fund_position(position_id),
    FOREIGN KEY (underlying_fund_id) REFERENCES fund_master(fund_id),
    FOREIGN KEY (child_position_id) REFERENCES fund_position(position_id),
    FOREIGN KEY (child_target_id) REFERENCES investment_target(target_id),

    CHECK (depth >= 1),
    CHECK (relationship_type IN (
        'FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND',
        'SPV_TO_ASSET', 'COINVEST_PARALLEL', 'OTHER'
    )),
    CHECK (weight_basis IN (
        'REPORTED_OWNERSHIP', 'REPORTED_NAV_SHARE', 'REPORTED_EXPOSURE',
        'COMMITMENT_SHARE', 'DERIVED_FROM_VALUES', 'UNKNOWN'
    )),
    CHECK (coverage_status IN ('FULL', 'PARTIAL', 'UNKNOWN')),
    CHECK (relationship_confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (record_status IN ('ACTIVE', 'INACTIVE', 'UNKNOWN')),
    CHECK (
        child_position_id IS NOT NULL
        OR child_target_id IS NOT NULL
        OR underlying_fund_id IS NOT NULL
    ),
    CHECK (weight_fraction IS NULL OR (weight_fraction >= 0 AND weight_fraction <= 1)),
    CHECK (effective_exposure_fraction IS NULL OR (effective_exposure_fraction >= 0 AND effective_exposure_fraction <= 1)),
    CHECK (coverage_fraction IS NULL OR (coverage_fraction >= 0 AND coverage_fraction <= 1)),
    CHECK (coverage_status <> 'FULL' OR coverage_fraction = 1),
    CHECK (coverage_status <> 'PARTIAL' OR coverage_fraction IS NULL OR coverage_fraction < 1),
    CHECK (coverage_status <> 'UNKNOWN' OR coverage_fraction IS NULL),
    CHECK (
        (effective_exposure_value IS NULL AND effective_exposure_fraction IS NULL)
        OR NULLIF(TRIM(formula_id), '') IS NOT NULL
    ),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR synthetic_parameter_set_id IS NULL
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    ),
    CHECK (child_position_id IS NULL OR child_position_id <> parent_position_id)
);

CREATE TABLE IF NOT EXISTS holding_field_lineage (
    lineage_id                      VARCHAR PRIMARY KEY,
    record_type                     VARCHAR NOT NULL,
    record_id                       VARCHAR NOT NULL,
    field_name                      VARCHAR NOT NULL,
    value_raw                       VARCHAR,
    normalized_value                VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    origin_type                     VARCHAR NOT NULL,
    source_holding_id               VARCHAR,
    source_observation_id           VARCHAR,
    source_document_id              VARCHAR,
    source_sha256                   VARCHAR,
    source_page                     VARCHAR,
    source_table                    VARCHAR,
    source_row_label                VARCHAR,
    source_column_label             VARCHAR,
    source_occurrence               INTEGER,
    evidence_quote                  VARCHAR,
    definition_keys                 VARCHAR,
    pair_id                         VARCHAR,
    pair_status                     VARCHAR,
    adjudication_status             VARCHAR,
    source_agents                   VARCHAR,
    source_review_decision_id       VARCHAR,
    formula_id                      VARCHAR,
    parent_lineage_ids              VARCHAR,
    matrix_rule_id                  VARCHAR,
    confidence_level                VARCHAR NOT NULL,
    confidence_basis                VARCHAR,
    effective_date                  DATE,
    available_at                    TIMESTAMP,
    synthetic_parameter_set_id      VARCHAR,
    notes                           VARCHAR,

    CHECK (record_type IN ('OWNER', 'TARGET', 'INSTRUMENT', 'POSITION', 'LOOKTHROUGH')),
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    CHECK (origin_type IN (
        'DIRECT_SOURCE', 'SOURCE_NORMALIZED', 'MATRIX_NORMALIZATION',
        'FORMULA', 'COMPLETION', 'SOURCE_REVIEW', 'SYNTHETIC_FIXTURE', 'OTHER'
    )),
    CHECK (confidence_level IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
    CHECK (source_occurrence IS NULL OR source_occurrence >= 1),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR (
            NULLIF(TRIM(source_document_id), '') IS NOT NULL
            AND NULLIF(TRIM(source_observation_id), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'DERIVED'
        OR (
            NULLIF(TRIM(formula_id), '') IS NOT NULL
            OR NULLIF(TRIM(matrix_rule_id), '') IS NOT NULL
            OR NULLIF(TRIM(parent_lineage_ids), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'SYNTHETIC'
        OR NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
    ),
    CHECK (
        provenance_type <> 'IMPUTED'
        OR (
            NULLIF(TRIM(synthetic_parameter_set_id), '') IS NOT NULL
            OR NULLIF(TRIM(formula_id), '') IS NOT NULL
            OR NULLIF(TRIM(parent_lineage_ids), '') IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_investment_owner_kind
    ON investment_owner(owner_kind);
CREATE INDEX IF NOT EXISTS idx_investment_owner_fund
    ON investment_owner(owner_fund_id);
CREATE INDEX IF NOT EXISTS idx_investment_owner_parent
    ON investment_owner(parent_owner_id);
CREATE INDEX IF NOT EXISTS idx_investment_owner_name
    ON investment_owner(canonical_name);
CREATE INDEX IF NOT EXISTS idx_investment_target_kind
    ON investment_target(target_kind);
CREATE INDEX IF NOT EXISTS idx_investment_target_company_entity
    ON investment_target(company_entity_id);
CREATE INDEX IF NOT EXISTS idx_investment_target_investee_fund
    ON investment_target(investee_fund_id);
CREATE INDEX IF NOT EXISTS idx_investment_target_parent
    ON investment_target(parent_target_id);
CREATE INDEX IF NOT EXISTS idx_investment_target_name
    ON investment_target(canonical_name);
CREATE INDEX IF NOT EXISTS idx_investment_instrument_target
    ON investment_instrument(target_id);
CREATE INDEX IF NOT EXISTS idx_investment_instrument_kind
    ON investment_instrument(instrument_kind);
CREATE INDEX IF NOT EXISTS idx_investment_instrument_identifier
    ON investment_instrument(identifier_type, identifier_value);
CREATE INDEX IF NOT EXISTS idx_fund_position_owner_date
    ON fund_position(owner_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_fund_position_owner_fund_date
    ON fund_position(owner_fund_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_fund_position_instrument_date
    ON fund_position(instrument_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_fund_position_class_date
    ON fund_position(position_class, as_of_date);
CREATE INDEX IF NOT EXISTS idx_fund_position_status
    ON fund_position(record_status);
CREATE INDEX IF NOT EXISTS idx_lookthrough_root_date
    ON lookthrough_edge(root_fund_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_lookthrough_parent_date
    ON lookthrough_edge(parent_position_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_lookthrough_underlying_fund
    ON lookthrough_edge(underlying_fund_id);
CREATE INDEX IF NOT EXISTS idx_lookthrough_child_position
    ON lookthrough_edge(child_position_id);
CREATE INDEX IF NOT EXISTS idx_lookthrough_child_target
    ON lookthrough_edge(child_target_id);
CREATE INDEX IF NOT EXISTS idx_lookthrough_relationship_type
    ON lookthrough_edge(relationship_type);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_record
    ON holding_field_lineage(record_type, record_id);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_observation
    ON holding_field_lineage(source_observation_id);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_holding
    ON holding_field_lineage(source_holding_id);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_document_page
    ON holding_field_lineage(source_document_id, source_page);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_matrix_rule
    ON holding_field_lineage(matrix_rule_id);
CREATE INDEX IF NOT EXISTS idx_holding_field_lineage_formula
    ON holding_field_lineage(formula_id);
-- NORMALIZED HOLDINGS END

CREATE TABLE IF NOT EXISTS synthetic_parameters (
    parameter_id                    VARCHAR PRIMARY KEY,
    parameter_set_id                VARCHAR NOT NULL,
    strategy                        VARCHAR,
    sub_strategy                    VARCHAR,
    parameter_name                  VARCHAR NOT NULL,
    value_numeric                   DECIMAL(30, 10),
    value_text                      VARCHAR,
    unit                            VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    formula_id                      VARCHAR,
    input_record_ids                VARCHAR,
    assumption_basis                VARCHAR,
    adjudication_status             VARCHAR NOT NULL,
    active                          BOOLEAN NOT NULL,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'ASSUMED')),
    CHECK (
        provenance_type <> 'EXTRACTED'
        OR (
            NULLIF(TRIM(source_document_id), '') IS NOT NULL
            AND NULLIF(TRIM(source_anchor), '') IS NOT NULL
            AND NULLIF(TRIM(input_record_ids), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'DERIVED'
        OR (
            NULLIF(TRIM(formula_id), '') IS NOT NULL
            AND NULLIF(TRIM(input_record_ids), '') IS NOT NULL
        )
    ),
    CHECK (
        provenance_type <> 'ASSUMED'
        OR NULLIF(TRIM(assumption_basis), '') IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS quality_results (
    quality_result_id               VARCHAR PRIMARY KEY,
    run_id                          VARCHAR NOT NULL,
    record_table                    VARCHAR NOT NULL,
    record_id                       VARCHAR NOT NULL,
    fund_id                         VARCHAR,
    rule_id                         VARCHAR NOT NULL,
    severity                        VARCHAR NOT NULL,
    status                          VARCHAR NOT NULL,
    actual_value                    VARCHAR,
    expected_value                  VARCHAR,
    -- DOUBLE, not DECIMAL: the rule engine writes these in full float
    -- precision, 4,067 of them in scientific notation, and DECIMAL(30, 10)
    -- rounded them while the parity check cast the CSV to the same type and
    -- read the rounding as agreement.
    difference                      DOUBLE,
    tolerance                       DOUBLE,
    source_document_id              VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    checked_at                      TIMESTAMP NOT NULL,
    notes                           VARCHAR,
    CHECK (status IN ('PASS', 'FAIL', 'SKIP')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS defect_injections (
    defect_id                       VARCHAR PRIMARY KEY,
    parameter_set_id                VARCHAR NOT NULL,
    record_table                    VARCHAR NOT NULL,
    record_id                       VARCHAR NOT NULL,
    fund_id                         VARCHAR NOT NULL,
    defect_type                     VARCHAR NOT NULL,
    field_name                      VARCHAR NOT NULL,
    clean_value                     VARCHAR,
    injected_value                  VARCHAR,
    expected_rule_id                VARCHAR NOT NULL,
    seed                            BIGINT NOT NULL,
    notes                           VARCHAR
);

CREATE TABLE IF NOT EXISTS benchmark_returns (
    benchmark_return_id             VARCHAR PRIMARY KEY,
    benchmark_id                    VARCHAR NOT NULL,
    benchmark_name                  VARCHAR NOT NULL,
    return_date                     DATE NOT NULL,
    periodicity                     VARCHAR NOT NULL,
    -- DOUBLE, not DECIMAL: 42,498 of the 42,876 CSV returns carry more than
    -- ten decimals, and a ten-place DECIMAL moved 853 KS-PME and 745 Direct
    -- Alpha results recomputed from the database at the tenth decimal.
    return_value                    DOUBLE NOT NULL,
    currency                        VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    source_page                     VARCHAR,
    source_anchor                   VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    record_status                   VARCHAR NOT NULL,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED'))
);

CREATE TABLE IF NOT EXISTS portfolio_allocations (
    allocation_id                   VARCHAR PRIMARY KEY,
    portfolio_id                    VARCHAR NOT NULL,
    as_of_date                      DATE NOT NULL,
    fund_id                         VARCHAR,
    strategy                        VARCHAR,
    sub_strategy                    VARCHAR,
    target_weight                   DECIMAL(20, 10) NOT NULL,
    minimum_weight                  DECIMAL(20, 10),
    maximum_weight                  DECIMAL(20, 10),
    commitment_amount               DECIMAL(24, 6),
    nav_amount                      DECIMAL(24, 6),
    unfunded_amount                 DECIMAL(24, 6),
    expected_return                 DECIMAL(20, 10),
    expected_volatility             DECIMAL(20, 10),
    liquidity_score                 DECIMAL(20, 10),
    provenance_type                 VARCHAR NOT NULL,
    source_document_id              VARCHAR,
    synthetic_parameter_set_id      VARCHAR,
    optimization_run_id             VARCHAR,
    record_status                   VARCHAR NOT NULL,
    -- The printed industry and the taxonomy reading of the printed grouping the
    -- row above states, carried from the fund period the allocation was built
    -- from. Grouping on strategy alone joins a printed word to nothing.
    sector                          VARCHAR,
    canonical_asset_class           VARCHAR,
    canonical_strategy              VARCHAR,
    canonical_sub_strategy          VARCHAR,
    canonical_sector                VARCHAR,
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED')),
    FOREIGN KEY (fund_id) REFERENCES fund_master(fund_id)
);

CREATE TABLE IF NOT EXISTS fund_metrics (
    analysis_result_id              VARCHAR PRIMARY KEY,
    entity_id                       VARCHAR NOT NULL,
    as_of_date                      DATE NOT NULL,
    metric_id                       VARCHAR NOT NULL,
    value_numeric                   DECIMAL(30, 10) NOT NULL,
    unit                            VARCHAR,
    formula_id                      VARCHAR NOT NULL,
    input_record_ids                VARCHAR NOT NULL,
    benchmark_id                    VARCHAR,
    provenance_type                 VARCHAR NOT NULL,
    quality_population              VARCHAR NOT NULL,
    notes                           VARCHAR,
    -- What the rate behind the row was measured on. A multiple or a rate whose
    -- fee basis stayed in the extraction layer cannot be compared with another.
    input_fee_basis                 VARCHAR,
    input_method                    VARCHAR,
    -- entity_id names whatever the metric was measured on. The fund-model
    -- population measures funds; the regression fixture measures LP positions,
    -- whose IDs are absent from fund_master by design. A foreign key here would
    -- refuse the fixture rebuild, so entity_id stays unconstrained, as
    -- quality_results.record_id does for the same reason.
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED'))
);

CREATE TABLE IF NOT EXISTS pme_results (
    analysis_result_id              VARCHAR PRIMARY KEY,
    entity_id                       VARCHAR NOT NULL,
    as_of_date                      DATE NOT NULL,
    metric_id                       VARCHAR NOT NULL,
    value_numeric                   DECIMAL(30, 10) NOT NULL,
    unit                            VARCHAR,
    formula_id                      VARCHAR NOT NULL,
    input_record_ids                VARCHAR NOT NULL,
    benchmark_id                    VARCHAR NOT NULL,
    provenance_type                 VARCHAR NOT NULL,
    quality_population              VARCHAR NOT NULL,
    notes                           VARCHAR,
    -- Why this row carries the benchmark it carries: `mapped` when the fund's
    -- canonical strategy named it in strategy-benchmark-map.csv, otherwise the
    -- default row of that matrix which fired.
    benchmark_selection             VARCHAR,
    input_fee_basis                 VARCHAR,
    input_method                    VARCHAR,
    -- entity_id is polymorphic here for the same reason it is on fund_metrics.
    CHECK (provenance_type IN ('EXTRACTED', 'DERIVED', 'SYNTHETIC', 'IMPUTED'))
);

CREATE OR REPLACE VIEW vw_fund_period_math AS
SELECT
    fp.*,
    CASE WHEN paid_in_capital_itd > 0
         THEN distributions_itd / paid_in_capital_itd END AS recomputed_dpi,
    CASE WHEN paid_in_capital_itd > 0
         THEN nav / paid_in_capital_itd END AS recomputed_rvpi,
    CASE WHEN paid_in_capital_itd > 0
         THEN (distributions_itd + nav) / paid_in_capital_itd END AS recomputed_tvpi,
    dpi + rvpi AS component_tvpi,
    beginning_nav
      + contributions_period
      - distributions_period
      + realized_gain_period
      + unrealized_gain_period
      + net_income_period
      - management_fee_period
      - other_expenses_period AS recomputed_ending_nav
FROM fund_periods fp;

CREATE OR REPLACE VIEW vw_analytics_ready_fund_periods AS
SELECT fp.*
FROM fund_periods fp
WHERE fp.record_status = 'ACTIVE'
  AND NOT EXISTS (
      SELECT 1
      FROM quality_results qr
      WHERE qr.record_table = 'fund_periods'
        AND qr.record_id = fp.fund_period_id
        AND qr.status = 'FAIL'
        AND qr.severity = 'error'
  );

CREATE OR REPLACE VIEW vw_quality_scorecard AS
SELECT
    run_id,
    rule_id,
    severity,
    COUNT(*) AS checks,
    COUNT(*) FILTER (WHERE status = 'PASS') AS passes,
    COUNT(*) FILTER (WHERE status = 'FAIL') AS failures,
    COUNT(*) FILTER (WHERE status = 'SKIP') AS skips,
    COUNT(*) FILTER (WHERE status = 'PASS')::DOUBLE
      / NULLIF(COUNT(*) FILTER (WHERE status IN ('PASS', 'FAIL')), 0) AS pass_rate_excluding_skips
FROM quality_results
GROUP BY run_id, rule_id, severity;
