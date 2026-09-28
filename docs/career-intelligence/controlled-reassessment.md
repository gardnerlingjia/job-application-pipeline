# Controlled reassessment of existing Career Intelligence opportunities

## Contract

`src.career_intelligence.reassess` defaults to **preview**. It reads the saved opportunity
identities and their provenance, queries exactly those Silver IDs in a read-only database
transaction, and evaluates current calibration. It never fetches provider jobs, activates
sources, creates new opportunity identities or updates Product V1 database assessments.
Run all commands from the repository root.

Preview writes an isolated candidate directory, `plan.json` and `report.md`. It does not
change production opportunities, provenance, radar or operator-state files. It briefly
holds the shared daily lock and retains its persistent `.guard` file. An absent state file
stays absent. The plan contains descriptions and evidence: keep it in ignored local runtime
storage, not in Git.

The report contains every selected identity, company/title, old/new candidacy score,
recommendation, semantics version, added/removed constraints and exact blocking reasons.
The proposed complete-set distribution retains blocked, missing and unselected records.
“Unchanged decisions” means the score, recommendation and constraints are unchanged;
upgraded semantics/explanations can still differ.

## Preview — default and explicit forms

```sh
cd /Users/lingjiamacbook/Documents/projects/job-application-pipeline
.venv/bin/python -B -m src.career_intelligence.reassess
```

For a deliberately named review artifact (the directory must not already exist):

```sh
.venv/bin/python -B -m src.career_intelligence.reassess preview \
  --output-dir .runtime/career_intelligence/reassessments/previews/mobility-review
```

Optional repeated `--source-file` flags select an explicit subset of the saved identities.
Unknown selections are reported as missing; this is not a way to add jobs. There is no
arbitrary Silver range or default `LIMIT 100` in reassessment.

```sh
.venv/bin/python -B -m src.career_intelligence.reassess preview \
  --source-file EXISTING_SOURCE_FILE_FROM_THE_REPORT \
  --output-dir .runtime/career_intelligence/reassessments/previews/subset-review
```

## Evidence and identity safeguards

- Require exactly one provenance record and one matching Silver row per selected identity.
  Verify the saved source filename, stable identity hash/type, source/external ID, raw ID,
  Silver ID, company and title. Missing, ambiguous or changed identities are blocked.
- Prefer the exact `explanation.input_evidence` snapshot. Future batch and Silver assessments
  now save their actual role/market arguments there, including explicit empty mappings.
- Otherwise accept a matching original processed job JSON, preserving its optional evidence.
- For v3/v4 records only, the supported normalized requirement facts and enumerated unknown
  market fields can be reconstructed. Positive network access without its original
  relationship/source, omitted known market facts, and ambiguous requirement evidence block
  automatic reassessment. Cold access and explicit unknown fields are not upgraded to
  positive evidence. The reconstruction basis is recorded in the report.
- Unversioned records without original inputs/snapshots block. Do not fabricate empty
  evidence dictionaries to bypass this safeguard; recover the original evidence first.
- Keep original provenance records unchanged. Derived reassessment provenance, input hashes,
  full input rows and recovered evidence are recorded separately in the reviewed plan and
  archived publication manifest. Original provenance score fields remain historical; current
  candidacy is in the opportunity record and new derived values are in the revision audit.
- Freeze the saved freshness penalty for this calibration-only operation. This is not a
  daily freshness refresh. Normal missing-description/scoring/evidence gates still apply.
- Preserve every unselected or blocked opportunity record and its identity. Preserve all
  existing operator-state bytes. Radar generation includes dismissed records under their
  existing state; the Control Center continues to join state by the same identity.

## Apply — explicit approval required

Inspect `report.md` and `plan.json`. A plan with any blocked/missing selected record is not
publishable. Recover evidence or explicitly preview a smaller eligible subset. Never infer
approval from completion of a preview.

After explicit approval, pass the **literal confirmation fingerprint from that reviewed plan**:

```sh
.venv/bin/python -B -m src.career_intelligence.reassess apply \
  --plan .runtime/career_intelligence/reassessments/previews/mobility-review/plan.json \
  --confirm REVIEWED_CONFIRMATION_SHA256
```

Apply rechecks the plan/candidate hashes, complete production result tree, operator-state
file (including absence), current calibration code/configuration, and exact database input
rows. Any drift requires a new preview. Apply uses paths/scope frozen in the plan and does
not calculate new scores itself.

## Publication, concurrency and interruption recovery

Preview, apply and rollback share `DailyRunLock`. The daily workflow now also holds a
persistent OS file lock, released by the kernel on process exit. An old timestamp does not
permit stealing a live process's lock. Incomplete lock metadata fails closed rather than
being deleted while a writer may be active. A valid dead-PID lock can be reclaimed.

Before publication, a uniquely named directory under
`.runtime/career_intelligence/reassessments/archives/` stores the complete original results
directory, operator-state file if present, and an immutable `manifest.json`. Absence of the
state file is recorded as `state_hash: null`. Archives and candidate files are flushed before
publication. The archive contains both before/after file hashes and the entire reviewed plan.

Publication uses one **atomic directory exchange** on the same filesystem: macOS
`renameatx_np(RENAME_SWAP)` or Linux `renameat2(RENAME_EXCHANGE)`. Unsupported filesystems or
platforms fail without file-by-file publication. Symlink result trees are rejected. Extra
files in the results directory are preserved. Publication never mutates the operator-state
file.

A caught failure after exchange triggers an atomic reversal. A hard process exit, or failure
of the reversal itself, still leaves either the complete old or complete new directory—not
partially replaced files. The durable PREPARED archive allows rollback even if the success
receipt was never written. Do not delete an archive or retained `.career-publication-*`
directory after an interrupted publication until its before/after hashes have been reviewed.

## Rollback

Successful apply prints its exact archive path and `rollback_confirmation`. After an
interruption, the same token is available as `rollback_token` in the archive's immutable
`manifest.json`; the optional `published.json` receipt is not required.

```sh
.venv/bin/python -B -m src.career_intelligence.reassess rollback \
  --archive .runtime/career_intelligence/reassessments/archives/ARCHIVE_ID \
  --confirm REVIEWED_ROLLBACK_TOKEN
```

Rollback verifies archive integrity and requires production to match that generation's
published hash. It refuses if operator decisions changed, rather than restore a stale radar.
It archives the outgoing generation and atomically restores the complete original result
set. Operator-state bytes remain untouched. If production already matches the manifest's
`before` hashes, it is already restored: no rollback is needed. If it matches neither set,
stop for manual review; never force-copy individual files.

A PostgreSQL backup is not required by this operation because all database access is
read-only. A database backup alone would not protect these file-backed results; the local
result/state archive is mandatory.

## Control Center and boundaries

After publication or rollback, use Control Center **Refresh** to load the current result
files. It does not import preview directories or reassess jobs itself. Historical archived
results and versioned calibration fixtures remain unchanged.

This mechanism does not grant permission to apply. For the autonomous mobility update,
implementation/testing is followed by preview only; publication requires separate user approval.

## Validation and initial preview — 2026-09-23

- 30 new reassessment regression cases cover exact IDs, incomplete provenance, original and
  normalized evidence recovery, preserved operator decisions, unselected records, stale
  review fingerprints, daily-lock exclusion, interrupted publication, hard process exit,
  reversal failure and archive rollback.
- Career Intelligence suite: **361 passed**. Full suite: **3,430 passed, 4 existing failures**.
  Three failures are the known macOS Bash `mapfile` issue in daily-pipeline tests; the fourth
  is the pre-existing untracked `docs/.DS_Store` documentation-layout failure.
- Configuration validation, Ruff on changed Python files, and `git diff --check` passed.
- Preview only selected all **45** saved identities: **13 reassessed, 32 blocked, 0 missing**.
  All blocked records lack a reconstructable legacy evidence contract/original snapshot.
  Their records and provenance remain unchanged. The 13 recoverable records had v3 evidence
  explanations; the preview records their explicit reconstruction basis and advances them to v4.
- Proposed complete-set recommendation distribution (retaining blocked records): APPLY 1 → 0,
  WATCH 15 → 14, SKIP 29 → 31. This has **not** been published.
- The whole-set preview is **not eligible for apply** because 32 selected records are blocked.
- Production opportunities, provenance and radar were verified byte-for-byte unchanged;
  operator-state absence was preserved. No production publication archive was created.
- Local review artifacts: `.runtime/career_intelligence/reassessments/previews/autonomous-mobility-2026-09-23/`
  contains `report.md`, `plan.json`, candidate results and `production-verification.json`.

## Reviewed legacy StepStone recovery

The opt-in `--recovery-manifest PATH --recovery-confirm SHA256` preview arguments
accept only a fingerprinted review manifest. Each entry binds `source_file`, Silver
and Bronze (`raw_job_id`) IDs, source name/external ID, stable identity type/hash,
the SHA-256 of the exact UTF-8 captured `detail_evidence.text`, and a historical
contract reference. Identity validation precedes recovery. Unexpected optional
evidence, a conflicting original processed input, missing sources, or changed
hashes fail closed. This does not bypass the ordinary missing-snapshot gate.

The historical three-argument Silver ingestion contract supplied company, title
and description only. Empty optional mappings record **not supplied**, not confirmed
negative requirement facts. Retained captured descriptions are available, but
historical assessment-time byte-for-byte equivalence cannot be proven.

Private reviewed manifest (generated output, not a scoring input by default):
`.runtime/career_intelligence/reassessments/legacy-stepstone-recovery.json`.
Its reviewed content fingerprint is
`4a6fa8b302757d9231df541176d0314b98c2dfe2e3bc2529eb1f220194a05053`.
It contains exactly the 30 R1 identities reviewed in the preceding investigation.
The following command selects those 30 plus the 13 previously eligible v3 records
by their saved identities, preserving the two unselected MOIA records:

```bash
.venv/bin/python -B - <<'PY'
import json
from pathlib import Path
from src.career_intelligence.reassess import main
base = Path('.runtime/career_intelligence/reassessments')
previous = json.loads((base / 'previews/autonomous-mobility-2026-09-23/plan.json').read_text())
manifest = base / 'legacy-stepstone-recovery.json'
reviewed = json.loads(manifest.read_text())
selected = sorted({r['source_file'] for r in reviewed['records']} |
                  {r['source_file'] for r in previous['records'] if r['status'] == 'reassessed'})
assert len(reviewed['records']) == 30 and len(selected) == 43
args = ['preview', '--recovery-manifest', str(manifest), '--recovery-confirm',
        '4a6fa8b302757d9231df541176d0314b98c2dfe2e3bc2529eb1f220194a05053',
        '--output-dir', str(base / 'previews/combined-legacy-2026-09-23')]
for source in selected:
    args += ['--source-file', source]
raise SystemExit(main(args))
PY
```

Use a new output directory for a repeat preview. Unselected records now appear in
the report as `preserved`, with identical before/after values. A selected blocked
record still prevents publication; an explicitly unselected record does not.
The reviewed manifest and per-record recovery provenance are embedded in the
fingerprinted plan and publication archive. Existing apply and rollback commands
and atomic whole-directory publication protections are unchanged. Apply still
requires the new plan's exact confirmation and separate operator approval.

## Explicit evidence-blocked preservation

A preview may opt into `--preservation-manifest PATH`. Version 1 manifests contain
`schema_version: 1` and `records`, each binding `source_file`, `record_sha256`
(SHA-256 of the exact UTF-8 JSON object slice in production opportunities.json),
`provenance_sha256` (the existing canonical `digest` function), and the exact
`evidence_reason`. Review these bindings against production and the blocked preview.
The manifest is embedded in the confirmation-fingerprinted plan.

This deliberately narrow path accepts only `missing_evidence_snapshot:` failures.
The complete Silver/Bronze/source identity and provenance must still validate, and
there must be no other failure. It never generates replacement evidence or an
assessment for an accepted preserved record. Missing identities, mismatches,
recoverable records and failed assessments cannot use this exemption.

Selected records expose explicit `state` values: `REASSESSED`,
`PRESERVED_UNCHANGED`, `BLOCKED`, or `MISSING` (the lowercase `status` is retained
for machine consumers). Previously supported unselected records remain `preserved`.
Preserved unchanged records have separate counts and do not count as reassessed
or blocked. Complete-set identity accounting, provenance bytes and preserved
object bytes are checked during preview and again during apply. The surrounding
JSON array formatting can change; each preserved object retains its exact bytes.

```bash
.venv/bin/python -B -m src.career_intelligence.reassess preview \
  --preservation-manifest .runtime/career_intelligence/reassessments/moia-preservation-2026-09-28.json \
  --output-dir .runtime/career_intelligence/reassessments/previews/evidence-interpretation2-preserved-2026-09-28
```

Only after separate approval, use the unchanged `apply --plan PATH/plan.json
--confirm FINGERPRINT` command. Apply revalidates production, operator state,
calibration, candidate files and source rows under the daily lock. The existing
publication mechanism must create, hash-verify and fsync the complete rollback
archive before any atomic exchange. Archive or exchange failure leaves the old
complete generation in place. No archive is created by preview. Rollback remains
`rollback --archive ARCHIVE --confirm ROLLBACK_TOKEN`.
