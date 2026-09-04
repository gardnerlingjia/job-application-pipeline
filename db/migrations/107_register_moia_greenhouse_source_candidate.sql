-- Career Intelligence V2.3 MOIA Greenhouse source candidate.
--
-- Purpose:
--   Register MOIA as a reviewed employer-origin source candidate using the
--   existing Greenhouse connector family:
--     source_name_candidate = 'greenhouse:moia'
--
-- Boundary:
-- - This migration creates candidate/gate-review state only.
-- - It does not pass validation or final approval gates.
-- - It does not create an active search profile.
-- - It does not run ingestion, write Bronze/Silver rows, mutate ranking,
--   schedule jobs or touch applications.
-- - Controlled activation remains an explicit operator action after existing
--   gate reviews pass.

INSERT INTO employer_origin_source_candidates (
    company_key,
    company_name,
    candidate_url,
    source_name_candidate,
    source_family_candidate,
    source_target_candidate,
    source_type_candidate,
    status,
    risk_level,
    notes
)
SELECT
    'moia',
    'MOIA',
    'https://boards-api.greenhouse.io/v1/boards/moia/jobs',
    'greenhouse:moia',
    'greenhouse',
    'moia',
    'employer_origin_ats_backed_career_site',
    'manual_review_required',
    'low',
    'Career Intelligence V2.3 candidate. Greenhouse board token maps to greenhouse:moia; activation requires connector validation and final approval gates.'
WHERE NOT EXISTS (
    SELECT 1
    FROM employer_origin_source_candidates
    WHERE company_key = 'moia'
      AND source_name_candidate = 'greenhouse:moia'
);
