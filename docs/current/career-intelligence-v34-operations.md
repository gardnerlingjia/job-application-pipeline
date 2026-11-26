# Career Intelligence V3.4 operational handover

Development is frozen. No new sources, scoring redesign or V3.5 work is authorized.
The 14-day operational observation period is 26 November–9 December 2026 inclusive;
review the accumulated logs on 10 December. Daily operation continues afterward.

## Production selection and rollback

The installed deployment selects `CAREER_INTELLIGENCE_STRATEGY=v3.4` in both
LaunchAgents. Omission or `v3.3` selects the retained V3.3 strategy. The strategy
artifact keeps its explicit-selection safety contract; production selection is a
deployment setting, not a rewrite of scores, evidence or historical assessments.
The dashboard supports explicit V3.3/V3.4 comparison. Read-only qualification never
writes WATCH/SKIP assessments or operator decisions.

An absence of PURSUE results is not an activation failure. Strong specialist gaps,
unverified availability and unknown working conditions must remain visible.
No hiring outcome or measured precision/recall improvement is claimed.

## Local deployment and scheduling

The production copy is under `$HOME/Library/Application Support/CareerIntelligence/runtime`.
Its parent is private to the user. This avoids the confirmed background startup
failure when launchd opened the environment under Documents. A private byte-identical
CV copy preserves the original content hash and provenance; no Files and Folders
permissions were broadened. The developer checkout remains separate.

LaunchAgents in `$HOME/Library/LaunchAgents`:

- `com.gardnerlingjia.career-intelligence.daily`: 08:15 system local time daily,
  plus a run when loaded or on login. Current system timezone: Europe/Berlin.
- `com.gardnerlingjia.career-intelligence.control-center`: loopback HTTP on port
  8781, starts on login and restarts after process exit.

The operational command is `python -m scripts.run_career_intelligence_operational`.
It uses the existing run lock, bounded provider adapters, persistent observations,
source monitoring and read-only qualification. It creates a private PostgreSQL dump
before retrieval. Database readiness is retried for a bounded interval after login.
A failed backup or missing approved evidence stops retrieval. Source failures yield
a nonzero/degraded result after available observations and qualification are retained.
No partial snapshot can confirm a removal; two complete absent snapshots remain required.
The existing Linux/WSL scheduler and unrelated upstream pipeline are unchanged.

Next normal calendar execution: **27 November 2026 at 08:15 Europe/Berlin**.
Control Center: **http://127.0.0.1:8781/**. Older developer servers are not production.

According to Apple's launchd documentation, a missed calendar job during sleep
runs on wake, with missed triggers coalesced. Power-off does not replay every missed
calendar event. Our RunAtLoad setting starts a fresh run on login after restart.
Nothing runs while powered off or logged out. Docker Desktop/PostgreSQL must become
available. Offline provider attempts use existing bounded retries, then log degraded
coverage; retained observations are still available. There is no promise of immediate
retry on network return; the next calendar/login run retries, or the operator may
kickstart the existing daily agent. Changing the Mac timezone changes the local schedule.

Reference: [Apple: Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).

## Observation and operator procedure

Use existing source-level database history, vacancy events, the Control Center and
`.runtime/career_intelligence/operations/latest.json` and `logs/daily_*.json`.
`market_intelligence.v34.json` is a generated report, never an authoritative input.
Do not add an analytics system. Review new/change events and PURSUE/CLARIFY evidence
in the existing dashboard. Check promising employer URLs directly before applying.
Record manual review effort and obvious false positives in the existing operator
note/history mechanism. A source timestamp change is not a verified description change;
unknown direct-employer availability and unrecorded manual effort remain unknown.
Inventory-wide recommendation counts must not be described as new recommendations.
This is ongoing local operation, not a claim that 14 days have already been observed.
Only confirmed operational defects may be corrected during the freeze.

## Backup and recovery

Private pre-release database dump, runtime/profile archive and worktree archive are
retained in the developer checkout under `.runtime/release-2026-11-26/`.
Daily database dumps are under the deployed runtime's
`.runtime/career_intelligence/operations/backups/`. These contain personal data:
do not upload them to GitHub or treat them as public release assets. They are local
backups on the same Mac, not an off-device disaster-recovery service.

For a strategy rollback, boot out the daily agent, change both installed plist
`EnvironmentVariables.CAREER_INTELLIGENCE_STRATEGY` values to `v3.3`, then reload the
Control Center agent. V3.3 remains available without deleting V3.4 observations.
The V3.4 operational runner intentionally refuses to run with V3.3 selected; leave
it disabled during rollback rather than silently running the wrong acquisition plan.

For recovery, disable both agents first. Restore code from the release tag into a
clean deployment, then restore the separately retained private profiles, approved
CV evidence, runtime/operator files and database configuration. Restore PostgreSQL
into a **new empty database** using the matching PostgreSQL 17 `pg_restore`, inspect
its tables and counts, then switch the private configuration to that database.
Never restore with destructive options into the live database without a separate
backup and an explicit recovery decision. Verify candidate content hashes and
operator/history counts before reloading services. Build the frontend if restoring
from Git: generated dist and node_modules are not published.

## Public release boundary

GitHub visibility remains public. The release is a clean snapshot based on remote
main, not a push of unpublished candidate-bearing local commits. Personal career,
capability, constraint and network profiles, CVs, approved/draft evidence, credentials,
private calibration snapshots, database contents and runtime outputs are excluded.
Candidate-specific historical reports are withheld or replaced with non-sensitive
section markers. Private source files and historical commits remain locally backed up.

The full operational test suite uses separately retained private deployment inputs;
those inputs are intentionally not reproducible from the public repository alone.
Historical calibration tests explicitly skip when their private snapshots are absent.
Other developers must supply their own approved private profiles, never another
candidate's evidence. No empty template is a production-approved competency profile.

## Remaining limitations

BA is bounded and can be partially unreliable. Successful queries do not establish
whole-market completeness. Filtered employer searches are not complete board
snapshots. Many BA list observations lack descriptions; conservative INSUFFICIENT
EVIDENCE judgments are expected. Employer availability, travel, working style and
business-unit outlook often require manual confirmation. Candidate-declared AI
projects remain supplementary and are not repository-verified or professional
enterprise production AI evidence. Login, local Docker, disk space and network
availability remain operational dependencies.

## Database hardening at release

The deployed PostgreSQL role no longer uses the public demonstration password.
Its replacement is retained only in private mode-600 environment/recovery files.
Compose now requires a private POSTGRES_PASSWORD and binds port 5432 only to
127.0.0.1. The existing persistent volume and vacancy counts were preserved.
Superseded development Control Centers were stopped; port 8781 is authoritative.
The historical E402 lint baseline remains unchanged at 34 findings. One redundant
f-string prefix was removed because the release CI correctness gate rejects F541;
this changes no behavior or assessment logic.

## Release validation scopes

The clean release snapshot passed 3,800 tests with the private deployment inputs
restored locally. Public-package validation without those inputs passed 3,181
tests and explicitly skipped 358 collected cases requiring private configuration;
private snapshot modules also skip when their separately retained files are absent.
This prevents CI from fabricating candidate data. Provider, persistence, geography
and deployment-selector regressions remain in the public checks. The release
passes the repository correctness lint gate with its unchanged E402 exception.
