# Career Intelligence

Career Intelligence assesses job descriptions against a versioned candidate profile. V1.1 adds
local batch automation. V1.2 adds Silver-layer ingestion; it does not apply to jobs, scrape new
sources, alter upstream ingestion, or modify the Silver schema. V1.3 adds a local daily runner for
unattended macOS refreshes from the existing Silver layer. V1.4-lite adds persistent local operator
review state for the daily radar. V2.0 projects Career Intelligence into the existing Product V1
Control Center as an additional decision lens. V2.1 adds Lingjia Gardner's source strategy as a
configuration-backed prioritization layer over the existing source architecture.

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
existing source overview with Lingjia-specific source tiers, roles, priorities, and gaps. A bad file
or bad Silver record is reported; other records continue processing. Hard-stop decisions come
unchanged from the existing constraint and recommendation modules.

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

## Silver Deduplication

Silver ingestion reuses the V1.1 cumulative result identity by generating a deterministic
`source_file` for each Silver record. The preferred stable identity is
`source_name + external_job_id`, matching the existing upstream duplicate protection for
`raw_jobs`. If no external job id exists, the deterministic fallback is `raw_job_id`; if that is
unavailable, `silver_job_id`, `canonical_key_candidate`, and finally company/title/location content
are used in that order.

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
and operator state. Because V1.1 public results do not store `network_access` or
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
