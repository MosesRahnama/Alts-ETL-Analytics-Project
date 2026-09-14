-- Normalized holdings QA for Alts-ETL-Analytics-Project
-- Target warehouse: data/warehouse/alts.duckdb
-- Prerequisite: normalized_holdings_ddl.sql (or equivalent tables) already loaded.
--
-- Contract:
--   * Every QA view returns violations only.
--   * A clean model returns zero rows from vw_normalized_holdings_qa.
--   * ERROR = publication blocker.
--   * WARN  = incomplete or suspicious state that requires review.
--
-- DuckDB syntax follows current WITH RECURSIVE graph traversal semantics.

-- =============================================================================
-- 1. FUND_INTEREST target and position validation
-- =============================================================================

CREATE OR REPLACE VIEW vw_qa_fund_interest_target AS

SELECT
    'NH001_FUND_INTEREST_TARGET_KIND' AS rule_id,
    'ERROR' AS severity,
    'investment_instrument' AS record_table,
    ii.instrument_id AS record_id,
    ii.target_id AS related_record_id,
    it.target_kind AS actual_value,
    'FUND' AS expected_value,
    'FUND_INTEREST must point to an investment_target whose target_kind is FUND.' AS details
FROM investment_instrument ii
JOIN investment_target it ON it.target_id = ii.target_id
WHERE ii.instrument_kind = 'FUND_INTEREST'
  AND it.target_kind <> 'FUND'

UNION ALL

SELECT
    'NH002_FUND_INTEREST_TARGET_IDENTITY' AS rule_id,
    CASE WHEN it.identity_status = 'RESOLVED' THEN 'ERROR' ELSE 'WARN' END AS severity,
    'investment_instrument' AS record_table,
    ii.instrument_id AS record_id,
    ii.target_id AS related_record_id,
    COALESCE(it.investee_fund_id, '') AS actual_value,
    'nonblank investee_fund_id for a resolved FUND target' AS expected_value,
    'A FUND_INTEREST target should resolve to fund_master before source publication.' AS details
FROM investment_instrument ii
JOIN investment_target it ON it.target_id = ii.target_id
WHERE ii.instrument_kind = 'FUND_INTEREST'
  AND it.target_kind = 'FUND'
  AND it.investee_fund_id IS NULL

UNION ALL

SELECT
    'NH003_POSITION_FUND_INTEREST_CLASS' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    fp.position_class || ' / ' || ii.instrument_kind AS actual_value,
    'FUND_INTEREST / FUND_INTEREST' AS expected_value,
    'A position is a FUND_INTEREST if and only if its instrument is a FUND_INTEREST.' AS details
FROM fund_position fp
JOIN investment_instrument ii ON ii.instrument_id = fp.instrument_id
WHERE (fp.position_class = 'FUND_INTEREST' AND ii.instrument_kind <> 'FUND_INTEREST')
   OR (fp.position_class <> 'FUND_INTEREST' AND ii.instrument_kind = 'FUND_INTEREST')

UNION ALL

SELECT
    'NH004_DEBT_POSITION_CLASS' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    fp.position_class || ' / ' || ii.instrument_kind AS actual_value,
    'DEBT_INVESTMENT / debt instrument' AS expected_value,
    'Loan, bond, mezzanine, revolver, and other debt instruments must classify as DEBT_INVESTMENT.' AS details
FROM fund_position fp
JOIN investment_instrument ii ON ii.instrument_id = fp.instrument_id
WHERE ii.instrument_kind IN ('LOAN', 'BOND', 'MEZZANINE_DEBT', 'REVOLVER', 'OTHER_DEBT')
  AND fp.position_class <> 'DEBT_INVESTMENT';


-- =============================================================================
-- 2. Owner consistency
-- =============================================================================

CREATE OR REPLACE VIEW vw_qa_owner_fund AS

SELECT
    'NH010_POSITION_OWNER_FUND_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.owner_id AS related_record_id,
    COALESCE(fp.owner_fund_id, '') || ' / ' || COALESCE(io.owner_fund_id, '') AS actual_value,
    'fund_position.owner_fund_id = investment_owner.owner_fund_id' AS expected_value,
    'The position and its owner disagree about the linked fund identity.' AS details
FROM fund_position fp
JOIN investment_owner io ON io.owner_id = fp.owner_id
WHERE fp.owner_fund_id IS DISTINCT FROM io.owner_fund_id

UNION ALL

SELECT
    'NH011_OWNER_FUND_KIND_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'investment_owner' AS record_table,
    io.owner_id AS record_id,
    COALESCE(io.owner_fund_id, '') AS related_record_id,
    io.owner_kind AS actual_value,
    'fund' AS expected_value,
    'A nonblank owner_fund_id is valid only for a fund owner.' AS details
FROM investment_owner io
WHERE io.owner_fund_id IS NOT NULL
  AND io.owner_kind <> 'fund'

UNION ALL

SELECT
    'NH012_OWNER_SOURCE_FUND_LINK_MISSING' AS rule_id,
    'ERROR' AS severity,
    'investment_owner' AS record_table,
    io.owner_id AS record_id,
    COALESCE(io.source_entity_id, '') AS related_record_id,
    COALESCE(io.owner_fund_id, '') AS actual_value,
    io.source_entity_id AS expected_value,
    'When the reviewed source entity is already a FUND_ identity, owner_fund_id must carry that same fund ID.' AS details
FROM investment_owner io
WHERE io.owner_kind = 'fund'
  AND io.source_entity_id LIKE 'FUND_%'
  AND io.owner_fund_id IS DISTINCT FROM io.source_entity_id

UNION ALL

SELECT
    'NH013_POSITION_OWNER_LINK_MISSING' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.owner_id AS related_record_id,
    fp.owner_id AS actual_value,
    'existing investment_owner.owner_id' AS expected_value,
    'Every position must resolve through investment_owner.' AS details
FROM fund_position fp
LEFT JOIN investment_owner io ON io.owner_id = fp.owner_id
WHERE io.owner_id IS NULL;


-- =============================================================================
-- 3. Look-through relationship requirements
-- =============================================================================

CREATE OR REPLACE VIEW vw_qa_lookthrough_relationship AS

-- Fund look-through must start from a fund-interest position.
SELECT
    'NH020_LOOKTHROUGH_PARENT_NOT_FUND_INTEREST' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    fp.position_class || ' / ' || ii.instrument_kind AS actual_value,
    'FUND_INTEREST / FUND_INTEREST' AS expected_value,
    'Fund look-through relationships must start from a fund-interest position and instrument.' AS details
FROM lookthrough_edge le
JOIN fund_position fp ON fp.position_id = le.parent_position_id
JOIN investment_instrument ii ON ii.instrument_id = fp.instrument_id
WHERE le.relationship_type IN ('FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND')
  AND (fp.position_class <> 'FUND_INTEREST' OR ii.instrument_kind <> 'FUND_INTEREST')

UNION ALL

-- The parent fund-interest instrument must point to a FUND target.
SELECT
    'NH021_LOOKTHROUGH_PARENT_TARGET_NOT_FUND' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    it.target_id AS related_record_id,
    it.target_kind AS actual_value,
    'FUND' AS expected_value,
    'A fund look-through edge must originate from an instrument whose target is a FUND.' AS details
FROM lookthrough_edge le
JOIN fund_position fp ON fp.position_id = le.parent_position_id
JOIN investment_instrument ii ON ii.instrument_id = fp.instrument_id
JOIN investment_target it ON it.target_id = ii.target_id
WHERE le.relationship_type IN ('FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND')
  AND it.target_kind <> 'FUND'

UNION ALL

-- These relationship types require the immediate underlying fund to be known.
SELECT
    'NH022_LOOKTHROUGH_UNDERLYING_FUND_REQUIRED' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    COALESCE(le.underlying_fund_id, '') AS actual_value,
    'nonblank underlying_fund_id' AS expected_value,
    'Fund-to-fund and fund-to-underlying-holding relationships require the immediate underlying fund.' AS details
FROM lookthrough_edge le
WHERE le.relationship_type IN ('FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND')
  AND le.underlying_fund_id IS NULL

UNION ALL

-- The target of the parent fund-interest instrument must be the same underlying fund.
SELECT
    'NH023_PARENT_TARGET_FUND_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    it.target_id AS related_record_id,
    COALESCE(it.investee_fund_id, '') || ' / ' || COALESCE(le.underlying_fund_id, '') AS actual_value,
    'investment_target.investee_fund_id = lookthrough_edge.underlying_fund_id' AS expected_value,
    'The held fund named by the parent instrument must be the same fund named by the look-through edge.' AS details
FROM lookthrough_edge le
JOIN fund_position fp ON fp.position_id = le.parent_position_id
JOIN investment_instrument ii ON ii.instrument_id = fp.instrument_id
JOIN investment_target it ON it.target_id = ii.target_id
WHERE le.relationship_type IN ('FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND')
  AND le.underlying_fund_id IS NOT NULL
  AND it.investee_fund_id IS DISTINCT FROM le.underlying_fund_id

UNION ALL

-- A holding relationship must actually identify an underlying holding.
SELECT
    'NH024_UNDERLYING_HOLDING_REQUIRED' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    '' AS actual_value,
    'child_position_id or child_target_id' AS expected_value,
    'FUND_TO_UNDERLYING_HOLDING must identify the underlying position or target, not only the underlying fund.' AS details
FROM lookthrough_edge le
WHERE le.relationship_type = 'FUND_TO_UNDERLYING_HOLDING'
  AND le.child_position_id IS NULL
  AND le.child_target_id IS NULL

UNION ALL

-- If an underlying position is present, its owner must be the immediate underlying fund.
SELECT
    'NH025_CHILD_POSITION_OWNER_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.child_position_id AS related_record_id,
    COALESCE(cp.owner_fund_id, '') AS actual_value,
    COALESCE(le.underlying_fund_id, '') AS expected_value,
    'An underlying child position must be owned by the underlying fund named on the edge.' AS details
FROM lookthrough_edge le
JOIN fund_position cp ON cp.position_id = le.child_position_id
WHERE le.relationship_type = 'FUND_TO_UNDERLYING_HOLDING'
  AND le.underlying_fund_id IS NOT NULL
  AND cp.owner_fund_id IS DISTINCT FROM le.underlying_fund_id

UNION ALL

-- If both child position and child target are given, they must identify the same target.
SELECT
    'NH026_CHILD_POSITION_TARGET_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.child_position_id AS related_record_id,
    ci.target_id || ' / ' || le.child_target_id AS actual_value,
    'child position instrument target = child_target_id' AS expected_value,
    'child_position_id and child_target_id cannot describe different investments.' AS details
FROM lookthrough_edge le
JOIN fund_position cp ON cp.position_id = le.child_position_id
JOIN investment_instrument ci ON ci.instrument_id = cp.instrument_id
WHERE le.child_position_id IS NOT NULL
  AND le.child_target_id IS NOT NULL
  AND ci.target_id <> le.child_target_id

UNION ALL

-- The first look-through level starts from a position owned by the root fund.
SELECT
    'NH027_DEPTH1_ROOT_OWNER_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    COALESCE(pp.owner_fund_id, '') AS actual_value,
    le.root_fund_id AS expected_value,
    'A depth-1 look-through edge must start from a position directly owned by root_fund_id.' AS details
FROM lookthrough_edge le
JOIN fund_position pp ON pp.position_id = le.parent_position_id
WHERE le.depth = 1
  AND pp.owner_fund_id IS DISTINCT FROM le.root_fund_id

UNION ALL

-- SPV relationships must start from an SPV target.
SELECT
    'NH028_SPV_PARENT_TARGET_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    pit.target_id AS related_record_id,
    pit.target_kind AS actual_value,
    'SPV' AS expected_value,
    'SPV_TO_ASSET must start from a position whose instrument target is an SPV.' AS details
FROM lookthrough_edge le
JOIN fund_position pp ON pp.position_id = le.parent_position_id
JOIN investment_instrument pii ON pii.instrument_id = pp.instrument_id
JOIN investment_target pit ON pit.target_id = pii.target_id
WHERE le.relationship_type = 'SPV_TO_ASSET'
  AND pit.target_kind <> 'SPV'

UNION ALL

-- A known basis should normally have a parsed weight.
SELECT
    'NH029_WEIGHT_BASIS_VALUE_MISMATCH' AS rule_id,
    'WARN' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    le.weight_basis || ' / ' || COALESCE(CAST(le.weight_fraction AS VARCHAR), '') AS actual_value,
    'UNKNOWN with NULL, or stated basis with parsed weight_fraction' AS expected_value,
    'Weight basis and normalized weight should agree; an unparsed source weight may remain a reviewed warning.' AS details
FROM lookthrough_edge le
WHERE (le.weight_basis = 'UNKNOWN' AND le.weight_fraction IS NOT NULL)
   OR (le.weight_basis <> 'UNKNOWN' AND le.weight_fraction IS NULL)

UNION ALL

-- Coverage labels and values must agree, even if data bypassed DDL checks.
SELECT
    'NH030_COVERAGE_STATUS_VALUE_MISMATCH' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    le.coverage_status || ' / ' || COALESCE(CAST(le.coverage_fraction AS VARCHAR), '') AS actual_value,
    'FULL=1; PARTIAL<1; UNKNOWN=NULL' AS expected_value,
    'Look-through coverage label and coverage_fraction are inconsistent.' AS details
FROM lookthrough_edge le
WHERE (le.coverage_status = 'FULL' AND le.coverage_fraction IS DISTINCT FROM 1)
   OR (le.coverage_status = 'PARTIAL' AND le.coverage_fraction IS NOT NULL AND le.coverage_fraction >= 1)
   OR (le.coverage_status = 'UNKNOWN' AND le.coverage_fraction IS NOT NULL)

UNION ALL

-- Derived exposure requires a named formula.
SELECT
    'NH031_EFFECTIVE_EXPOSURE_FORMULA_REQUIRED' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    COALESCE(le.formula_id, '') AS actual_value,
    'nonblank formula_id' AS expected_value,
    'Any normalized effective exposure value or fraction must name its derivation formula.' AS details
FROM lookthrough_edge le
WHERE (le.effective_exposure_value IS NOT NULL OR le.effective_exposure_fraction IS NOT NULL)
  AND NULLIF(TRIM(le.formula_id), '') IS NULL;


-- =============================================================================
-- 4. Range and date checks
-- =============================================================================

CREATE OR REPLACE VIEW vw_qa_normalized_ranges AS

SELECT
    'NH040_FUND_OWNERSHIP_RANGE' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    CAST(fp.fund_ownership_fraction AS VARCHAR) AS actual_value,
    '0 <= value <= 1' AS expected_value,
    'Normalized ownership fractions are unit fractions, not percentage points.' AS details
FROM fund_position fp
WHERE fp.fund_ownership_fraction IS NOT NULL
  AND (fp.fund_ownership_fraction < 0 OR fp.fund_ownership_fraction > 1)

UNION ALL

SELECT
    'NH041_PORTFOLIO_WEIGHT_RANGE' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    CAST(fp.portfolio_weight_fraction AS VARCHAR) AS actual_value,
    '0 <= value <= 1' AS expected_value,
    'Normalized portfolio weights are unit fractions, not percentage points.' AS details
FROM fund_position fp
WHERE fp.portfolio_weight_fraction IS NOT NULL
  AND (fp.portfolio_weight_fraction < 0 OR fp.portfolio_weight_fraction > 1)

UNION ALL

SELECT
    'NH042_LOOKTHROUGH_WEIGHT_RANGE' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    CAST(le.weight_fraction AS VARCHAR) AS actual_value,
    '0 <= value <= 1' AS expected_value,
    'Normalized look-through weights are unit fractions.' AS details
FROM lookthrough_edge le
WHERE le.weight_fraction IS NOT NULL
  AND (le.weight_fraction < 0 OR le.weight_fraction > 1)

UNION ALL

SELECT
    'NH043_EFFECTIVE_EXPOSURE_RANGE' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    CAST(le.effective_exposure_fraction AS VARCHAR) AS actual_value,
    '0 <= value <= 1' AS expected_value,
    'Normalized effective exposure fractions are unit fractions.' AS details
FROM lookthrough_edge le
WHERE le.effective_exposure_fraction IS NOT NULL
  AND (le.effective_exposure_fraction < 0 OR le.effective_exposure_fraction > 1)

UNION ALL

SELECT
    'NH044_COVERAGE_RANGE' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    le.lookthrough_id AS record_id,
    le.parent_position_id AS related_record_id,
    CAST(le.coverage_fraction AS VARCHAR) AS actual_value,
    '0 <= value <= 1' AS expected_value,
    'Normalized coverage fractions are unit fractions.' AS details
FROM lookthrough_edge le
WHERE le.coverage_fraction IS NOT NULL
  AND (le.coverage_fraction < 0 OR le.coverage_fraction > 1)

UNION ALL

SELECT
    'NH045_POSITION_PERIOD_DATE_ORDER' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    COALESCE(CAST(fp.period_start_date AS VARCHAR), '') || ' / ' ||
        COALESCE(CAST(fp.period_end_date AS VARCHAR), '') AS actual_value,
    'period_start_date <= period_end_date' AS expected_value,
    'Position period dates are reversed.' AS details
FROM fund_position fp
WHERE fp.period_start_date IS NOT NULL
  AND fp.period_end_date IS NOT NULL
  AND fp.period_end_date < fp.period_start_date

UNION ALL

SELECT
    'NH046_POSITION_INVESTMENT_EXIT_ORDER' AS rule_id,
    'ERROR' AS severity,
    'fund_position' AS record_table,
    fp.position_id AS record_id,
    fp.instrument_id AS related_record_id,
    COALESCE(CAST(fp.initial_investment_date AS VARCHAR), '') || ' / ' ||
        COALESCE(CAST(fp.exit_date AS VARCHAR), '') AS actual_value,
    'initial_investment_date <= exit_date' AS expected_value,
    'Position exit date precedes its initial investment date.' AS details
FROM fund_position fp
WHERE fp.initial_investment_date IS NOT NULL
  AND fp.exit_date IS NOT NULL
  AND fp.exit_date < fp.initial_investment_date;


-- =============================================================================
-- 5. Recursive cycle detection
-- =============================================================================

-- Position graph:
-- parent_position_id -> child_position_id.
-- The path is kept as a DuckDB LIST and the walk stops immediately after
-- adding the first repeated node, so the recursive query terminates on cycles.
CREATE OR REPLACE VIEW vw_qa_lookthrough_position_cycles AS
WITH RECURSIVE
position_edges(parent_position_id, child_position_id) AS (
    SELECT DISTINCT parent_position_id, child_position_id
    FROM lookthrough_edge
    WHERE child_position_id IS NOT NULL
),
position_walk(
    start_position_id,
    current_position_id,
    path,
    has_cycle,
    hop_count
) AS (
    SELECT
        parent_position_id,
        child_position_id,
        [parent_position_id, child_position_id],
        parent_position_id = child_position_id,
        1
    FROM position_edges

    UNION ALL

    SELECT
        w.start_position_id,
        e.child_position_id,
        array_append(w.path, e.child_position_id),
        list_position(w.path, e.child_position_id) IS NOT NULL,
        w.hop_count + 1
    FROM position_walk w
    JOIN position_edges e
      ON e.parent_position_id = w.current_position_id
    WHERE NOT w.has_cycle
      AND w.hop_count < 256
)
SELECT DISTINCT
    'NH050_POSITION_LOOKTHROUGH_CYCLE' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    start_position_id AS record_id,
    current_position_id AS related_record_id,
    CAST(path AS VARCHAR) AS actual_value,
    'acyclic parent_position_id -> child_position_id graph' AS expected_value,
    'A look-through position path returns to a position already present in the same path.' AS details
FROM position_walk
WHERE has_cycle;


-- Fund graph:
-- immediate parent owner fund -> underlying fund.
-- This catches A -> B -> A even when the cycle uses different position IDs.
CREATE OR REPLACE VIEW vw_qa_lookthrough_fund_cycles AS
WITH RECURSIVE
fund_edges(parent_fund_id, child_fund_id) AS (
    SELECT DISTINCT
        pp.owner_fund_id,
        le.underlying_fund_id
    FROM lookthrough_edge le
    JOIN fund_position pp ON pp.position_id = le.parent_position_id
    WHERE le.relationship_type IN ('FUND_TO_UNDERLYING_HOLDING', 'FUND_TO_UNDERLYING_FUND')
      AND pp.owner_fund_id IS NOT NULL
      AND le.underlying_fund_id IS NOT NULL
),
fund_walk(
    start_fund_id,
    current_fund_id,
    path,
    has_cycle,
    hop_count
) AS (
    SELECT
        parent_fund_id,
        child_fund_id,
        [parent_fund_id, child_fund_id],
        parent_fund_id = child_fund_id,
        1
    FROM fund_edges

    UNION ALL

    SELECT
        w.start_fund_id,
        e.child_fund_id,
        array_append(w.path, e.child_fund_id),
        list_position(w.path, e.child_fund_id) IS NOT NULL,
        w.hop_count + 1
    FROM fund_walk w
    JOIN fund_edges e
      ON e.parent_fund_id = w.current_fund_id
    WHERE NOT w.has_cycle
      AND w.hop_count < 256
)
SELECT DISTINCT
    'NH051_FUND_LOOKTHROUGH_CYCLE' AS rule_id,
    'ERROR' AS severity,
    'lookthrough_edge' AS record_table,
    start_fund_id AS record_id,
    current_fund_id AS related_record_id,
    CAST(path AS VARCHAR) AS actual_value,
    'acyclic immediate-owner-fund -> underlying-fund graph' AS expected_value,
    'A fund look-through path returns to a fund already present in the same path.' AS details
FROM fund_walk
WHERE has_cycle;


-- Optional but useful: target parent hierarchy also cannot contain a multi-hop cycle.
CREATE OR REPLACE VIEW vw_qa_target_parent_cycles AS
WITH RECURSIVE
target_edges(parent_target_id, child_target_id) AS (
    SELECT parent_target_id, target_id
    FROM investment_target
    WHERE parent_target_id IS NOT NULL
),
target_walk(
    start_target_id,
    current_target_id,
    path,
    has_cycle,
    hop_count
) AS (
    SELECT
        parent_target_id,
        child_target_id,
        [parent_target_id, child_target_id],
        parent_target_id = child_target_id,
        1
    FROM target_edges

    UNION ALL

    SELECT
        w.start_target_id,
        e.child_target_id,
        array_append(w.path, e.child_target_id),
        list_position(w.path, e.child_target_id) IS NOT NULL,
        w.hop_count + 1
    FROM target_walk w
    JOIN target_edges e
      ON e.parent_target_id = w.current_target_id
    WHERE NOT w.has_cycle
      AND w.hop_count < 256
)
SELECT DISTINCT
    'NH052_TARGET_PARENT_CYCLE' AS rule_id,
    'ERROR' AS severity,
    'investment_target' AS record_table,
    start_target_id AS record_id,
    current_target_id AS related_record_id,
    CAST(path AS VARCHAR) AS actual_value,
    'acyclic parent_target_id hierarchy' AS expected_value,
    'The investment_target parent hierarchy contains a multi-hop cycle.' AS details
FROM target_walk
WHERE has_cycle;


-- =============================================================================
-- 6. Polymorphic field-lineage target validation
-- =============================================================================

CREATE OR REPLACE VIEW vw_qa_holding_field_lineage AS

SELECT
    'NH060_LINEAGE_TARGET_MISSING' AS rule_id,
    'ERROR' AS severity,
    'holding_field_lineage' AS record_table,
    hfl.lineage_id AS record_id,
    hfl.record_id AS related_record_id,
    hfl.record_type || ' / ' || hfl.record_id AS actual_value,
    'existing investment_owner row' AS expected_value,
    'OWNER lineage points to no investment_owner record.' AS details
FROM holding_field_lineage hfl
LEFT JOIN investment_owner io ON io.owner_id = hfl.record_id
WHERE hfl.record_type = 'OWNER'
  AND io.owner_id IS NULL

UNION ALL

SELECT
    'NH060_LINEAGE_TARGET_MISSING' AS rule_id,
    'ERROR' AS severity,
    'holding_field_lineage' AS record_table,
    hfl.lineage_id AS record_id,
    hfl.record_id AS related_record_id,
    hfl.record_type || ' / ' || hfl.record_id AS actual_value,
    'existing investment_target row' AS expected_value,
    'TARGET lineage points to no investment_target record.' AS details
FROM holding_field_lineage hfl
LEFT JOIN investment_target it ON it.target_id = hfl.record_id
WHERE hfl.record_type = 'TARGET'
  AND it.target_id IS NULL

UNION ALL

SELECT
    'NH060_LINEAGE_TARGET_MISSING',
    'ERROR',
    'holding_field_lineage',
    hfl.lineage_id,
    hfl.record_id,
    hfl.record_type || ' / ' || hfl.record_id,
    'existing investment_instrument row',
    'INSTRUMENT lineage points to no investment_instrument record.'
FROM holding_field_lineage hfl
LEFT JOIN investment_instrument ii ON ii.instrument_id = hfl.record_id
WHERE hfl.record_type = 'INSTRUMENT'
  AND ii.instrument_id IS NULL

UNION ALL

SELECT
    'NH060_LINEAGE_TARGET_MISSING',
    'ERROR',
    'holding_field_lineage',
    hfl.lineage_id,
    hfl.record_id,
    hfl.record_type || ' / ' || hfl.record_id,
    'existing fund_position row',
    'POSITION lineage points to no fund_position record.'
FROM holding_field_lineage hfl
LEFT JOIN fund_position fp ON fp.position_id = hfl.record_id
WHERE hfl.record_type = 'POSITION'
  AND fp.position_id IS NULL

UNION ALL

SELECT
    'NH060_LINEAGE_TARGET_MISSING',
    'ERROR',
    'holding_field_lineage',
    hfl.lineage_id,
    hfl.record_id,
    hfl.record_type || ' / ' || hfl.record_id,
    'existing lookthrough_edge row',
    'LOOKTHROUGH lineage points to no lookthrough_edge record.'
FROM holding_field_lineage hfl
LEFT JOIN lookthrough_edge le ON le.lookthrough_id = hfl.record_id
WHERE hfl.record_type = 'LOOKTHROUGH'
  AND le.lookthrough_id IS NULL

UNION ALL

SELECT
    'NH061_EXTRACTED_LINEAGE_SOURCE_REQUIRED' AS rule_id,
    'ERROR' AS severity,
    'holding_field_lineage' AS record_table,
    hfl.lineage_id AS record_id,
    hfl.record_id AS related_record_id,
    COALESCE(hfl.source_document_id, '') || ' / ' ||
        COALESCE(hfl.source_observation_id, '') AS actual_value,
    'nonblank source_document_id and source_observation_id' AS expected_value,
    'EXTRACTED field lineage must identify the exact source document and observation.' AS details
FROM holding_field_lineage hfl
WHERE hfl.provenance_type = 'EXTRACTED'
  AND (
      NULLIF(TRIM(hfl.source_document_id), '') IS NULL
      OR NULLIF(TRIM(hfl.source_observation_id), '') IS NULL
  );


-- =============================================================================
-- 7. Consolidated QA views
-- =============================================================================

CREATE OR REPLACE VIEW vw_normalized_holdings_qa AS
SELECT * FROM vw_qa_fund_interest_target
UNION ALL
SELECT * FROM vw_qa_owner_fund
UNION ALL
SELECT * FROM vw_qa_lookthrough_relationship
UNION ALL
SELECT * FROM vw_qa_normalized_ranges
UNION ALL
SELECT * FROM vw_qa_lookthrough_position_cycles
UNION ALL
SELECT * FROM vw_qa_lookthrough_fund_cycles
UNION ALL
SELECT * FROM vw_qa_target_parent_cycles
UNION ALL
SELECT * FROM vw_qa_holding_field_lineage;


CREATE OR REPLACE VIEW vw_normalized_holdings_qa_summary AS
SELECT
    severity,
    rule_id,
    COUNT(*) AS finding_count
FROM vw_normalized_holdings_qa
GROUP BY severity, rule_id
ORDER BY
    CASE severity WHEN 'ERROR' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END,
    rule_id;


-- =============================================================================
-- 8. Run queries
-- =============================================================================

-- Detailed violations. A clean result is zero rows.
SELECT *
FROM vw_normalized_holdings_qa
ORDER BY
    CASE severity WHEN 'ERROR' THEN 1 WHEN 'WARN' THEN 2 ELSE 3 END,
    rule_id,
    record_table,
    record_id;

-- Compact scorecard.
SELECT *
FROM vw_normalized_holdings_qa_summary;

-- Publication gate count. Publication requires error_count = 0.
SELECT
    COUNT(*) FILTER (WHERE severity = 'ERROR') AS error_count,
    COUNT(*) FILTER (WHERE severity = 'WARN') AS warning_count,
    COUNT(*) AS total_findings
FROM vw_normalized_holdings_qa;
