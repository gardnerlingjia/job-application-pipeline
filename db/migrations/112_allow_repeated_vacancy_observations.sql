-- Repeated source postings can occur across search queries in one run.
-- Keep each observation; the observation id is its identity, not timestamp uniqueness.
ALTER TABLE career_discovery_observations
    DROP CONSTRAINT IF EXISTS career_discovery_observations_source_key_source_job_id_obse_key;

CREATE INDEX IF NOT EXISTS idx_career_discovery_observations_source_job_time
ON career_discovery_observations(source_key, source_job_id, observed_at DESC);
