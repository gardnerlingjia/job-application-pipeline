# Career strategy calibration — 2026-09-15

Historical v1 report. Current rules and results: [recommendation semantics v2](recommendation-semantics-v2.md).

## Strategy and implementation

Primary search allocation is 55% autonomous-systems deployment/program leadership,
25% ADAS/AD and vehicle-software/mobility delivery, and 20% selective AI/data products.
These are search-effort allocations, not probability estimates or score multipliers.
Existing lane identifiers remain compatible; strategy/operations and mobility-ecosystem
identifiers remain available as secondary classifications with zero dedicated allocation.
Their classifier weights are reduced so generic strategy words do not dominate AI products.

Configuration owns target terms, gap rules, relevance anchors and recommendation thresholds.
A delivery role plus relevant domain establishes an 85-point lane/domain anchor instead of
requiring many synonyms. The weighted score remains a fit heuristic, not a hiring probability.
Traditional automotive keywords alone do not qualify a role: software/data/autonomy relevance
is required. Specialist engineering and unsupported enterprise-AI leadership are hard
recommendation exclusions, with capability/evidence scores capped at 25.

Capabilities matched only through transfer contexts are weighted as transferable evidence.
Unknown, empty and in-development evidence cannot establish matched capability. AI projects
support prototype literacy; the planned ROS 2/AMR project establishes no completed experience.
Professional robotics, production AI, cloud/DevOps, commercial and seniority gaps remain visible.

APPLY requires a score of at least 65, evidence of at least 55, a compatible known location,
and no overriding risk. Cold access is a visible risk, not an automatic rejection.
Developing robotics adjacency normally receives NETWORK FIRST when cold; customer deployment
can qualify for APPLY. Commercial or formal-PO risks require NETWORK FIRST or WATCH.
Technical Chief of Staff roles are capped at NETWORK FIRST; unrelated assistant roles are SKIP.
Existing wire codes APPLY_NOW and NETWORK_FIRST are retained; explanation labels use APPLY
and NETWORK FIRST. The old recommend_action helper remains available to existing callers;
the assessor uses the strategy-aware recommender.

## Role and market evidence contract

The assessor accepts optional keyword-only `role_evidence` and `market_evidence` mappings.
Batch JSON inputs preserve these mappings. New schema-v1 result records include `explanation`;
legacy records without it still load, and operator state does not rewrite them.
The explanation includes fit signals, capabilities, gaps, transition, location, access,
automotive exposure, missing market evidence and recommended action.

Role-specific access example (do not generalize to every role at an employer):

```json
{"role_evidence": {"network": {
  "relationship_level": "employee_referral",
  "status": "confirmed",
  "evidence_source": "Documented role-specific referral"
}}}
```

Supported access includes employee_referral, hiring_manager_access, internal_team_access,
internal_sponsor, warm_introduction and prior_working_relationship. Unconfirmed or unsourced
role access never supplies a bonus. Existing configured relationships are retained.

Each market field (`employer_segment`, `traditional_automotive_exposure`,
`autonomy_or_robotics_relevance`, `hiring_intent_strength`, `funding_or_budget_signal`)
contains `value`, `status` (confirmed/inferred/unknown), `evidence_source`, and
`evidence_freshness`. Missing sources or values become unknown. Unknown and inferred facts
never change scores or establish confirmed risks. Confirmed automotive exposure adds review;
confirmed weak hiring intent or frozen/unfunded budget caps an otherwise viable action at WATCH.
Freshness is retained as supplied, with no fabricated date or automatic freshness inference.

## Offline before/after calibration

Descriptions are representative fixtures, not verified live vacancies. Baselines were captured
from the clean current branch before edits. The requested historical dx.one 27.5/SKIP could not
be reproduced: the checked-out evaluator returned 48.3/WATCH for this description. The revision
recognizes vehicle/customer analytics and product-delivery transfer plus the supplied referral,
while retaining the missing multi-year formal PO evidence. Final-round history is contextual
validation, not a guarantee of capability or future hiring.

| Role | Before | After | Transition |
|---|---|---|---|
| Example Robotics — Robotics Technical Program Manager | 63.6 / EXPLORE | 82.5 / NETWORK_FIRST | adjacent |
| Example AMR — AMR Customer Deployment Lead | 58.1 / WATCH | 81.5 / APPLY_NOW | adjacent |
| Example Robotics — Robotics Perception Engineer | 58.7 / WATCH | 24.4 / SKIP | unrealistic |
| Example Robotics — Senior Robotics Architect | 56.1 / WATCH | 24.4 / SKIP | unrealistic |
| HERE — Solution Lead Professional Services ADAS/AD EMEA | 52.6 / WATCH | 80.5 / NETWORK_FIRST | direct |
| CARIAD — Internal A.I. Reporting Specialist | 51.3 / WATCH | 84.3 / APPLY_NOW | bridge |
| Example Retail — Head of Enterprise AI Transformation | 52.8 / WATCH | 30.0 / SKIP | unrealistic |
| Example Retail — Founder’s Associate | 10.0 / SKIP | 10.0 / SKIP | unrealistic |
| Example Robotics — Chief of Staff Autonomous Systems | 52.6 / WATCH | 79.5 / NETWORK_FIRST | adjacent |
| Example Mobility — ADAS Program Lead | 46.1 / SKIP | 74.0 / SKIP | direct |
| Example Mobility — ADAS Leadership | 45.3 / SKIP | 45.9 / SKIP | unknown |
| dx.one — Product Owner - Vehicle & Customer Analytics | 48.3 / WATCH | 73.8 / NETWORK_FIRST | bridge |
| FREENOW — Senior Autonomous Vehicle Partnership Manager | 64.1 / WATCH | 82.2 / NETWORK_FIRST | adjacent |

## Scope and remaining evidence

No providers, connectors, database records, rankings, applications or operator states were
changed. No migration is required. Search terms were revised without changing source statuses.
Role-specific dx.one referral and CARIAD internal-team access are calibration inputs from the
user; they are not employer-wide network facts. Existing saved results require an explicitly
requested reassessment before their displayed values change.

Unknown location, actual attendance obligations, hiring-manager intent, budget, evidence dates,
production ownership and commercial outcomes require verification. Text matching is deterministic
and heuristic: complex negation, multilingual descriptions and unnamed out-of-region attendance
can require human review. Review the explanation before applying. No market evidence was fetched.

## Validation

- `.venv/bin/python -m pytest -q tests/career_intelligence`: 184 passed.
- Focused suite plus documentation-consolidation checks: 188 passed.
- Complete suite: 3254 passed, 3 failed. All three daily-pipeline failure-domain tests
  reproduce on pristine HEAD files in a temporary directory with the local Bash environment;
  the existing script uses `mapfile`, which macOS system Bash does not provide.
- `.venv/bin/ruff check .`: 38 findings, all in untouched files. Changed Python files pass.
- Career configuration validation and `git diff --check`: passed.
- No commit, push, PR, runtime reassessment or provider activation performed.

## Files changed

- `config/capability_profile.yaml`
- `config/career_market_discovery.yaml`
- `config/career_profile.yaml`
- `config/constraints.yaml`
- `config/network_profile.yaml`
- `docs/career-intelligence/README.md`
- `docs/career-intelligence/strategy-calibration-2026-09-15.md`
- `docs/current/architecture.md`
- `docs/current/operations.md`
- `docs/current/product.md`
- `src/career_intelligence/assessor.py`
- `src/career_intelligence/batch.py`
- `src/career_intelligence/capability_matcher.py`
- `src/career_intelligence/classifier.py`
- `src/career_intelligence/constraints.py`
- `src/career_intelligence/domain_matcher.py`
- `src/career_intelligence/location_matcher.py`
- `src/career_intelligence/network_matcher.py`
- `src/career_intelligence/recommender.py`
- `tests/career_intelligence/test_operator_state.py`
- `tests/career_intelligence/test_real_jobs.py`
- `tests/career_intelligence/test_strategy_calibration.py`
- `tests/fixtures/career_intelligence/strategy_calibration.json`
