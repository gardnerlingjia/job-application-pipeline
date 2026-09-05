# Career Intelligence

Career Intelligence assesses job descriptions against a versioned candidate profile. V1.1 adds
local batch automation. V1.2 adds Silver-layer ingestion; it does not apply to jobs, scrape new
sources, alter upstream ingestion, or modify the Silver schema. V1.3 adds a local daily runner for
unattended macOS refreshes from the existing Silver layer. V1.4-lite adds persistent local operator
review state for the daily radar. V2.0 projects Career Intelligence into the existing Product V1
Control Center as an additional decision lens. V2.1 adds Lingjia Gardner's source strategy as a
configuration-backed prioritization layer over the existing source architecture. V2.2 adds
adaptive source discovery and promotion suggestions from observed opportunities; those suggestions
remain local candidates until an operator reviews them. V2.3 adds the first bounded live employer
flow for MOIA through the existing Greenhouse connector and source lifecycle.

## Architecture

`assessor.py` orchestrates lane classification, capability/domain/location/network matching,
evidence strength, constraints, scoring, and recommendations. `cli.py` provides interactive
single-job assessment. `batch.py` validates inbox files, invokes the same `assess_opportunity()`
function, and maintains machine- and human-readable outputs. `silver_adapter.py` reads the
normalized `silver_jobs` representation plus linked `raw_jobs.raw_data`, converts available source
fields into the Career Intelligence input shape, and keeps source provenance separate from the
public result schema. `ingest_silver.py` assesses converted Silver rows through the same V1.1
cumulative result lifecycle. `daily.py` wraps Silver ingestion with a local runtime lock, concise
logs, operator state counts, and operator-friendly terminal output for once-per-day execution.
`operator_state.py` stores human review state outside `opportunities.json` and renders the daily
radar by operator state, recommendation, and score. `control_center.py` reads those runtime files
and joins them to Product V1 jobs through Silver provenance without changing scoring or the V1.1
result schema. `source_strategy.py` reads `config/career_source_strategy.yaml` and decorates the
existing source overview with Lingjia-specific source tiers, roles, priorities, and gaps.
`adaptive_sources.py` reads the same Career Intelligence results and Silver provenance, aggregates
unknown employers into adaptive source candidates, adds source-health advisory signals, and stores
operator promotion decisions in local runtime state only. `moia_live_source.py` provides the
MOIA-only activation preflight and daily live-source flow while delegating ingestion, Silver
transformation, and Career Intelligence refresh to existing commands. A bad file or bad Silver
record is reported; other records continue processing. Hard-stop decisions come unchanged from the
existing constraint and recommendation modules.

## Configuration

Candidate strategy is defined in `config/career_profile.yaml`, `config/capability_profile.yaml`,
`config/constraints.yaml`, and `config/network_profile.yaml`. Treat these as calibrated product
inputs: do not change capability strengths or strategy as part of batch operations.

## Single-job CLI

Run from the repository root:

```bash
python -m src.career_intelligence.cli \
  --company MOIA \
  --title "Senior Technical Program Manager" \
  --file jobs/examples/job_description.txt
```

## Batch Usage

Place one or more `.json` files in `jobs/inbox/`:

```json
{"company": "MOIA", "title": "Program Manager", "description": "Full job text"}
```

Then run:

```bash
python -m src.career_intelligence.batch
```

Successful inputs move to `jobs/processed/` without replacing existing files. Invalid files remain
in `jobs/inbox/`, errors are printed to stderr, and the command exits nonzero after completing the
batch.

Results are a cumulative current corpus. Each result records its `source_file`; later runs merge new
files with the existing corpus and reject a filename that already contributed a result. An empty
rerun preserves both output files byte-for-byte. To rebuild the corpus intentionally, archive or
remove both result files and repopulate the inbox from controlled source data.

## Output Files

- `jobs/results/opportunities.json`: schema-versioned assessments sorted by opportunity score,
  company, and title, including risks and matched capabilities.
- `jobs/results/opportunity_radar.md`: the same opportunities grouped by recommendation and sorted
  within each group.

The first run with an empty inbox creates an empty JSON list and radar. Later empty runs preserve
the existing corpus.

## Silver Ingestion

Run from the repository root:

```bash
python -m src.career_intelligence.ingest_silver
```

Optional arguments follow existing repository conventions:

```bash
python -m src.career_intelligence.ingest_silver \
  --source personio \
  --limit 25 \
  --results jobs/results
```

The Silver flow is:

1. Read normalized `silver_jobs` rows joined to their source `raw_jobs.raw_data`.
2. Map `company_name` to `company`, `title` to `title`, and strong source-provided job/detail
   description evidence from `raw_data` to `description`.
3. Call `assess_opportunity()` for each converted record.
4. Append compatible V1.1 records to `jobs/results/opportunities.json` and refresh
   `jobs/results/opportunity_radar.md`.
5. Write Silver/source traceability to `jobs/results/silver_ingestion_provenance.json`.

`opportunities.json` remains the V1.1 public schema. Silver provenance is stored in the sidecar
file keyed by the same `source_file` value, preserving compatibility for existing readers while
keeping traceability to `silver_job_id`, `raw_job_id`, `source_name`, `external_job_id`,
`source_url`, canonical fields, the description source path, description quality, and whether the
record was assessed or skipped.

Freshness is recorded in the same sidecar without changing `opportunities.json`.
Employer-provided `publication_date` is preferred when available. `first_seen_at` and `last_seen_at`
remain separate observation timestamps; `first_seen_at` is used for job age only as a clearly
labelled `first_seen_fallback` when no reliable publication date exists. Dates are never fabricated.
Career Intelligence freshness buckets are `NEW` for 0-3 days, `FRESH` for 4-7 days, `AGING` for
8-14 days, `OLD` for more than 14 days, and `UNKNOWN` when no reliable date exists. `AGING` and
`OLD` jobs receive a local Career Intelligence ranking penalty; Product V1 ranking authority and
Top-5 semantics are unchanged.

## Silver Deduplication

Silver ingestion reuses the V1.1 cumulative result identity by generating a deterministic
`source_file` for each Silver record. The preferred stable identity is
`source_name + external_job_id`, matching the existing upstream duplicate protection for
`raw_jobs`. If no external job id exists, the deterministic fallback is `raw_job_id`; if that is
unavailable, `silver_job_id`, `canonical_key_candidate`, and finally company/title/location content
are used in that order.

## MOIA Live Source Flow

V2.3 corrects MOIA to the existing Greenhouse source family:

```yaml
source_name: greenhouse:moia
source_role: employer_origin
```

`greenhouse:moia` maps to the Greenhouse board token `moia` and the canonical connector request
`https://boards-api.greenhouse.io/v1/boards/moia/jobs`. The guided MOIA CLI delegates validation,
approval and activation to the existing source lifecycle gates.

MOIA activation is explicit and gate-bound:

```bash
python -m src.career_intelligence.moia_live_source doctor
python -m src.career_intelligence.moia_live_source preflight
python -m src.career_intelligence.moia_live_source validate --dry-run
python -m src.career_intelligence.moia_live_source validate --reviewed-by lingjia
python -m src.career_intelligence.moia_live_source approve --reviewed-by lingjia
python -m src.career_intelligence.moia_live_source activate
```

The seed migration `db/migrations/107_register_moia_greenhouse_source_candidate.sql` creates only a
MOIA source candidate. It does not approve gates, create a search profile, run ingestion, write
Bronze/Silver rows, rank jobs, schedule work, or touch applications. Activation refuses to write the
active profile unless `connector_validation_gate` is passed with `ready_for_final_approval` and
`final_approval_gate` is passed with `approve_connector_registration`.

After activation, daily MOIA execution uses one local command:

```bash
python -m src.career_intelligence.moia_live_source run-daily
```

That command composes the canonical pipeline:

1. `python -m src.ingest_jobs --profile moia_controlled_hannover_precision`
2. `python -m src.run_silver_jobs --source greenhouse:moia --limit 25`
3. `python -m src.career_intelligence.daily --source greenhouse:moia --limit 25`

Start the local database first with the repository Docker setup, for example:

```bash
docker compose up -d postgres
```

For local development, `src.config.get_database_config()` defaults to the repository Docker
Compose database (`localhost:5432`, `job_pipeline`, `job_user`). `POSTGRES_*` environment variables
still override those defaults. If the database is unavailable, MOIA commands print
`Database unavailable. Start with: docker compose up -d postgres`; if required schema tables are
missing, they print `.venv/bin/python scripts/apply_db_migrations.py --apply --applied-by local`.

Then open the existing Product V1 Control Center with the repository launcher. The Sources view
should show MOIA as active after activation, with last ingestion result, Bronze count and Silver
count coming from existing lifecycle read models. The Career Intel view should show actual scored
opportunities after Silver rows with strong Greenhouse `job.content` evidence are available.

V2.3 does not activate any other employer. Other strategic sources remain candidates or gaps until
their actual provider is verified and their lifecycle gates pass.

If a generated `source_file` is already present in `opportunities.json`, the record is skipped and
not reassessed. Duplicate Silver records within one run are reported without stopping the rest of
the run.

## Daily Command

Run from the repository root:

```bash
python -m src.career_intelligence.daily
```

Optional arguments mirror Silver ingestion:

```bash
python -m src.career_intelligence.daily \
  --source personio \
  --limit 100 \
  --results jobs/results \
  --runtime-dir .runtime/career_intelligence
```

The daily runner does not run connectors, scrape, alter Silver, or apply to jobs. It only reads
existing Silver records through V1.2 and refreshes Career Intelligence outputs. It prints:

- Silver jobs loaded
- converted
- newly assessed
- already known/skipped
- errors
- counts for `APPLY_NOW`, `NETWORK_FIRST`, `EXPLORE`, `WATCH`, and `SKIP`

The command exits `0` when ingestion completes without record errors, `1` for ingestion or
processing failures, and `2` when another daily run is already active.

## Daily Logs And Lock

Runtime files live under `.runtime/career_intelligence/`, which is gitignored.

- `.runtime/career_intelligence/logs/daily_*.log`: JSON run logs with start time, finish time,
  counts, sanitized errors, and exit status.
- `.runtime/career_intelligence/daily.lock`: local exclusive lock that prevents overlapping daily
  runs. Normal locks are removed at the end of the process. Stale or dead-process locks are cleaned
  before retrying.
- `.runtime/career_intelligence/operator_state.json`: persistent local operator review state keyed
  by `source_file`.

Logs intentionally avoid full job descriptions and raw Silver payloads.

## Operator Workflow

Every opportunity has one operator state:

- `NEW`: default for any current opportunity without stored state.
- `INTERESTED`: marked for follow-up and kept prominent.
- `REVIEWED`: seen by the operator but still visible at lower priority.
- `DISMISSED`: hidden from the default actionable radar.

State is stored separately from `jobs/results/opportunities.json`, keyed by stable `source_file`.
Daily reruns, Silver refreshes, and rescoring do not reset stored state. If an opportunity
temporarily disappears from source data, its stored state remains in
`.runtime/career_intelligence/operator_state.json`.

List current actionable opportunities:

```bash
python -m src.career_intelligence.operator_state list
```

Include dismissed opportunities:

```bash
python -m src.career_intelligence.operator_state list --include-dismissed
```

Set state:

```bash
python -m src.career_intelligence.operator_state set \
  --source-file "silver-personio-example-1234567890abcdef.json" \
  --state INTERESTED
```

Valid states are `NEW`, `INTERESTED`, `REVIEWED`, and `DISMISSED`. Invalid states are rejected and
malformed state files are not silently overwritten.

The daily command rewrites `jobs/results/opportunity_radar.md` as:

```text
# Career Opportunity Radar

## NEW
### APPLY_NOW
...

## INTERESTED
...

## REVIEWED
...
```

`python -m src.career_intelligence.daily` is the canonical operator workflow; direct
`ingest_silver` runs produce the lower-level V1.2 recommendation radar.

Within each operator state, opportunities remain grouped by recommendation and sorted by score,
company, title, and `source_file`. The default radar omits `DISMISSED`. To render a full radar that
includes dismissed opportunities:

```bash
python -m src.career_intelligence.operator_state radar --include-dismissed
```

To intentionally reset operator state, stop any scheduled daily run and remove
`.runtime/career_intelligence/operator_state.json`. The next daily run treats all current
opportunities as `NEW`.

## macOS Scheduling

A launchd template is available at `docs/career-intelligence/macos-launchd.example.plist`.
Copy it to `~/Library/LaunchAgents/`, then replace all placeholders:

- `/ABSOLUTE/PATH/TO/REPO` with this repository's absolute path.
- `/ABSOLUTE/PATH/TO/REPO/.venv/bin/python` with the Python interpreter that has the repository
  dependencies installed.
- The `Label` value with a local identifier if desired.
- `Hour` and `Minute` with the preferred daily run time.

Load the schedule:

```bash
launchctl load ~/Library/LaunchAgents/com.example.career-intelligence-daily.plist
```

Run it manually for a smoke test:

```bash
launchctl start com.example.career-intelligence-daily
```

Disable and remove the schedule:

```bash
launchctl unload ~/Library/LaunchAgents/com.example.career-intelligence-daily.plist
```

Then delete the copied plist from `~/Library/LaunchAgents/`.

## Product V1 Control Center

Career Intelligence V2.0 is integrated into the existing Product V1 Control Center. It does not
create a second dashboard. The Control Center API reads:

- `jobs/results/opportunities.json` for the V1.1 assessment records.
- `jobs/results/silver_ingestion_provenance.json` for traceability and the `source_file` to
  `silver_job_id` join.
- `.runtime/career_intelligence/operator_state.json` for local operator state.

The Product V1 job identity remains `silver_job_id`. Career Intelligence opportunities remain keyed
by `source_file`; the sidecar provenance maps `source_file` back to `silver_job_id` when available.
Joined jobs receive a `career_intelligence` decoration in the Control Center payload, and the full
Career Intelligence lens is also exposed under the top-level `career_intelligence` key. Product V1
ranking, Top-5 semantics, hard-filter decisions, Silver schema, and the public
`opportunities.json` schema are unchanged.

The UI adds a dedicated Career Intelligence tab inside the existing Operator Workspace because the
filters and state actions are specific to the career radar. The tab shows score, recommendation,
career lane, constraints, risks, matched capabilities, network fields when available, provenance,
operator state, freshness bucket, job age, publication date, first seen and last seen. Because V1.1
public results do not store `network_access` or
`relationship_level`, the Control Center shows those fields as unavailable instead of recomputing or
fabricating them.

Operator-state changes in the Control Center call the same `operator_state.py` persistence logic used
by the CLI. The POST action is scoped to `source_file` and one valid state:
`NEW`, `REVIEWED`, `INTERESTED`, or `DISMISSED`. It writes only local runtime state, never Product V1
ranking, Silver, connectors, applications, or provider-backed data.

For `INTERESTED`, `APPLY_NOW`, and `NETWORK_FIRST` opportunities that join to a Product V1
`silver_job_id`, the Career tab can open the existing Application Workspace with that job selected.
The workspace still uses its source-grounded `draft_for_review` flow and keeps all approval gates,
document checks, provider boundaries, and no-submission guarantees.

If Career Intelligence has never run, or a runtime file is missing or malformed, the Control Center
fails closed for the Career tab while leaving Product V1 available. Scores are never fabricated.

## Lingjia Source Strategy

V2.1 stores source strategy in `config/career_source_strategy.yaml`. This is configuration, not
connector registration or activation. Each source record includes:

- company/source name
- tier: `A`, `B`, or `C`
- strategic priority from `0` to `100`
- relevant career lanes
- preferred evidence type
- source role: `employer_origin` or `discovery`
- optional location relevance
- active/watch status

Tier A contains strategic employer sources for autonomous mobility, robotics, technical
program/product leadership, AI/data transformation, strategy/executive operations, and mobility
ecosystems. Tier B contains adjacent employers. Tier C contains discovery sources such as Stepstone
and Bundesagentur fuer Arbeit.

The source strategy decorates the existing Control Center source overview. It does not replace
connector readiness, validation, final approval, activation, Bronze/Silver ingestion, or Product V1
ranking. Employer-origin sources remain preferred evidence for Career Intelligence. Discovery
sources may identify opportunities, but they do not become stronger evidence than an employer-origin
vacancy when both exist.

Configured employers without implemented, validated, approved, active ingestion are shown as source
gaps or candidate sources. Supported connector families such as `personio:*`, `greenhouse:*`, and
`successfactors:*` can be shown as connector-supported but unconfigured. Unknown source families are
shown as connector gaps. Existing generic/demo sources remain visible under "Existing generic/demo
sources" and are not deleted or reclassified as Lingjia strategy targets.

## Adaptive Source Discovery

V2.2 keeps `config/career_source_strategy.yaml` as the committed baseline strategy and adds
`config/career_adaptive_source_rules.yaml` for deterministic suggestion thresholds. The adaptive
layer reads only existing local evidence:

1. Career Intelligence opportunities from `jobs/results/opportunities.json`.
2. Silver/source traceability from `jobs/results/silver_ingestion_provenance.json`.
3. The curated V2.1 strategy from `config/career_source_strategy.yaml`.
4. Local operator decisions from `.runtime/career_intelligence/adaptive_source_state.json`.

Candidates are keyed by normalized employer identity, not source URL. Employers already present in
the curated strategy are not duplicated as adaptive candidates. For new employers, the read model
aggregates observed opportunity count, assessed opportunity count, best and average opportunity
score, recommendation distribution, represented career lanes, Berlin/remote-Germany relevance,
location conflicts, evidence quality, employer-origin evidence availability, discovery-source
evidence availability, network relevance when available, first/last seen values, and explicit
promotion reasons.

Suggested actions are deterministic and explainable:

- `PROMOTE_TO_TIER_A`: repeated high-quality, high-scoring, location-compatible opportunities in
  primary career lanes, with employer-origin evidence.
- `PROMOTE_TO_TIER_B`: credible relevant opportunities in primary or adjacent lanes with compatible
  location evidence.
- `WATCH`: useful but thin, weak, aggregator-only, or ambiguous evidence.
- `IGNORE`: repeated low fit or a hard location conflict such as relocation to Munich or China.

Operator decisions are stored atomically in
`.runtime/career_intelligence/adaptive_source_state.json` with states `UNREVIEWED`, `PROMOTED_A`,
`PROMOTED_B`, `WATCH`, and `IGNORED`. These decisions survive reruns and do not edit
`config/career_source_strategy.yaml`, register connectors, activate profiles, crawl employers,
trigger ingestion, modify Product V1 ranking, or change Career Intelligence scoring. Approved
promotions are therefore local strategy overlays/candidate decisions, not lifecycle truth.

The Control Center Sources tab shows five groups: Strategic employers, Adjacent employers,
Discovery sources, Adaptive candidates, and Existing generic/demo sources. Candidate action buttons
write only adaptive source state. Configured sources may also receive advisory signals such as
`HEALTHY`, `LOW_ACTIVITY`, `LOW_RELEVANCE`, `NO_RECENT_SIGNAL`, or `REVIEW_RECOMMENDED`; these are
review prompts only and never downgrade a configured source automatically.

## Troubleshooting

- If the command exits `2`, another run is active or a valid lock exists. Check
  `.runtime/career_intelligence/daily.lock` and the latest daily log.
- If the command exits `1`, read the latest `.runtime/career_intelligence/logs/daily_*.log` and
  the terminal output. Record-level errors usually mean missing strong description evidence or
  invalid existing result/provenance files.
- If launchd does not run, verify `WorkingDirectory`, the Python path, file permissions, and the
  `StandardOutPath`/`StandardErrorPath` directories.
- If no new opportunities appear, confirm Silver rows already exist and include strong description
  evidence. Already-known Silver identities are skipped by design.
- If operator state looks wrong, inspect `.runtime/career_intelligence/operator_state.json`.
  Replace or remove it only intentionally; malformed files cause the state commands and daily
  runner to fail closed.
- If the Control Center Career tab says the radar is unavailable, run
  `python -m src.career_intelligence.daily` and check the latest daily log. Malformed runtime JSON
  is reported in the tab instead of breaking the whole Control Center.
- If a Career Intelligence opportunity cannot open the Application Workspace, confirm it is joined
  to a Product V1 `silver_job_id` and is either `INTERESTED`, `APPLY_NOW`, or `NETWORK_FIRST`.
- If the Sources tab shows a target employer as a gap, inspect the existing connector lifecycle:
  source candidate, connector implementation, validation gate, final approval gate, active search
  profile, and Bronze/Silver presence. V2.1 does not activate or crawl sources automatically.

## Limitations

Inbox inputs must be UTF-8 JSON with non-empty `company`, `title`, and `description` strings.
Silver ingestion requires usable `company_name`, `title`, and strong source description evidence.
The current normalized Silver table does not define a description column, so V1.2 derives
description from linked source evidence such as `raw_data.job.description` or bounded detail
evidence. Weak listing/card/snippet text is preserved as skipped provenance but is not scored.
`profile_terms` are never used as description text. Records without usable strong description
evidence are reported and skipped. Processing is local and synchronous. Results depend on keyword
evidence and configured network knowledge; they support human decisions and never trigger
applications.
