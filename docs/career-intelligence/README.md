# Career Intelligence

Career Intelligence assesses job descriptions against a versioned candidate profile. V1.1 adds
local batch automation; it does not apply to jobs or alter upstream ingestion.

## Architecture

`assessor.py` orchestrates lane classification, capability/domain/location/network matching,
evidence strength, constraints, scoring, and recommendations. `cli.py` provides interactive
single-job assessment. `batch.py` validates inbox files, invokes the same `assess_opportunity()`
function, and maintains machine- and human-readable outputs. A bad file is reported and left in
the inbox; other files continue processing. Hard-stop decisions come unchanged from the existing
constraint and recommendation modules.

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

## Limitations

Inputs must be UTF-8 JSON with non-empty `company`, `title`, and `description` strings. Processing
is local and synchronous. Results depend on keyword evidence and configured network knowledge;
they support human decisions and never trigger applications.
