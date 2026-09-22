# Recommendation semantics v2 — 2026-09-15

Historical v2 semantics. Current calibration: [v3 report](strategy-calibration-2026-09-15.md).
Superseded the [v1 calibration report](strategy-calibration-v1-2026-09-15.md).

## Decision contract

NETWORK FIRST is reserved for sufficient strategic fit **and** current candidate strength
(at least 60), cold access, known compatible location, and no blocking capability gap or
unresolved commissioning scope. Documented referral, direct hiring-manager access, internal
team access, sponsor support and warm relationships prevent NETWORK FIRST.
Core commercial, engineering and technical ownership gaps receive WATCH or SKIP, regardless
of network access. WATCH means requirements/evidence need resolution; it does not suggest
that networking can compensate for a core gap. Specialist excluded roles remain SKIP.

The 55/25/20 search priorities remain. Strategic attractiveness is now a separate explanation
field. The former 85-point lane/domain floors are removed. `candidate_strength.score` is the
minimum of matched capability fit, matched evidence strength and any role-specific gap cap.
Core gaps cap strength at 40; specialist engineering/unsupported AI leadership caps it at 25.
Neither career priority, domain keyword scores, location nor network scores enter this measure.
Access alone cannot raise candidate strength, including in selective AI bridges.

`opportunity_score` remains the legacy weighted ranking heuristic for compatibility; it is
explicitly **not** candidate strength or an application-eligibility threshold. Actions use the
independent strength threshold (65 for APPLY, 60 for NETWORK FIRST), strategy and requirement
gates. Individual matched-capability evidence scores describe transferable evidence; the
role-specific strength cap explains why that evidence may still be insufficient for the role.

Strong cold robotics/autonomy roles can receive NETWORK FIRST. Warm/referral roles receive
APPLY only when strength and all other gates qualify; otherwise WATCH or SKIP. Technical
Chief of Staff remains capped at WATCH for warm access or NETWORK FIRST for eligible cold
access. Pre-sales support alone is a review flag, not confirmed core commercial ownership.

Silver freshness updates no longer rerun the old composite-score recommender. They preserve
semantic gates and may downgrade APPLY/NETWORK FIRST to WATCH when an age penalty applies;
they never manufacture NETWORK FIRST. Missing source descriptions clear supported strength
and cannot retain optimistic actions. Legacy `recommend_action` lacks the independent evidence
and categorical access required for approval, so it returns only WATCH/SKIP.

## Explicit role requirements

`role_evidence.requirements` accepts `commercial_core`, `engineering_commissioning_core`,
and `technical_core`. Each is a mapping with a boolean `value`, `status: confirmed`, and a
nonempty `evidence_source`. Unsourced, inferred, unknown and non-boolean values remain unknown.
Confirmed core requirements trigger a gap; explicit requirement text also triggers a gap and
wins over contradictory negative scope evidence. Requirement phrase rules are configurable.

For AMR/customer robotics deployment, APPLY requires `engineering_commissioning_core: false`
with confirmed, sourced evidence. Absence of engineering terms in a job description is not
confirmation. The positive AMR calibration is synthetic and does not establish any live role's
scope. The unconfirmed original fixture is WATCH, with any access level.

## Preserved evidence and historical comparisons

- `strategy_calibration.v0.json`: exact original descriptions and original recorded metrics,
  before role evidence was supplied. Partial results only; no missing historic fields fabricated.
- `strategy_calibration.v1.json`: byte-for-byte copy of the pre-refinement fixture file.
- `strategy_calibration.v1.results.json`: complete pre-refinement assessments captured before editing.
- `strategy_calibration.v2.json`: same original company/title/description bytes, revised expected
  actions, real user-reported FREENOW commercial-heavy feedback, and two separately named
  synthetic AMR scope variants. dx.one's original explicit referral is preserved.
- `strategy_calibration.v2.results.json`: complete current assessments, checked by regression tests.
- Version manifests preserve input/result SHA-256 hashes and evaluator/config fingerprints.
  The original unversioned file is frozen as a v1 compatibility copy, not reused as a v2 fixture.

The historical dx.one 27.5/SKIP remains unverified. Original checked-out code measured 48.3/WATCH;
v1 measured 73.8/NETWORK FIRST with the referral. v2 corrects the recommendation semantics.
The v1 and v2 composite scores are different heuristics after removal of relevance floors;
use the separate candidate strength and requirement reasons to interpret the new decision.

## Changed outcomes

| Role | v1 score / action | v2 composite score | Current candidate strength | v2 action |
|---|---|---:|---:|---|
| robotics_tpm | 82.5 / NETWORK_FIRST | 62.9 | 90.0 | NETWORK_FIRST |
| amr | 81.5 / APPLY_NOW | 61.2 | 83.3 | WATCH |
| perception | 24.4 / SKIP | 51.4 | 25 | SKIP |
| architect | 24.4 / SKIP | 51.4 | 25 | SKIP |
| here | 80.5 / NETWORK_FIRST | 64.7 | 88.0 | APPLY_NOW |
| cariad | 84.3 / APPLY_NOW | 75.5 | 40 | WATCH |
| enterprise_ai | 30.0 / SKIP | 50.2 | 25 | SKIP |
| founder | 10.0 / SKIP | 10.0 | 0 | SKIP |
| cos | 79.5 / NETWORK_FIRST | 52.4 | 81.3 | NETWORK_FIRST |
| munich | 74.0 / SKIP | 42.5 | 100.0 | SKIP |
| china | 45.9 / SKIP | 45.9 | 95.0 | SKIP |
| dx | 73.8 / NETWORK_FIRST | 57.3 | 38.7 | WATCH |
| freenow | 82.2 / NETWORK_FIRST | 56.5 | 40 | WATCH |
| amr_confirmed_delivery | New synthetic scope variant | 61.2 | 83.3 | APPLY_NOW |
| amr_core_commissioning | New synthetic scope variant | 61.2 | 40 | WATCH |

FREENOW retains autonomous-mobility attractiveness but scores 40 on role-specific strength
because the real commercial-heavy feedback confirms unsupported core commercial ownership.
dx.one has documented referral access and 38.7 strength: WATCH for the formal Product Owner
requirement, never NETWORK FIRST. CARIAD is WATCH because this exact fixture explicitly
requires platform/DevOps depth. HERE's fixture says pre-sales **support**, without core revenue
ownership, so it qualifies for APPLY while retaining the commercial-evidence review flag.
If core pre-sales ownership is confirmed, the requirements gate caps it at WATCH.

## Scope and follow-up

No applications, runtime rankings, provider activation, saved operator state, commits or pushes.
Existing saved assessments retain their previous version until explicitly reassessed. To
resolve WATCH, verify actual required ownership and provide evidence against the identified gap.
FREENOW commercial-heavy feedback is user-reported evidence; fixture descriptions are still
representative, not newly fetched live postings. Positive AMR scope confirmation remains
synthetic until an actual job description or hiring team provides it.

## Validation

- Focused Career Intelligence suite: **262 passed**.
- Complete suite: **3332 passed, 3 failed**. The same three daily-pipeline shell tests
  fail under local macOS Bash; they were previously reproduced using pristine HEAD files.
  No new full-suite failures remain.
- Repository-wide Ruff: **38 findings**, all in untouched files. Changed/new Python files pass.
- Career configuration validation and `git diff --check`: passed.
- Regression coverage includes access/strength/core-gap combinations, actual referral
  propagation through batch output, cold versus direct hiring-manager AI bridge strength,
  freshness behavior, AMR unknown/confirmed/core scope and contradictory scope evidence,
  immutable v1 inputs/results and exact v2 assessment snapshots.

Primary implementation changes in this refinement: `assessor.py`, `recommender.py`,
`scoring.py`, `classifier.py`, `ingest_silver.py`, career/network profiles, versioned fixtures,
recommendation regression tests and the Career Intelligence/current documentation.
