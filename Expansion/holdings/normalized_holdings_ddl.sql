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
