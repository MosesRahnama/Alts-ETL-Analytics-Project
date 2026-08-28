-- =============================================================================
-- The extracted corpus, flattened.
--
-- Source: data/extracted/tables/*.csv, written by src.flatten.flatten_extracted
-- from the adjudicated rounds. Target: data/warehouse/extracted.duckdb.
--
-- This is the document-faithful layer. One row per printed cell, carrying the
-- page, the grid position, the evidence quote, and which agents produced it.
-- It stays separate from data/warehouse/alts.duckdb, the analytical fund-level
-- database, because promoting a printed observation into a fund fact needs a
-- resolved entity and a controlled metric, and that promotion is its own step.
--
-- Every join is declared as a foreign key, so the database itself states
-- how the tables relate and refuses a row that points at nothing. The wide
-- tables in 04_extracted_wide_ddl.sql load after this file.
-- =============================================================================

-- One row per source document that reached extraction.
CREATE TABLE IF NOT EXISTS dim_document (
    document_id             VARCHAR NOT NULL,
    filename                VARCHAR,
    canonical_doc_type      VARCHAR NOT NULL,
    route                   VARCHAR NOT NULL,
    product_tier            VARCHAR,
    source_sha256           VARCHAR NOT NULL,
    issuer                  VARCHAR,
    issuer_type             VARCHAR,
    file_ext                VARCHAR,
    ledger_page_count       INTEGER,
    is_redacted             VARCHAR,
    source_url              VARCHAR,
    retrieved_at            VARCHAR,
    pages_covered           INTEGER NOT NULL,
    pages_with_data         INTEGER NOT NULL,
    observation_count       INTEGER NOT NULL,
    holding_count           INTEGER NOT NULL,
    PRIMARY KEY (document_id)
);

-- One row per page the extractors reported on, whether or not it held data.
-- A NO_ELIGIBLE_DATA page is a finding, not an absence.
CREATE TABLE IF NOT EXISTS dim_page (
    page_id                     VARCHAR NOT NULL,
    document_id                 VARCHAR NOT NULL,
    route                       VARCHAR NOT NULL,
    source_page                 VARCHAR NOT NULL,
    page_status                 VARCHAR NOT NULL,
    layout_checked              VARCHAR,
    source_structures           VARCHAR,
    relevant_record_families    VARCHAR,
    expected_observation_count  INTEGER,
    records_written             INTEGER,
    notes                       VARCHAR,
    PRIMARY KEY (page_id),
    FOREIGN KEY (document_id) REFERENCES dim_document(document_id),
    -- csv_wide_contract.PAGE_STATUSES
    CHECK (page_status IN (
        'NO_ELIGIBLE_DATA', 'ELIGIBLE_DATA_EXTRACTED', 'DEFERRED_BY_SCOPE', 'REFERENCE_ONLY', 'UNREADABLE'
    ))
);

-- One row per resolved entity. Identity comes from the conversion matrices in
-- data/normalization/, never from a parser.
CREATE TABLE IF NOT EXISTS dim_entity (
    entity_id           VARCHAR NOT NULL,
    entity_kind         VARCHAR NOT NULL,
    canonical_name      VARCHAR NOT NULL,
    -- The sponsor series a fund belongs to, named by the normalizer. It is a
    -- search key for the manager round, never a claim about who runs the fund.
    fund_family         VARCHAR,
    -- The general partner, settled by the two-agent web round. A manager whose
    -- source starts with "FAMILY <key>:" was settled once for the sponsor
    -- family and propagated to every member, rather than looked up per fund.
    manager_name         VARCHAR,
    manager_source      VARCHAR,
    alias_count         INTEGER NOT NULL,
    observation_count   INTEGER NOT NULL,
    PRIMARY KEY (entity_id),
    CHECK (entity_kind IN ('fund', 'manager', 'lp', 'plan', 'company'))
);

-- Every entity name as printed. entity_id stays NULL until the matrix settles
-- the name, so an undecided name is visible here instead of dropping its rows.
CREATE TABLE IF NOT EXISTS entity_alias (
    alias_id            VARCHAR NOT NULL,
    raw_name            VARCHAR NOT NULL,
    normalized_name     VARCHAR NOT NULL,
    entity_kind         VARCHAR NOT NULL,
    entity_id           VARCHAR,
    standardized_name   VARCHAR,
    match_method        VARCHAR NOT NULL,
    first_seen_document VARCHAR NOT NULL,
    documents           VARCHAR,
    occurrences         INTEGER NOT NULL,
    PRIMARY KEY (alias_id),
    FOREIGN KEY (entity_id) REFERENCES dim_entity(entity_id),
    CHECK (match_method IN ('matrix_decided', 'matrix_auto', 'unresolved', 'scope_label')),
    -- A settled alias carries an entity; an unsettled one must not pretend to.
    CHECK (match_method NOT IN ('unresolved', 'scope_label') OR entity_id IS NULL)
);

-- The metric vocabulary actually printed, keyed record_family.metric_category.
-- in_catalogue false means a value escaped EXTRACTION-METRIC-CATEGORIES.csv.
-- standard_measure, measure_scope, and note come from
-- data/schemas/METRIC-STANDARD-MEASURES.csv, one row per metric_id.
CREATE TABLE IF NOT EXISTS dim_metric (
    metric_id           VARCHAR NOT NULL,
    record_family       VARCHAR NOT NULL,
    metric_category     VARCHAR,
    in_catalogue        BOOLEAN NOT NULL,
    value_kind          VARCHAR,
    observation_count   INTEGER NOT NULL,
    standard_measure    VARCHAR NOT NULL,
    measure_scope       VARCHAR NOT NULL,
    note                VARCHAR,
    PRIMARY KEY (metric_id)
);

-- The central fact: one row per printed cell the adjudicator accepted.
CREATE TABLE IF NOT EXISTS fact_observation (
    observation_id          VARCHAR NOT NULL,
    document_id             VARCHAR NOT NULL,
    route                   VARCHAR NOT NULL,
    canonical_doc_type      VARCHAR NOT NULL,
    product_tier            VARCHAR,
    page_id                 VARCHAR NOT NULL,
    source_page             VARCHAR NOT NULL,
    source_structure_type   VARCHAR NOT NULL,
    source_section          VARCHAR,
    source_table            VARCHAR,
    source_row_label        VARCHAR,
    source_column_label     VARCHAR,
    source_occurrence       INTEGER NOT NULL,
    record_family           VARCHAR NOT NULL,
    metric_id               VARCHAR NOT NULL,
    metric_category         VARCHAR,
    metric_name             VARCHAR,
    subject_type            VARCHAR NOT NULL,
    subject_alias_id        VARCHAR,
    subject_entity_id       VARCHAR,
    subject_name            VARCHAR,
    subject_standardized_name VARCHAR,
    subject_manager_name    VARCHAR,
    manager_alias_id        VARCHAR,
    manager_entity_id       VARCHAR,
    investor_alias_id       VARCHAR,
    investor_entity_id      VARCHAR,
    portfolio_name          VARCHAR,
    asset_class             VARCHAR,
    strategy                VARCHAR,
    geography               VARCHAR,
    vintage_year            VARCHAR,
    horizon                 VARCHAR,
    date_precision          VARCHAR,
    as_of_date_raw          VARCHAR,
    as_of_date              DATE,
    period_start_raw        VARCHAR,
    period_start            DATE,
    period_end_raw          VARCHAR,
    period_end              DATE,
    value_kind              VARCHAR NOT NULL,
    value_raw               VARCHAR,
    value_numeric           DECIMAL(30, 6),
    value_text              VARCHAR,
    value_sign              VARCHAR,
    currency                VARCHAR,
    unit                    VARCHAR,
    unit_scale              VARCHAR NOT NULL,
    unit_scale_multiplier   DECIMAL(20, 2) NOT NULL,
    currency_scale_raw      VARCHAR,
    term_category           VARCHAR,
    basis_raw               VARCHAR,
    condition_raw           VARCHAR,
    evidence_quote          VARCHAR NOT NULL,
    evidence_class          VARCHAR NOT NULL,
    adjudication_status     VARCHAR NOT NULL,
    source_agents           VARCHAR,
    extractor_model         VARCHAR,
    contract_version        VARCHAR NOT NULL,
    notes                   VARCHAR,
    PRIMARY KEY (observation_id),
    FOREIGN KEY (document_id) REFERENCES dim_document(document_id),
    FOREIGN KEY (page_id) REFERENCES dim_page(page_id),
    FOREIGN KEY (metric_id) REFERENCES dim_metric(metric_id),
    FOREIGN KEY (subject_alias_id) REFERENCES entity_alias(alias_id),
    FOREIGN KEY (subject_entity_id) REFERENCES dim_entity(entity_id),
    FOREIGN KEY (manager_alias_id) REFERENCES entity_alias(alias_id),
    FOREIGN KEY (manager_entity_id) REFERENCES dim_entity(entity_id),
    FOREIGN KEY (investor_alias_id) REFERENCES entity_alias(alias_id),
    FOREIGN KEY (investor_entity_id) REFERENCES dim_entity(entity_id),
    CHECK (value_kind IN ('number', 'currency', 'percent', 'multiple', 'text', 'none')),
    CHECK (unit_scale IN ('absolute', 'thousands', 'millions', 'billions', 'trillions')),
    -- csv_wide_contract.EVIDENCE_CLASSES
    CHECK (evidence_class IN ('actual', 'illustrative', 'template', 'requirement', 'definition', 'redacted', 'unknown')),
    -- csv_wide_contract.SOURCE_STRUCTURE_TYPES
    CHECK (source_structure_type IN ('DOCUMENT', 'TABLE', 'FIGURE', 'NARRATIVE', 'FORM', 'FOOTNOTE', 'SCHEDULE')),
    -- csv_wide_contract.SUBJECT_TYPES
    CHECK (subject_type IN ('document', 'reporting_entity', 'fund', 'portfolio', 'investment', 'manager', 'investor', 'asset_class', 'benchmark', 'peer_group', 'market_series', 'fee_scope', 'cash_flow', 'valuation_subject', 'foundation', 'program_related_investment', 'service_provider', 'clause_party', 'subscription', 'other_printed_scope')),
    CHECK (adjudication_status IN ('RESOLVED', 'ADDED', 'VERIFIED_ONE_SIDED')),
    -- A row states a number or it states text. The one exception is the
    -- per-document context row, whose whole content is the document's own name
    -- and the quote it was read from.
    CHECK (
        value_numeric IS NOT NULL
        OR value_text IS NOT NULL
        OR value_raw IS NOT NULL
        OR record_family = 'document_context'
    )
);

-- The blind-lane and adjudication path behind each published observation.
CREATE TABLE IF NOT EXISTS observation_lineage (
    observation_id          VARCHAR NOT NULL,
    document_id             VARCHAR NOT NULL,
    source_page             VARCHAR,
    pair_id                 VARCHAR,
    pair_status             VARCHAR NOT NULL,
    a_row_number            INTEGER,
    b_row_number            INTEGER,
    difference_fields       VARCHAR,
    resolution_decision     VARCHAR,
    resolution_reason       VARCHAR,
    adjudication_status     VARCHAR,
    source_agents           VARCHAR,
    source_sha256           VARCHAR,
    PRIMARY KEY (observation_id),
    FOREIGN KEY (observation_id) REFERENCES fact_observation(observation_id),
    FOREIGN KEY (document_id) REFERENCES dim_document(document_id)
);

-- Schedule-of-investments lines, pivoted from fact_observation cells so one row
-- is one printed holding. observation_ids keeps the cells it was built from.
CREATE TABLE IF NOT EXISTS fact_holding (
    holding_id              VARCHAR NOT NULL,
    document_id             VARCHAR NOT NULL,
    route                   VARCHAR NOT NULL,
    page_id                 VARCHAR NOT NULL,
    source_page             VARCHAR NOT NULL,
    source_table            VARCHAR,
    holding_label           VARCHAR,
    holding_alias_id        VARCHAR,
    holding_entity_id       VARCHAR,
    subject_type            VARCHAR,
    source_occurrence       INTEGER,
    as_of_date_raw          VARCHAR,
    as_of_date              DATE,
    currency                VARCHAR,
    unit_scale              VARCHAR,
    unit_scale_multiplier   DECIMAL(20, 2),
    fair_value              DECIMAL(30, 6),
    market_value            DECIMAL(30, 6),
    cost                    DECIMAL(30, 6),
    notional_amount         DECIMAL(30, 6),
    quantity                DECIMAL(30, 6),
    portfolio_weight        DECIMAL(30, 6),
    interest_rate           DECIMAL(30, 6),
    maturity_date_raw       VARCHAR,
    observation_ids         VARCHAR NOT NULL,
    observation_count       INTEGER NOT NULL,
    collision_note          VARCHAR,
    PRIMARY KEY (holding_id),
    FOREIGN KEY (document_id) REFERENCES dim_document(document_id),
    FOREIGN KEY (page_id) REFERENCES dim_page(page_id),
    FOREIGN KEY (holding_alias_id) REFERENCES entity_alias(alias_id),
    FOREIGN KEY (holding_entity_id) REFERENCES dim_entity(entity_id)
);

-- The entity backlog: printed names the matrix has yet to settle.
CREATE TABLE IF NOT EXISTS unresolved_names (
    entity_kind         VARCHAR NOT NULL,
    raw_name            VARCHAR NOT NULL,
    normalized_name     VARCHAR NOT NULL,
    occurrences         INTEGER NOT NULL,
    documents           VARCHAR,
    reason              VARCHAR NOT NULL,
    PRIMARY KEY (entity_kind, raw_name)
);

-- =============================================================================
-- VIEWS. Every derivation the flatten refused to bake into the data.
-- =============================================================================

-- Scaling kept in the open. A money value printed under a "in thousands" heading
-- multiplies out here, where the raw value and the multiplier stay visible
-- beside the result, so a reviewer can see and reject the arithmetic.
CREATE OR REPLACE VIEW vw_observation_scaled AS
SELECT
    o.*,
    CASE
        WHEN o.value_kind IN ('currency', 'number') AND o.value_numeric IS NOT NULL
        THEN o.value_numeric * o.unit_scale_multiplier
    END AS value_scaled
FROM fact_observation o;

-- Observations that carry a resolved entity, ready for fund-level promotion.
CREATE OR REPLACE VIEW vw_observation_resolved AS
SELECT o.*, e.entity_kind, e.canonical_name, e.fund_family, e.manager_name
FROM fact_observation o
JOIN dim_entity e ON e.entity_id = o.subject_entity_id;

-- How far the manager round has got, and how much of it came from a sibling.
CREATE OR REPLACE VIEW vw_manager_coverage AS
SELECT
    COALESCE(NULLIF(fund_family, ''), '(no family)')                    AS fund_family,
    COUNT(*)                                                            AS funds,
    COUNT(*) FILTER (WHERE COALESCE(manager_name, '') <> '')            AS with_manager,
    COUNT(*) FILTER (WHERE manager_source LIKE 'FAMILY %')              AS family_propagated,
    SUM(observation_count)                                              AS observations
FROM dim_entity
WHERE entity_kind = 'fund'
GROUP BY ALL;

-- Coverage of the corpus, one row per document.
CREATE OR REPLACE VIEW vw_document_coverage AS
SELECT
    d.document_id,
    d.canonical_doc_type,
    d.route,
    d.pages_covered,
    d.pages_with_data,
    d.observation_count,
    d.holding_count,
    COUNT(*) FILTER (WHERE p.page_status = 'NO_ELIGIBLE_DATA') AS pages_no_eligible_data,
    SUM(p.expected_observation_count)                          AS expected_observations,
    SUM(p.records_written)                                     AS written_observations
FROM dim_document d
JOIN dim_page p ON p.document_id = d.document_id
GROUP BY ALL;
