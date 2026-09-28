# Waymo controlled Germany ingestion preparation

## Result and boundaries

Implementation is ready for gated candidate review. Waymo is **not activated** and
has no candidate, profile, ingestion run, Bronze or Silver records. Existing
production Career Intelligence results and operator state match the published
leadership-review-final-2026-09-23 generation. No scoring or career profiles changed.

Greenhouse requests `jobs?content=true`. Original provider HTML remains in
`raw_data.job.content`; untruncated, entity-decoded plain text is projected into
`raw_data.job.description`. Existing Silver normalization preserves identity and
location; the Career Intelligence adapter reads the description from joined Bronze.
The v4 assessor and missing-description safeguards are unchanged.

Only an explicit `search_location=Germany` or `Deutschland` enables the new local
country filter. Server-side location capability remains false. Explicit Germany
metadata is retained; explicit foreign-country metadata is excluded. Missing,
city-only, remote-Europe and mixed-country locations are excluded conservatively.
Original location metadata is untouched. Each decision includes its reason and job
ID in `last_location_filter_report` and connector INFO logs; retained records also
carry their location-filter evidence. Excluded jobs are not persisted as Bronze.
Existing non-country profiles, including MOIA's Hannover profile, retain their
existing geographic behavior. The connector's metadata never implies Berlin,
remote or hybrid compatibility.

## Explicit activation configuration

`config/waymo_controlled_profile.json` defines the source, Germany scope, profile
name `waymo_controlled_germany_mobility`, explicit mobility/program/regulatory/fleet/
strategy terms, page size 25, and recurring ingestion disabled. Local keyword
matching still runs after geographic filtering. The four example IDs test geography;
role-theme filtering can reduce that set further. No keyword is a candidacy claim.

The activation CLI accepts `--profile-config`; both fresh readiness and eventual
profile creation use that scope. Waymo without an explicit configuration fails
before database access. Existing MOIA/default callers are unchanged. Existing
validation, final approval, exact readiness and A1 policy gates remain mandatory.
The activation transaction creates all configured terms and never enables recurring
acquisition. A later change of scope requires a new review; do not edit approved
configuration between review and activation.

## Current live check

Read-only public API check: HTTP 200, 352 jobs, 352 populated descriptions.
Country decisions: 4 Germany, 301 explicitly outside Germany, 47 ambiguous.
All four Germany jobs remain Munich-located:

- 8063637: Program Manager, Germany Regulatory
- 8108104: Strategy & BizOps Lead, Germany
- 8109449: Emergency Services Liaison, Germany
- 7922569: Lead Diagnostic Technician

Availability is point-in-time, not a suitability or Berlin-compatibility finding.
No provider responses were ingested or production opportunities reassessed.

## Validation

Full Python suite: **3,466 passed, four known baseline failures**:
three `test_daily_pipeline_failure_domains.py` Bash/mapfile failures, and
`test_doc001l_documentation_information_architecture.py` for the existing
`docs/.DS_Store`. Connector, activation, MOIA, ingestion/Bronze, Silver and Career
Intelligence tests passed. New tests cover all four IDs, missing/mixed/ambiguous
locations, full text over 12,000 characters reaching v4, preserved raw HTML and
location, unchanged default geography, mandatory gates, profile validation, all
search terms and recurring-disabled activation. Ruff and whitespace checks passed.

## Future commands — not executed

Run from the repository root with the normal database environment configured.
Candidate creation records no approval, activates no profile and ingests no jobs:

```bash
.venv/bin/python -B -m scripts.record_employer_origin_gate_review create-candidate \
  --company-key waymo --company-name Waymo \
  --candidate-url https://careers.withwaymo.com/jobs/search \
  --source-name-candidate greenhouse:waymo --source-family-candidate greenhouse \
  --source-target-candidate waymo \
  --source-type-candidate employer_origin_ats_backed_career_site \
  --status candidate --reviewed-by lingjia
```

Inspect validation before recording its result:

```bash
.venv/bin/python -B -m scripts.run_employer_origin_connector_validation_agent \
  --company-key waymo --dry-run --print-json
```

After reviewing the validation evidence, record validation, then inspect final
approval. Resolve every reported prerequisite; do not manually mark gates passed:

```bash
.venv/bin/python -B -m scripts.run_employer_origin_connector_validation_agent \
  --company-key waymo --reviewed-by lingjia --print-json
.venv/bin/python -B -m scripts.run_employer_origin_final_approval_gate_agent \
  --company-key waymo --dry-run --print-json
```

Only after separate approval, record the final gate using existing A1 authorization
(or the existing explicit approval-token workflow if required by that gate):

```bash
.venv/bin/python -B -m scripts.run_employer_origin_final_approval_gate_agent \
  --company-key waymo --approved-by lingjia --print-json
```

Review exact scoped activation readiness, then activate only if separately approved
and all gates pass. The readiness command fetches a fresh board but ingests no jobs:

```bash
.venv/bin/python -B -m scripts.run_validated_connector_controlled_activation \
  --company-key waymo --profile-config config/waymo_controlled_profile.json --print-json

# Separate future approval required; do not run during preparation:
.venv/bin/python -B -m scripts.run_validated_connector_controlled_activation \
  --company-key waymo --profile-config config/waymo_controlled_profile.json \
  --apply --print-json
```

Activation is not ingestion. First ingestion and recurring scheduling remain separate
approval steps. No full-fetch board-candidate validator command for Waymo is offered:
that older CLI has a fixed candidate allowlist and is not the activation gate.
