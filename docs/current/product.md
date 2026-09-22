# Product Current Truth

Status: current truth
Project character: **A — Intent Locked**

## Product authority

This file is the short current-product summary. It is not the complete product specification.

The authoritative product-behavior surface is `docs/reference/product-contract/`:

1. `docs/reference/product-contract/PRD.md`
2. `docs/reference/product-contract/PRODUCT_DECISION_REGISTER.md`
3. `docs/reference/product-contract/ACCEPTANCE_SCENARIOS.md`
4. `docs/reference/product-contract/TRACEABILITY.md`

Jens owns product intent. DON may propose product changes and independently choose technical implementation inside approved requirements, but it may not infer unresolved product preferences or promote them into current truth.

## Current product summary

This project is a personal Search Intelligence system for Hannover and
remote-in-Germany opportunities.

The product problem is false negatives: relevant employers or jobs can disappear
behind noisy aggregators, stale search terms, missing origin evidence or overly
safe stops. The system is built to find those weak spots, explain them and move
only when the next action is safe.

The goal is not maximum job volume. The goal is controlled market understanding:
which signals are known, which candidates are blocked, why they are blocked, and
what should happen next.

```text
Market signals -> candidates -> origin/detail evidence -> gates/stops/repair
-> connector readiness -> controlled sources -> Bronze/Silver/Gold -> Control Center
```

Career Opportunity Intelligence is now a local decision-support lens inside the
existing Product V1 Control Center. It reads Career Intelligence runtime outputs
and operator state, joins to Product V1 jobs through Silver provenance and
`silver_job_id`, and never replaces Product V1 ranking, Top-5, hard-filter, or
application authority.

Operator state for the career radar is human-owned local runtime state. Changing
NEW, REVIEWED, INTERESTED, or DISMISSED from the Control Center updates only
`.runtime/career_intelligence/operator_state.json`; it does not modify
`opportunities.json`, Silver, connectors, Product V1 scores, or applications.

Career-selected INTERESTED, APPLY_NOW, and NETWORK_FIRST jobs can open the
existing Application Workspace when they join to a Product V1 `silver_job_id`.
The workspace still owns the source-grounded `draft_for_review` flow and all
approval gates. The product still does not submit applications automatically.

Lingjia's V2.1 source strategy is configuration-backed in
`config/career_source_strategy.yaml`. It makes strategic employers, adjacent
employers, discovery sources and generic/demo sources distinct in the existing
Control Center. It prioritizes employer-origin evidence for career decisions but
does not register, activate, crawl, score, rank or apply to sources/jobs by
itself.

Career Intelligence V2.2 adds adaptive source discovery from existing observed
opportunities, Career Intelligence results and Silver provenance. It suggests
candidate employers for `PROMOTE_TO_TIER_A`, `PROMOTE_TO_TIER_B`, `WATCH`, or
`IGNORE` with explicit reasons, then stores operator decisions only in local
runtime state. These suggestions do not mutate the curated source strategy,
Product V1 ranking, source activation, connector registration, ingestion or
application submission.

Career Intelligence V2.3 makes MOIA the first live employer-origin proof flow
through `greenhouse:moia`. MOIA still follows the existing source lifecycle:
candidate state, connector validation, final approval, explicit active profile,
canonical ingestion, Silver transformation, Career Intelligence assessment, and
Control Center display. The flow does not change Product V1 ranking authority or
submit applications.
Career Intelligence freshness is a local decision lens: employer publication
dates are preferred, first seen is only a labelled fallback, and jobs older than
seven days receive a Career Intelligence score penalty without changing Product
V1 ranking or Top-5 semantics.

Career Intelligence V2.4 broadens the radar beyond pre-listed employers. The
operator runs `python -m src.career_intelligence.market_discovery run-daily` to
use existing supported discovery sensors, currently StepStone and Bundesagentur
fuer Arbeit, then the normal Bronze/Silver/Career Intelligence/Control Center
flow. Unknown employers may surface as opportunities and adaptive candidates,
but the product still does not auto-promote sources, auto-activate connectors,
replace Product V1 ranking, or submit applications.

Deep Ocean is the visual language: sonar for sensing, depth for evidence,
pressure for gates, calm control surfaces for decisions and repair loops for
learning.

## Current product-rebaseline state

The high-level intent above is stable repository truth, but exact target-profile, geography, Top-5, ranking, freshness, queue and review semantics still require operator approval under PRD-001.

Until the relevant decisions are approved, implementation must not silently choose product defaults. Safety work, defect repair, read-only evidence and operational stabilization may continue.


## Revised career strategy (2026-09-15)

Career Intelligence now prioritizes autonomous-systems program/deployment leadership (55%),
ADAS/vehicle-software delivery (25%), and selective AI/data-product bridges (20%).
Deterministic strategy gates distinguish delivery from specialist engineering, retain
unknown evidence, enforce location conflicts, and expose role-specific access and gap reasons.
Optional role/market evidence flows through batch inputs; explanations are additive to
schema-v1 results, with legacy records still accepted. Provider activation and Product V1
ranking authority are unchanged. Existing runtime assessments have not been regenerated.

See [strategy, evidence contract and offline calibration](../career-intelligence/strategy-calibration-2026-09-15.md) for
historical v1 thresholds, before/after examples and operator limitations.

Historical rules: [recommendation semantics v2](../career-intelligence/recommendation-semantics-v2.md) separates current candidate strength
from strategic attractiveness. NETWORK FIRST requires sufficient strength and cold access;
referrals/hiring-manager access prevent it, and core capability gaps yield WATCH/SKIP.
AMR APPLY requires confirmed non-core engineering/commissioning scope. Versioned fixtures
preserve exact historical inputs/results; Silver freshness cannot bypass these gates.

Current v3 calibration: [evidence-based candidacy, separate strategy/access and versioned fixtures](../career-intelligence/strategy-calibration-2026-09-15.md). Published totals exclude access, location and career priority; adjacency caps at 75. Full scope and validation are in that report.
