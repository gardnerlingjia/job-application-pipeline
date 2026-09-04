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

Deep Ocean is the visual language: sonar for sensing, depth for evidence,
pressure for gates, calm control surfaces for decisions and repair loops for
learning.

## Current product-rebaseline state

The high-level intent above is stable repository truth, but exact target-profile, geography, Top-5, ranking, freshness, queue and review semantics still require operator approval under PRD-001.

Until the relevant decisions are approved, implementation must not silently choose product defaults. Safety work, defect repair, read-only evidence and operational stabilization may continue.
