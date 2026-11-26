# Documentation

Status: current documentation entry point
Scope: DOC-001M documentation architecture and artifact discipline

## Purpose

The documentation is intentionally small at the top level. It separates approved
product intent, what is currently true, how to work with the project, detailed
reference material, architecture decisions, active planning and historical build
traces.

The goal is not to keep every useful note visible forever. The goal is to make
the current system and desired product understandable without archaeology.

## Read this first

1. `reference/product-contract/README.md`
2. `current/product.md`
3. `current/architecture.md`
4. `current/pipeline.md`
5. `current/system-diagrams.md`
6. `current/engineering_principles.md`
7. `current/governance.md`
8. `current/operations.md`

## Product authority

`reference/product-contract/` defines the operator-owned product contract, open decisions, acceptance scenarios and traceability rules.

The Pipeline is a Class A — Intent Locked project. Product semantics may be proposed by DON or engineering work, but they become active only through explicit operator approval.

Implementation truth does not silently redefine desired product behavior.

## Current truth notes

`current/engineering_principles.md` defines the small set of engineering values
that guide architecture, governance, compliance readiness, sustainability and
operational decisions. It is intentionally short and must not become a policy
collection.

## Structure

| Area | Purpose | Rule |
|---|---|---|
| `career-intelligence/` | Usage documentation for the isolated Career Intelligence subsystem. | Keep aligned with the shipped assessment interfaces. |
| `current/` | Short, maintained truth about the current product and architecture. | Keep small; promote only stable facts. |
| `guides/` | How-to documentation for development, operation and testing. | Practical commands live here, not in the root README. |
| `reference/` | Detailed product contracts and lookup material: database, agents, governance, sources, security, scoring and glossary. | Precise detail is welcome; story duplication is not. |
| `decisions/` | ADRs and their DOC-001 status surface. | Decisions explain why, not how-to or current-state prose. |
| `planning/` | Active planning only. | One active roadmap plus short active plans; old work-item notes go to archive. |
| `archive/` | Historical build notes, old analyses, reviews and replaced diagrams. | Useful for traceability, not authoritative current or product truth. |

## Artifact rule

The documentation architecture applies to files, not only folders:

- a product-contract file must distinguish approved decisions from open or proposed behavior;
- a current file should earn its place by being maintained, short and useful;
- a guide should help the operator do a task without becoming architecture prose;
- a reference file should describe a stable contract, model or lookup surface;
- a planning file should be active, temporary and easy to retire;
- historical traces should be archived or deleted instead of half-promoted;
- exports and retired restart files must not become source-of-truth documentation.

New documentation should normally update an existing artifact before creating a
new one. Add a new file only when it has a distinct audience, lifecycle or
contract.

## Docs-as-code guards

- `scripts/check_documentation_architecture.py`
- `scripts/check_documentation_references.py`
- `scripts/check_adr_rebaseline.py`

## Key reference surfaces

- `reference/product-contract/PRD.md`
- `reference/product-contract/PRODUCT_DECISION_REGISTER.md`
- `reference/product-contract/ACCEPTANCE_SCENARIOS.md`
- `reference/product-contract/TRACEABILITY.md`
- `reference/database/schema_overview.md`
- `reference/database/schema_relationships.md`
- `reference/governance/governance_foundation.md`
- `reference/security/search_intelligence_security_baseline.md`
- `reference/search-intelligence/llm_booster_cascade.md`
- `reference/search-intelligence/ml_learning_layer.md`
- `decisions/adr_status_table.md`

## ADRs

ADRs live in `decisions/adr/`. Use `decisions/adr_status_table.md` before
reading an ADR as current implementation truth.

## Exports

`exports/` contains generated runtime reports and review artifacts. Exports are
reports, not source-of-truth handoffs and not pipeline inputs.

Reference path anchors: `docs/reference/database/schema_overview.md`, `docs/reference/database/schema_relationships.md`.
