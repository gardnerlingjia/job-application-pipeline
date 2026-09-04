# Current System Architecture

Status: current truth
Scope: product-level architecture after DOC-001M

## Architecture in one sentence

Market signals are treated as weak evidence until they pass bounded discovery,
origin/detail evidence checks, explicit gates and controlled approval paths.
Only then can a source become operational input for Bronze/Silver/Gold and the
Control Center.

```text
Market Sensors
  -> Candidate / Source Discovery
  -> URL / Origin / Detail Evidence
  -> Gates and Stopper Reassessment
  -> Connector Candidate / Build / Validation / Approval
  -> Active Controlled Source
  -> Bronze / Silver / Gold / Control Center
```

## Core boundaries

| Boundary | Rule |
|---|---|
| Sensor vs source | Discovery signal is not active source truth. |
| Candidate vs connector | Candidate evidence does not imply connector registration. |
| Evidence vs approval | Repair agents can produce evidence; they do not approve themselves. |
| Queue vs repair | Queue agents route; they do not repair. |
| Gate vs discovery | Gates evaluate evidence; they do not discover it. |
| Stop vs false negative | A stop is an audit input, not automatically final truth. |
| Report vs input | Exports are reports, never hidden pipeline inputs. |
| Current docs vs history | Historical notes must not look like current architecture. |

## Main system areas

### Market sensors

Market sensors and aggregators discover companies, source targets and search
spaces. They are intentionally bounded and defensive. Aggregators are discovery
inputs, not canonical source truth.

### Candidate and origin discovery

Candidate discovery turns signals into employer-origin candidates. Candidate
identity, source URL evidence and duplicate handling are safety concerns: missing
URLs stay missing, and ambiguous candidates must not be pushed through the
pipeline as if they were validated.

### Detail evidence and gates

Origin/detail evidence is required before connector work. Gates decide whether
evidence is enough to progress. Stops must include a reason, next safe action and
a manual-review path.

### Connector path

Connector candidacy, artifact generation, validation, registration planning,
final approval and active controlled operation are separate stages. Connector
artifacts are not activation.

### Job data layers

- Bronze keeps bounded raw acquisition and lineage.
- Silver builds canonical job representation and quality filtering.
- Gold provides decision, observability and Control Center read models.

### Control Center and observability

The Control Center should show lifecycle state, blockers, false-negative
pressure, gate status, next safe actions and agent/health summaries. The current
Agent Monitor uses derived lifecycle/gate/orchestrator signals; true runtime
agent health remains future work.

Career Opportunity Intelligence is integrated as a sidecar read model in the
existing Product V1 Control Center. Its data owner remains
`src/career_intelligence/`: assessments live in `jobs/results/opportunities.json`,
Silver/source traceability lives in
`jobs/results/silver_ingestion_provenance.json`, and operator review state lives
in `.runtime/career_intelligence/operator_state.json`. The Control Center joins
Career Intelligence opportunities to Product V1 jobs by `source_file` ->
Silver provenance -> `silver_job_id`. Missing or malformed Career Intelligence
runtime data fails closed for that lens and must not break Product V1.

The Career Intelligence tab can select a joined `silver_job_id` into the existing
Application Workspace for human review. It does not create application authority,
does not bypass document or evidence gates, and does not automate submission.
Product V1 ranking and Top-5 remain owned by the Gold/Product V1 read models.

Lingjia's Career Intelligence source strategy is a configuration-backed
prioritization layer over the existing connector/source architecture. The config
defines target employers and discovery channels with tier, priority, role,
career-lane relevance, preferred evidence type, location relevance and
active/watch status. The read model decorates `source_connector_overview` and
adds explicit gap rows for configured targets that do not yet have an existing
candidate, connector support, active profile or ingestion evidence. It never
changes connector readiness, validation, approval, activation or scoring logic.

Career Intelligence V2.2 adds an adaptive candidate layer beside that curated
strategy. `adaptive_sources.py` reads existing `opportunities.json` and
`silver_ingestion_provenance.json`, normalizes employer identity, excludes
already-configured strategy employers, aggregates evidence, and exposes
promotion suggestions plus configured-source health advisories through the same
source overview read model. Operator decisions live under
`.runtime/career_intelligence/adaptive_source_state.json`. This runtime overlay
is not connector lifecycle truth and cannot activate, register, crawl, ingest,
rank or submit anything.

## Current maturity note

The documentation structure is now stable enough for product work again, but the
pipeline itself is not closed-loop yet. The biggest product blockers remain
StepStone discovery rotation, candidate promotion quality, URL/detail evidence
generics and repair/stop taxonomy.

Detailed references live under `../reference/`. Diagrams live in
`system-diagrams.md`.
