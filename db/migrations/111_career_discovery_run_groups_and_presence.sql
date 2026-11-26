ALTER TABLE career_discovery_runs
    ADD COLUMN IF NOT EXISTS run_group_id UUID;

CREATE INDEX IF NOT EXISTS idx_career_discovery_runs_group
ON career_discovery_runs(run_group_id, source_key, started_at);

CREATE TABLE IF NOT EXISTS career_discovery_source_vacancy_state (
    source_key TEXT NOT NULL,
    vacancy_id BIGINT NOT NULL REFERENCES career_discovery_vacancies(id) ON DELETE CASCADE,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consecutive_complete_absences INTEGER NOT NULL DEFAULT 0,
    removed_at TIMESTAMPTZ,
    PRIMARY KEY (source_key, vacancy_id)
);

CREATE INDEX IF NOT EXISTS idx_career_discovery_source_presence
ON career_discovery_source_vacancy_state(source_key, last_seen_at DESC);
