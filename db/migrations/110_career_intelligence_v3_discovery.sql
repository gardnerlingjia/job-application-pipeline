-- Career Intelligence V3 discovery/monitoring state. This model is observational:
-- it does not write Silver jobs, assessments, recommendations or operator state.
CREATE TABLE IF NOT EXISTS career_discovery_sources (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    employer_name TEXT,
    provider TEXT NOT NULL,
    board_id TEXT,
    geographic_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    configured BOOLEAN NOT NULL DEFAULT TRUE,
    authorized BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    access_status TEXT NOT NULL DEFAULT 'unverified',
    last_retrieval_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    health_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS career_discovery_runs (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT REFERENCES career_discovery_sources(id) ON DELETE SET NULL,
    source_key TEXT NOT NULL,
    query_text TEXT,
    geographic_scope TEXT,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','partial','failed')),
    queries_attempted INTEGER NOT NULL DEFAULT 0,
    pages_requested INTEGER NOT NULL DEFAULT 0,
    pages_retrieved INTEGER NOT NULL DEFAULT 0,
    raw_results INTEGER NOT NULL DEFAULT 0,
    unique_vacancies INTEGER NOT NULL DEFAULT 0,
    cross_source_duplicates INTEGER NOT NULL DEFAULT 0,
    parse_failures INTEGER NOT NULL DEFAULT 0,
    retrieval_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS career_discovery_vacancies (
    id BIGSERIAL PRIMARY KEY,
    canonical_key TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    location_text TEXT NOT NULL DEFAULT '',
    canonical_url TEXT,
    content_sha256 TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    publication_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active','possibly_removed','removed')),
    removal_confirmed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS career_discovery_observations (
    id BIGSERIAL PRIMARY KEY,
    vacancy_id BIGINT NOT NULL REFERENCES career_discovery_vacancies(id) ON DELETE CASCADE,
    source_id BIGINT REFERENCES career_discovery_sources(id) ON DELETE SET NULL,
    run_id BIGINT REFERENCES career_discovery_runs(id) ON DELETE SET NULL,
    source_key TEXT NOT NULL,
    source_job_id TEXT,
    source_url TEXT,
    query_text TEXT,
    geographic_scope TEXT,
    source_published_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    content_sha256 TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_key, source_job_id, observed_at)
);

CREATE TABLE IF NOT EXISTS career_discovery_vacancy_aliases (
    alias_key TEXT PRIMARY KEY,
    vacancy_id BIGINT NOT NULL REFERENCES career_discovery_vacancies(id) ON DELETE CASCADE,
    alias_type TEXT NOT NULL CHECK (alias_type IN ('canonical_url','company_title_location')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS career_discovery_events (
    id BIGSERIAL PRIMARY KEY,
    vacancy_id BIGINT NOT NULL REFERENCES career_discovery_vacancies(id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES career_discovery_runs(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('new','changed','removed','reappeared')),
    previous_content_sha256 TEXT,
    current_content_sha256 TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_career_discovery_runs_source_time
ON career_discovery_runs(source_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_career_discovery_observations_vacancy_time
ON career_discovery_observations(vacancy_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_career_discovery_observations_source_id
ON career_discovery_observations(source_key, source_job_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_career_discovery_events_type_time
ON career_discovery_events(event_type, occurred_at DESC);

COMMENT ON TABLE career_discovery_vacancies IS
'Canonical discovery-only vacancy observations; not assessment or Product V1 truth.';
