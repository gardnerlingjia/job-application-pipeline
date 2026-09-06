# Operations Current Truth

Status: current truth

Operational work is CLI-first and deliberately boring. The goal is reliable
changes, not clever terminal tricks.

Current operator entry points:

- `../guides/development-workflow.md` for commit, PR, merge and cleanup blocks.
- `../guides/operator-runbook.md` for local operation and recovery.
- `../career-intelligence/README.md` for the local Career Intelligence
  daily command, operator-state CLI, macOS scheduling template and Control
  Center lens behavior.
- `../guides/testing.md` for test expectations.
- `../reference/governance/workflow/validate001_unified_validation_command.md` and `scripts/run_validate001_unified_validation.py` for the unified local validation entry point.
- `../reference/operations/db_migration_tracking.md` for migration tracking.
- `../reference/operations/windows_scheduler_watchdog.md` for scheduler context.

The former generated chat-continuation restart mechanism is retired and
archived as a bad idea. Continuity comes from direct repository inspection,
temporary full-repository ZIP review, and later MCP-backed state.

Career Intelligence daily operation is local-runtime-first:
`python -m src.career_intelligence.daily` refreshes the Silver-backed career
radar under `jobs/results/` and `.runtime/career_intelligence/`. The Product V1
Control Center reads those files as an additional lens and writes only
operator-state changes to `.runtime/career_intelligence/operator_state.json`.
Those writes are intentionally separate from Product V1 ranking, connector
operation, application drafting and application submission.
Freshness shown in the Control Center prefers employer `publication_date`, uses
`first_seen_at` only as a labelled fallback, keeps `last_seen_at` separate, and
applies any age penalty only to the Career Intelligence lens.

Lingjia's source strategy lives in `config/career_source_strategy.yaml` and is
safe to review as configuration. It may surface connector gaps and target-source
priorities in the Control Center, but it is not an activation queue. Any source
candidate creation, connector implementation, final approval, active profile or
ingestion remains governed by the existing bounded source lifecycle.

Adaptive source decisions live in
`.runtime/career_intelligence/adaptive_source_state.json`. The file is local,
gitignored and atomically written by the Control Center action endpoint. Removing
it intentionally resets adaptive candidate decisions to `UNREVIEWED`; malformed
state fails closed instead of being overwritten. Adaptive decisions are promotion
overlays only and must not be treated as connector approval, activation,
registration, crawling, ingestion or Product V1 ranking authority.

Broad market discovery uses
`python -m src.career_intelligence.market_discovery doctor` and
`python -m src.career_intelligence.market_discovery run-daily`. Apply pending
database migrations before running it so the V2.4 StepStone and Bundesagentur
broad sensor profiles exist. The doctor reports source career priority,
implementation status, active-profile readiness and live-fetch evidence; a
blocked high-priority source must be fixed through the normal connector/source
lifecycle, not marked live in configuration.

Merge blocks must derive the PR number automatically from the current feature
branch; they must not require manual `<PR_NUMBER>` replacement.

## Failure and retry governance

There is **no global fixed attempt-count ceiling** for implementation, runtime,
infrastructure or recovery work. In particular, an old issue-local statement
such as "maximum three implementation attempts" is not current project
governance unless a current governance document explicitly reinstates it.

Retries are evidence-driven:

- classify the observed failure family and preserve its exact evidence;
- do not repeat an unchanged action against an unchanged unresolved failure
  merely to increase an attempt counter;
- retry when new evidence changes a relevant precondition, the failure was an
  independently resolved infrastructure incident, or the implementation or
  diagnostic approach materially changes;
- when evidence shows an approach itself is exhausted or unsafe, change the
  approach or bind a specific technical boundary rather than relying on a
  numeric retry limit;
- stop only at a real external operational, governance/operator, technical or
  demonstrated context boundary.

Attempt counts may remain useful diagnostic history, but they do not create a
stop condition by themselves. Historical issues and comments remain evidence of
what happened at that time; they do not override this current-truth rule.

## Repository-backed re-entry contract

Re-entry is not a chat handover and must not recreate the retired restart
mechanism. It is a bounded continuation from durable repository, PR, CI and
runtime truth after an external operational outage, governance/operator gate,
technical boundary or demonstrated context boundary.

### Target identity preflight

Before any freeze record, handover, issue, PR, runtime observation or next
action can supply continuation authority, authenticate the execution target
independently from live GitHub repository metadata.

- Machine-readable identity authority:
  `docs/current/REPOSITORY-IDENTITY.json`.
- The Pipeline execution target is immutable GitHub repository ID `1230805345`.
- `job-pipeline-runtime` is a related runtime/evidence authority source, not the
  Pipeline mutation target.
- A repository-ID mismatch fails closed as
  `REENTRY_CONTRACT_TARGET_MISMATCH` or
  `RELATED_REPOSITORY_NOT_EXECUTION_TARGET`.
- A changed repository name with the same immutable ID is
  `REPOSITORY_NAME_DRIFT`; it requires contract maintenance but is not evidence
  that execution moved to another repository.
- Filesystem location, project-name similarity, chat context, a freeze record,
  or authority supplied by a related repository cannot establish target
  identity by themselves.

Only after `IDENTITY_VERIFIED` may the repository-backed re-entry sequence below
supply project-state authority.

### Freeze record at every bounded stop

The active PR or issue must contain one explicit re-entry record with:

- repository and canonical `main` SHA;
- active branch, exact head SHA, issue and PR number;
- required CI run IDs and a per-job result matrix;
- completed implementation and validation evidence that must not be repeated;
- the classified stop reason: external operational, governance/operator,
  technical or context boundary;
- all side effects that remain prohibited;
- one exact next safe action and its preconditions.

The record is evidence, not authority over newer repository truth.

### Technical interruption checkpoint

A chat/context timeout, connector/tool failure, transient transport error or
similar execution interruption is **not** evidence of a product or runtime
failure by itself. It must not trigger replay, provider calls, state mutation or
an attempt-count increment merely to reconstruct a prior chat narrative.

Before starting the next material slice after such an interruption:

1. re-authenticate the immutable repository identity plus the exact live
   Pipeline `main` commit SHA and every related runtime/evidence repository SHA;
2. re-read the active issue/PR freeze and the newest durable runtime evidence;
3. explicitly reconcile any disagreement between prior chat/intermediate
   summaries and live repository/runtime truth, including commit-vs-tree SHA,
   candidate set, queue state and already-completed side effects;
4. persist a corrected active-issue freeze when the interruption exposed drift,
   ambiguity or stale continuation data; and
5. resume only from the newest legal durable state, preserving completed work
   and leaving unrelated or operator-bound work untouched.

Technical interruption recovery therefore restores **continuation context**, not
business state. Repository/runtime evidence always wins over a chat handover.

### Re-entry sequence

1. Inspect the repository, current `main`, branch head, PR state, review threads,
   required checks and the external dependency that caused the stop.
2. Compare live truth with the freeze record and classify drift:
   `no_drift`, `main_drift`, `head_drift`, `pr_drift`, `ci_drift` or
   `runtime_truth_drift`.
3. Preserve completed evidence only when it belongs to the unchanged head SHA.
   Do not repeat successful jobs or product mutations merely to recreate a
   previous narrative.
4. When the head is unchanged and failure was infrastructure-only, rerun only
   the missing, cancelled or infrastructure-failed job after the external
   incident is resolved.
5. When the head changed, old CI is no longer merge authority: run the complete
   required CI suite on the new head. When `main` changed, re-check
   mergeability, resolve drift safely and then run complete required CI.
6. Before any product-side continuation, inspect database and audit truth first.
   Never activate a source, register a connector, ingest data or replay another
   mutation as a re-entry shortcut.
7. Merge only when every required check is green for the exact current head.
   After merge, verify canonical `main`, the merge SHA, post-merge CI and issue
   closure.

A re-entry record may identify the next safe action, but it never loosens a
gate, converts unknown state to success or authorizes a side effect.
