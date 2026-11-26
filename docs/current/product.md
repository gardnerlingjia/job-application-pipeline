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

Deep Ocean is the visual language: sonar for sensing, depth for evidence,
pressure for gates, calm control surfaces for decisions and repair loops for
learning.

## Current product-rebaseline state

The high-level intent above is stable repository truth, but exact target-profile, geography, Top-5, ranking, freshness, queue and review semantics still require operator approval under PRD-001.

Until the relevant decisions are approved, implementation must not silently choose product defaults. Safety work, defect repair, read-only evidence and operational stabilization may continue.


Career Intelligence V3.4 operations: [handover](career-intelligence-v34-operations.md).
