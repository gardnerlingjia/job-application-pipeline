# Autonomous mobility strategy alignment — 2026-09-22

## Verified root causes

1. The live discovery runner reads database terms. All ten profiles still exactly matched migration 109, including AI product/platform searches. Updating YAML alone had no effect on live queries.
2. The frequent-travel rule was configured but had no detector. Berlin text was treated as compatible even without travel evidence. Location had zero candidacy weight, but no separate Berlin ordering signal existed.
3. AI Engineer and Software Engineer titles were absent from the engineering exclusion list. Research leadership could qualify through adoption language without recognizing required model-development and programming experience.
4. Waymo was listed as a strategic watch target, but had no database profile, source candidate or ingestion run. A registered Greenhouse family is not evidence of activation.

## Database before/after search profiles

The following exact terms apply to both `lingjia_market_stepstone_` and `lingjia_market_ba_`. All ten profiles had page_size=15, offer_type=1, NULL legacy search term/location/radius, active=true and recurring=true. Those operational fields are preserved. The full observed state, diff and approval fingerprint are in [the sync plan](discovery-search-sync-2026-09-22.json).

| Profile suffix | Database before | After synchronization |
|---|---|---|
| autonomy_robotics | ADAS strategy; autonomous driving; autonomous mobility; intelligent mobility systems; robotics product manager; robotics program manager | AV deployment Germany; autonomous driving program manager; autonomous mobility deployment; autonomous mobility operations; autonomous vehicle technical program manager; robotaxi launch readiness |
| technical_program_product | delivery lead technology; principal product manager AI; product operations manager; program manager data platform; senior product manager platform; technical program manager | ADAS program manager; automated driving release manager; mobility solution delivery lead; vehicle integration program manager; vehicle software delivery lead |
| ai_data_transformation | AI product manager; AI transformation lead; analytics platform manager; data strategy lead; data transformation manager; machine learning platform lead | AI adoption program manager; AI transformation lead; automotive AI transformation; business process transformation lead |
| strategy_operations | business operations AI; chief of staff technology; executive operations mobility; strategic projects manager; strategy operations technology; transformation program lead | autonomous driving operations lead; autonomous mobility strategy operations; mobility launch readiness; mobility partner integration |
| mobility_platform_deployment | charging infrastructure product; deployment program manager; fleet operations technology; mobility ecosystem strategy; mobility platform manager; transport data platform | autonomes Fahren Projektleiter; autonomous fleet operations; fleet launch manager; mobility deployment program manager; mobility ecosystem integration; robotaxi operations Germany |

## Controlled synchronization

`discovery_profile_sync` defaults to a read-only JSON plan. It reports every active-term difference and fingerprints the complete observed operational fields, term activation states and desired intent. Applying requires that exact reviewed fingerprint. Changes between review and apply invalidate approval. The transaction locks profiles/terms, rechecks the plan and changes only term activation/insertion; no profiles, source candidates, activation flags or approval gates are written.

`--seed-only` additionally refuses every changed profile that is not identical to the frozen migration-109 seed. Customizations are never assumed to be managed. A customized profile needs a newly reported diff and explicit user approval before running apply without that restriction. Missing profiles, source mismatches and populated legacy search_term fields fail closed.

The discovery doctor and generic ingestion entry point reject stale search intent before fetching. Repeating a plan after successful synchronization produces zero differences. Historical term rows are retained as inactive.

### Applied state

The exact reviewed plan was applied with `--seed-only`. All ten profiles matched the original seed before application. Post-apply comparison: **zero differences, zero blockers; every operational profile field unchanged**. The database doctor passes. No manual synchronization remains for this initial migration. Future customized differences still require approval. No connectors/providers were activated, no live ingestion or automatic reassessment ran, and no commit/push was made.

An additional status bug was corrected: the doctor queried `status='finished'`, while the ingestion repository records `status='success'`. Actual database evidence: Stepstone 210 successful runs / 3,150 loaded records; Bundesagentur 210 successful runs / zero loaded records. The doctor now recognizes Stepstone as LIVE. Bundesagentur remains unverified for nonempty results; diagnosing its empty responses is a remaining coverage gap.

## Practical and engineering semantics

- Berlin location, Germany with occasional domestic travel, Germany with unspecified travel, frequent European travel and required relocation are represented separately. Travel evidence is included in the explanation. Missing or optional travel evidence stays unknown and gates APPLY/NETWORK FIRST to WATCH.
- Frequent travel and required relocation produce SKIP independently of candidacy. Explicit frequent/weekly travel, >=20% travel, or >=4 days/month count as more than occasional. Unspecified travel geography is not invented. German expressions and negation/optional scope have regression coverage.
- Berlin preference is a separate tie-breaker after candidacy, both in batch output and the Career Intelligence control-center projection. It does not contribute to the score. Existing operator-state/recommendation ordering is retained.
- AI/Software/ML/robotics engineer titles, including senior/staff/principal variants, are excluded. Mentions of engineering teams in a leadership description do not activate title-based specialist exclusions.
- The recorded Würth Teamlead Data Science description requires model development, strong Python/SQL, ML framework experience and several years in Data Science/ML. It also specifies four to five travel days/month. A single in-memory diagnostic gives SKIP/25 instead of the saved APPLY/75. The saved runtime assessment was not changed.

## Waymo and ecosystem verification

- Configured target: `greenhouse:waymo`, status watch. Actual DB: zero matching search profiles, zero source candidates, zero ingestion runs.
- A read-only GET to `https://boards-api.greenhouse.io/v1/boards/waymo/jobs` returned HTTP 200, JSON and 347 jobs on 2026-09-22. This verifies current board validity, not pipeline ingestion.
- Four board listings explicitly had Germany locations, all Munich: Emergency Services Liaison, Germany; Lead Diagnostic Technician; Program Manager, Germany Regulatory; Strategy & BizOps Lead, Germany. No Berlin location was listed. This is not a determination of remote or travel eligibility.
- Broad Stepstone and Bundesagentur queries now cover AV deployment, fleet launch, mobility operations, launch readiness, vehicle delivery and ecosystem/partner integration, without restricting employer names. Previously unknown employers remain discoverable.
- Remaining coverage gaps: direct Waymo acquisition remains inactive; Bundesagentur has no nonempty recorded result; explicit regulatory/homologation searches and exhaustive AV-employer coverage are not guaranteed. The 55/25/20 allocation is advisory, not an enforced scheduler quota. No new providers or connectors were activated.

## Historical comparison

v0–v3 fixtures and archived scores are untouched. v4 uses the exact same 19 descriptions, with newly versioned expectations/results and configuration hashes. Across those 19 examples, all candidacy scores remain unchanged. Five actions become WATCH solely because travel is unconfirmed:

| Scenario | v3 | v4 | Candidacy |
|---|---|---|
| Robotics TPM | NETWORK FIRST | WATCH | 75 |
| HERE | NETWORK FIRST | WATCH | 88.4 |
| Chief of Staff | NETWORK FIRST | WATCH | 75 |
| AMR, commissioning confirmed non-core | APPLY | WATCH | 75 |
| CARIAD, bridge scope | APPLY | WATCH | 75 |

FREENOW remains WATCH/40 with the commercial-core gap. dx.one remains WATCH/40 with referral access. AMR and CARIAD positive tests explicitly add synthetic no-travel confirmation; AMR still needs commissioning confirmed non-core. These positive tests do not alter the historical descriptions.

## Commands for controlled verification

Run from the repository root. Read-only configuration and database checks:

```sh
.venv/bin/python scripts/validate_career_config.py
.venv/bin/python -m src.career_intelligence.discovery_profile_sync > /tmp/discovery-sync-review.json
.venv/bin/python -m src.career_intelligence.market_discovery doctor
.venv/bin/python -m src.ingest_jobs --list-profiles
```

For a future approved term change, inspect the complete plan and supply its literal `approval_digest`. Do not automatically extract and approve a digest without reviewing the diff:

```sh
.venv/bin/python -m src.career_intelligence.discovery_profile_sync --approve REVIEWED_SHA256 --seed-only
```

Use `--seed-only` for untouched migration seeds. For customized or already-migrated profiles, obtain approval for the reported differences before omitting `--seed-only`. The tool never activates profiles.

Optional controlled live verification, not executed in this task: run one existing active profile. This fetches/persists raw records for that profile only (six terms, configured page size 15); it does not invoke Silver normalization or Career Intelligence reassessment:

```sh
.venv/bin/python -m src.ingest_jobs --profile lingjia_market_stepstone_autonomy_robotics
```

Inspect the resulting ingestion_runs rows and search_term values. Do not use market_discovery run-daily for this isolated check because that command also runs Silver and Career Intelligence.

## Validation

- Configuration validation passed, including discovery profiles.
- Focused Career Intelligence, calibration and relevant ingestion/discovery tests: **349 passed**.
- Full suite: **3,400 passed, 4 pre-existing failures**.
- Three daily-pipeline failures reproduce in an isolated pristine HEAD checkout. macOS system Bash lacks `mapfile` (`scripts/run_daily_pipeline.sh:122`), leading to an unset `CONTEXT_VALUES[0]` at line 125.
- The documentation architecture failure reports only the pre-existing untracked `docs/.DS_Store`. It was left untouched.
- Ruff passes on every changed Python file; a wider Career Intelligence lint scan also reported four existing findings in unchanged `daily.py` and `moia_live_source.py`.
- Historical v3 input/output/config hashes match their original manifest. New v4 tests verify exact snapshots and identical historical inputs. All 19 historical comparison candidacy scores are unchanged.
- `git diff --check` passes. The source/profile checks were read-only apart from the explicitly controlled search-term transaction.

## Exact changed files

- `config/career_discovery_profile_seed.v1.json`
- `config/career_market_discovery.yaml`
- `config/career_profile.yaml`
- `config/constraints.yaml`
- `docs/career-intelligence/autonomous-mobility-alignment-2026-09-22.md`
- `docs/career-intelligence/discovery-search-sync-2026-09-22.json`
- `scripts/validate_career_config.py`
- `src/career_intelligence/assessor.py`
- `src/career_intelligence/batch.py`
- `src/career_intelligence/classifier.py`
- `src/career_intelligence/constraints.py`
- `src/career_intelligence/control_center.py`
- `src/career_intelligence/discovery_profile_sync.py`
- `src/career_intelligence/location_matcher.py`
- `src/career_intelligence/market_discovery.py`
- `src/career_intelligence/practical_constraints.py`
- `src/career_intelligence/recommender.py`
- `src/ingest_jobs.py`
- `tests/career_intelligence/test_real_jobs.py`
- `tests/career_intelligence/test_recommendation_semantics.py`
- `tests/career_intelligence/test_strategy_alignment.py`
- `tests/career_intelligence/test_strategy_calibration.py`
- `tests/fixtures/career_intelligence/strategy_calibration.v4.config.json`
- `tests/fixtures/career_intelligence/strategy_calibration.v4.json`
- `tests/fixtures/career_intelligence/strategy_calibration.v4.manifest.json`
- `tests/fixtures/career_intelligence/strategy_calibration.v4.results.json`
