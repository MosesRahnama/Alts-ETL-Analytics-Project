-- Open with: duckdb data/warehouse/extracted.duckdb

-- Table and view inventory.
SELECT table_name, table_type
FROM information_schema.tables
WHERE table_schema = 'main'
ORDER BY table_type, table_name;

-- Observation counts by document and record family.
SELECT document_id, record_family, COUNT(*) AS observations
FROM fact_observation
GROUP BY document_id, record_family
ORDER BY document_id, observations DESC;

-- Entity resolution coverage.
SELECT
  subject_type,
  COUNT(*) AS observations,
  COUNT(subject_entity_id) AS resolved_observations,
  COUNT(DISTINCT subject_entity_id) AS resolved_entities
FROM fact_observation
GROUP BY subject_type
ORDER BY observations DESC;

-- Metric coverage.
SELECT record_family, metric_category, COUNT(*) AS observations
FROM fact_observation
GROUP BY record_family, metric_category
ORDER BY record_family, observations DESC;

-- Replace the value with an ID from trace-sample.csv.
SELECT *
FROM fact_observation
WHERE observation_id = 'OBSERVATION_ID';

-- Wide-row lineage back to printed cells.
SELECT b.pivot_table, b.pivot_row_id, b.observation_id, f.document_id,
       f.source_page, f.source_row_label, f.source_column_label,
       f.metric_category, f.value_raw, f.evidence_quote
FROM bridge_pivot_observation AS b
JOIN fact_observation AS f USING (observation_id)
ORDER BY b.pivot_table, b.pivot_row_id, f.observation_id;
