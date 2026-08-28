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
    difference                      DECIMAL(30, 10),
    tolerance                       DECIMAL(30, 10),
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
    return_value                    DECIMAL(20, 10) NOT NULL,
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
