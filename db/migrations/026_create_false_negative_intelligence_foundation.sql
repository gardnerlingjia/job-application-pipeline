-- S5A False Negative Intelligence Foundation
-- Market evidence is observational data used to detect blind spots. It is not a Bronze job record, not a connector activation, and not a scheduler change.

CREATE TABLE IF NOT EXISTS market_evidence (
    id BIGSERIAL PRIMARY KEY,
    evidence_source TEXT NOT NULL,
    evidence_kind TEXT NOT NULL DEFAULT 'aggregator_sighting',
    source_name TEXT NOT NULL,
    normalized_company_key TEXT NOT NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence_url TEXT,
    search_profile_name TEXT,
    search_term TEXT,
    source_seen_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingestion_run_id BIGINT REFERENCES ingestion_runs(id),
    raw_job_external_id TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_market_evidence_company_seen
    ON market_evidence (normalized_company_key, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_market_evidence_source_seen
    ON market_evidence (source_name, observed_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_evidence_observation_unique
    ON market_evidence (
        lower(source_name),
        normalized_company_key,
        lower(title),
        coalesce(evidence_url, ''),
        ((coalesce(source_seen_at, observed_at) AT TIME ZONE 'UTC')::date)
    );

CREATE OR REPLACE VIEW candidate_market_evidence_summary AS
SELECT
    c.id AS candidate_id,
    c.company_key,
    c.company_name,
    c.source_name_candidate,
    c.source_family_candidate,
    c.status AS candidate_status,
    c.risk_level AS candidate_risk_level,
    count(me.id)::integer AS sighting_count,
    count(*) FILTER (WHERE me.observed_at >= now() - interval '14 days')::integer AS recent_sighting_count,
    max(me.observed_at) AS last_observed_at,
    array_remove(array_agg(DISTINCT me.source_name ORDER BY me.source_name), NULL) AS evidence_sources,
    array_remove(array_agg(DISTINCT me.title ORDER BY me.title), NULL) AS evidence_titles
FROM employer_origin_source_candidates c
LEFT JOIN market_evidence me
    ON me.normalized_company_key = c.company_key
    OR starts_with(me.normalized_company_key, c.company_key || '_')
    OR starts_with(c.company_key, me.normalized_company_key || '_')
GROUP BY
    c.id,
    c.company_key,
    c.company_name,
    c.source_name_candidate,
    c.source_family_candidate,
    c.status,
    c.risk_level;

CREATE TABLE IF NOT EXISTS false_negative_risk_snapshots (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT REFERENCES employer_origin_source_candidates(id),
    company_key TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    sighting_count INTEGER NOT NULL,
    recent_sighting_count INTEGER NOT NULL,
    last_observed_at TIMESTAMPTZ,
    suggested_search_terms TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by TEXT NOT NULL DEFAULT 'agent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_false_negative_risk_snapshots_candidate_created
    ON false_negative_risk_snapshots (candidate_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_false_negative_risk_snapshots_level_created
    ON false_negative_risk_snapshots (risk_level, created_at DESC);
