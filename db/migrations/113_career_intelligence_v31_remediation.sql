-- V3.1 additive remediation. Existing observations and event rows remain untouched.
ALTER TABLE career_discovery_vacancies
    ADD COLUMN IF NOT EXISTS vacancy_type TEXT NOT NULL DEFAULT 'actual_vacancy'
        CHECK (vacancy_type IN ('actual_vacancy','unsolicited_application','other_employer_board_entry')),
    ADD COLUMN IF NOT EXISTS locations JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE career_discovery_events
    ADD COLUMN IF NOT EXISTS run_group_id UUID;

CREATE TABLE IF NOT EXISTS career_discovery_source_identities (
    source_key TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    vacancy_id BIGINT NOT NULL REFERENCES career_discovery_vacancies(id),
    legacy_vacancy_id BIGINT REFERENCES career_discovery_vacancies(id),
    reconciliation_status TEXT NOT NULL DEFAULT 'current'
        CHECK (reconciliation_status IN ('current','split_from_legacy','needs_review')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_key, source_job_id)
);

CREATE TABLE IF NOT EXISTS career_operator_state_transitions (
    id BIGSERIAL PRIMARY KEY,
    vacancy_key TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    transitioned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_career_operator_transitions_key_time
ON career_operator_state_transitions(vacancy_key, transitioned_at DESC);

-- Backfill presence from historical raw observations as a baseline only. No
-- historical absence is counted toward removal confirmation.
INSERT INTO career_discovery_source_vacancy_state
    (source_key, vacancy_id, last_seen_at, consecutive_complete_absences, removed_at)
SELECT source_key, vacancy_id, MAX(observed_at), 0, NULL
FROM career_discovery_observations
GROUP BY source_key, vacancy_id
ON CONFLICT (source_key, vacancy_id) DO UPDATE SET
    last_seen_at = GREATEST(career_discovery_source_vacancy_state.last_seen_at, EXCLUDED.last_seen_at);

-- Reconcile each provider posting ID independently. Keep the former merged
-- canonical row as the legacy reference and duplicate metadata for split rows.
DO $$
DECLARE grp RECORD; item RECORD; target_id BIGINT; first_id BIGINT;
BEGIN
  FOR grp IN
    SELECT o.vacancy_id, o.source_key, COUNT(DISTINCT o.source_job_id) AS n
    FROM career_discovery_observations o
    WHERE NULLIF(o.source_job_id, '') IS NOT NULL
    GROUP BY o.vacancy_id, o.source_key
    HAVING COUNT(DISTINCT o.source_job_id) > 1
  LOOP
    first_id := NULL;
    FOR item IN
      SELECT DISTINCT o.source_job_id
      FROM career_discovery_observations o
      WHERE o.vacancy_id=grp.vacancy_id AND o.source_key=grp.source_key
      ORDER BY o.source_job_id
    LOOP
      IF first_id IS NULL THEN
        target_id := grp.vacancy_id;
        first_id := target_id;
      ELSE
        INSERT INTO career_discovery_vacancies
            (canonical_key,company_name,title,location_text,canonical_url,content_sha256,
             first_seen_at,last_seen_at,publication_at,source_updated_at,lifecycle_status,
             removal_confirmed_at,vacancy_type,locations)
        SELECT 'reconciled:' || md5(grp.source_key || ':' || item.source_job_id),
               company_name,title,location_text,canonical_url,content_sha256,
               first_seen_at,last_seen_at,publication_at,source_updated_at,lifecycle_status,
               removal_confirmed_at,vacancy_type,locations
        FROM career_discovery_vacancies WHERE id=grp.vacancy_id
        RETURNING id INTO target_id;
      END IF;
      INSERT INTO career_discovery_source_identities
          (source_key,source_job_id,vacancy_id,legacy_vacancy_id,reconciliation_status)
      VALUES (grp.source_key,item.source_job_id,target_id,grp.vacancy_id,
              CASE WHEN target_id=grp.vacancy_id THEN 'needs_review' ELSE 'split_from_legacy' END)
      ON CONFLICT (source_key,source_job_id) DO NOTHING;
      IF target_id <> grp.vacancy_id THEN
        INSERT INTO career_discovery_source_vacancy_state
            (source_key,vacancy_id,last_seen_at,consecutive_complete_absences,removed_at)
        SELECT grp.source_key,target_id,MAX(observed_at),0,NULL
        FROM career_discovery_observations
        WHERE source_key=grp.source_key AND source_job_id=item.source_job_id
        ON CONFLICT (source_key,vacancy_id) DO NOTHING;
      END IF;
    END LOOP;
  END LOOP;
  INSERT INTO career_discovery_source_identities(source_key,source_job_id,vacancy_id)
  SELECT DISTINCT ON (o.source_key,o.source_job_id)
         o.source_key,o.source_job_id,o.vacancy_id
  FROM career_discovery_observations o
  WHERE NULLIF(o.source_job_id,'') IS NOT NULL
  ORDER BY o.source_key,o.source_job_id,o.observed_at DESC
  ON CONFLICT (source_key,source_job_id) DO NOTHING;
END $$;

UPDATE career_discovery_vacancies v
SET vacancy_type='unsolicited_application'
WHERE v.title ILIKE 'Unsolicited Application%'
  AND EXISTS (SELECT 1 FROM career_discovery_observations o
              WHERE o.vacancy_id=v.id AND o.source_key ILIKE 'greenhouse:%moia%');

CREATE UNIQUE INDEX IF NOT EXISTS idx_career_discovery_event_group_unique
ON career_discovery_events(vacancy_id, run_group_id, event_type)
WHERE run_group_id IS NOT NULL;
