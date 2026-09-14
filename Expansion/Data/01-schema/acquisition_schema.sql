-- Expansion Data pre-extraction acquisition schema
-- DuckDB-compatible control tables.
-- This schema stores acquisition and admission metadata only.
-- It does not create extracted holding, valuation, or transaction facts.

CREATE TABLE IF NOT EXISTS expansion_source_candidate (
    candidate_id VARCHAR PRIMARY KEY,
    source_system VARCHAR NOT NULL,
    source_record_id VARCHAR,
    source_url VARCHAR NOT NULL,
    discovered_at TIMESTAMP NOT NULL,
    proposed_doc_type VARCHAR,
    proposed_report_subtype VARCHAR,
    candidate_priority VARCHAR NOT NULL CHECK (candidate_priority IN ('P0','P1','P2')),
    discovery_score DOUBLE,
    discovery_reason VARCHAR,
    fetch_status VARCHAR NOT NULL DEFAULT 'PENDING'
        CHECK (fetch_status IN ('PENDING','APPROVED','FETCHED','HOLD','REJECTED'))
);

CREATE TABLE IF NOT EXISTS expansion_source_document (
    expansion_document_id VARCHAR PRIMARY KEY,
    candidate_id VARCHAR NOT NULL,
    file_id VARCHAR,
    native_filename VARCHAR NOT NULL,
    native_file_ext VARCHAR NOT NULL,
    native_source_url VARCHAR NOT NULL,
    native_sha256 VARCHAR NOT NULL,
    native_size_bytes BIGINT NOT NULL,
    canonical_pdf_filename VARCHAR,
    canonical_pdf_sha256 VARCHAR,
    derived_from_native_sha256 VARCHAR,
    renderer_id VARCHAR,
    retrieved_at TIMESTAMP NOT NULL,
    source_system VARCHAR NOT NULL,
    document_family VARCHAR NOT NULL,
    document_subtype VARCHAR NOT NULL,
    deal_context VARCHAR NOT NULL
        CHECK (deal_context IN (
          'NONE','LP_LED','GP_LED','CONTINUATION','CO_INVEST_SECONDARY',
          'PRIVATE_CREDIT_SECONDARY','FUND_FINANCING','PORTCO_TRANSACTION','UNKNOWN'
        )),
    lookthrough_level VARCHAR NOT NULL
        CHECK (lookthrough_level IN (
          'NONE','FUND_INTEREST','UNDERLYING_FUND','PORTFOLIO_COMPANY',
          'SECURITY_OR_LOAN','MULTI_LEVEL','UNKNOWN'
        )),
    version_status VARCHAR NOT NULL
        CHECK (version_status IN (
          'ORIGINAL','AMENDMENT','RESTATEMENT','DRAFT','FINAL','EXECUTED','CLOSING','UNKNOWN'
        )),
    execution_status VARCHAR NOT NULL
        CHECK (execution_status IN (
          'NOT_APPLICABLE','DRAFT','FINAL_UNEXECUTED','EXECUTED','AMENDED','UNKNOWN'
        )),
    admission_status VARCHAR NOT NULL DEFAULT 'CANDIDATE'
        CHECK (admission_status IN ('CANDIDATE','FETCHED','HOLD','REJECTED','ADMITTED')),
    FOREIGN KEY(candidate_id) REFERENCES expansion_source_candidate(candidate_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_expansion_native_sha
ON expansion_source_document(native_sha256);

CREATE TABLE IF NOT EXISTS expansion_sec_filing (
    expansion_document_id VARCHAR PRIMARY KEY,
    sec_cik VARCHAR NOT NULL,
    sec_accession VARCHAR NOT NULL,
    regulatory_form VARCHAR NOT NULL,
    filing_date DATE,
    period_of_report DATE,
    primary_document VARCHAR,
    exhibit_type VARCHAR,
    exhibit_sequence VARCHAR,
    FOREIGN KEY(expansion_document_id)
      REFERENCES expansion_source_document(expansion_document_id)
);

CREATE TABLE IF NOT EXISTS expansion_access_rights (
    expansion_document_id VARCHAR PRIMARY KEY,
    access_basis VARCHAR NOT NULL
        CHECK (access_basis IN (
          'PUBLIC','PUBLIC_RECORDS_RESPONSE','CUSTOMER_AUTHORIZED','INTERNAL_OWNED','LICENSED'
        )),
    confidentiality_class VARCHAR NOT NULL
        CHECK (confidentiality_class IN (
          'PUBLIC','RESTRICTED','CONFIDENTIAL','HIGH_SENSITIVITY'
        )),
    redistribution_rights VARCHAR NOT NULL
        CHECK (redistribution_rights IN (
          'PUBLIC_REDISTRIBUTABLE','INTERNAL_ONLY','LICENSE_RESTRICTED',
          'NO_REDISTRIBUTION','UNKNOWN'
        )),
    pii_class VARCHAR NOT NULL
        CHECK (pii_class IN ('NONE','LOW','SENSITIVE_TAX_OR_IDENTITY')),
    license_contract_id VARCHAR,
    rights_note VARCHAR,
    FOREIGN KEY(expansion_document_id)
      REFERENCES expansion_source_document(expansion_document_id)
);

CREATE TABLE IF NOT EXISTS expansion_document_lineage (
    parent_expansion_document_id VARCHAR NOT NULL,
    child_expansion_document_id VARCHAR NOT NULL,
    relation_type VARCHAR NOT NULL
        CHECK (relation_type IN (
          'AMENDS','RESTATES','SUPERSEDES','ATTACHED_TO','MEMBER_OF_PACKAGE',
          'DERIVED_FROM','DUPLICATE_OF'
        )),
    PRIMARY KEY(parent_expansion_document_id, child_expansion_document_id, relation_type),
    FOREIGN KEY(parent_expansion_document_id)
      REFERENCES expansion_source_document(expansion_document_id),
    FOREIGN KEY(child_expansion_document_id)
      REFERENCES expansion_source_document(expansion_document_id)
);

CREATE TABLE IF NOT EXISTS expansion_admission_check (
    expansion_document_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    check_status VARCHAR NOT NULL
        CHECK (check_status IN ('PASS','FAIL','HOLD','NOT_APPLICABLE')),
    observed_value VARCHAR,
    expected_value VARCHAR,
    detail VARCHAR,
    checked_at TIMESTAMP NOT NULL,
    PRIMARY KEY(expansion_document_id, check_name),
    FOREIGN KEY(expansion_document_id)
      REFERENCES expansion_source_document(expansion_document_id)
);

CREATE VIEW IF NOT EXISTS expansion_admission_ready AS
SELECT
    d.expansion_document_id,
    d.file_id,
    d.native_filename,
    d.document_family,
    d.document_subtype,
    d.admission_status,
    SUM(CASE WHEN c.check_status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
    SUM(CASE WHEN c.check_status = 'HOLD' THEN 1 ELSE 0 END) AS hold_count
FROM expansion_source_document d
LEFT JOIN expansion_admission_check c
  ON d.expansion_document_id = c.expansion_document_id
GROUP BY 1,2,3,4,5,6;