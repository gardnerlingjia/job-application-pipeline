# Career Intelligence

Career Intelligence assesses job descriptions against a versioned candidate profile. V1.1 adds
local batch automation. V1.2 adds Silver-layer ingestion; it does not apply to jobs, scrape new
sources, alter upstream ingestion, or modify the Silver schema. V1.3 adds a local daily runner for
unattended macOS refreshes from the existing Silver layer.

## Architecture

`assessor.py` orchestrates lane classification, capability/domain/location/network matching,
evidence strength, constraints, scoring, and recommendations. `cli.py` provides interactive
single-job assessment. `batch.py` validates inbox files, invokes the same `assess_opportunity()`
function, and maintains machine- and human-readable outputs. `silver_adapter.py` reads the
normalized `silver_jobs` representation plus linked `raw_jobs.raw_data`, converts available source
fields into the Career Intelligence input shape, and keeps source provenance separate from the
public result schema. `ingest_silver.py` assesses converted Silver rows through the same V1.1
cumulative result lifecycle. `daily.py` wraps Silver ingestion with a local runtime lock, concise
logs, and operator-friendly terminal output for once-per-day execution. A bad file or bad Silver
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

Logs intentionally avoid full job descriptions and raw Silver payloads.

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
