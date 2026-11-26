-- Persist source snapshot completeness so absence decisions can be audited.
ALTER TABLE career_discovery_runs
    ADD COLUMN IF NOT EXISTS snapshot_complete BOOLEAN NOT NULL DEFAULT FALSE;
