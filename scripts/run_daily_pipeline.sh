#!/usr/bin/env bash

set -uo pipefail

RCC_REPOSITORY_ID="1230805345"
RCC_REPOSITORY="jenshaberle-dotcom/job-application-pipeline"
RCC_RUNNER_NAME="${RCC_RUNTIME_RUNNER_NAME:-job-pipeline-runtime-linux}"
RCC_CONTEXT_FILE="${RCC_RUNTIME_CONTEXT_FILE:-$HOME/.config/DeepOceanInfrastructure/RCC/runtime-contexts/${RCC_REPOSITORY_ID}-${RCC_RUNNER_NAME}.json}"
LOG_DIR="$HOME/job-pipeline-logs"
LOCK_DIR="/tmp/job-pipeline-daily.lock"
DB_READY_MAX_ATTEMPTS="${DB_READY_MAX_ATTEMPTS:-30}"
DB_READY_SLEEP_SECONDS="${DB_READY_SLEEP_SECONDS:-10}"

mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/daily_pipeline_$TIMESTAMP.log"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" | tee -a "$LOG_FILE"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "ERROR another daily pipeline run appears to be active: $LOCK_DIR"
  exit 1
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

log "START daily job pipeline"
log "rcc_runtime_context=$RCC_CONTEXT_FILE"

if [ ! -f "$RCC_CONTEXT_FILE" ]; then
  log "ERROR RCC runtime context missing: RUNTIME_CONTEXT_NOT_REGISTERED"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  log "ERROR python3 bootstrap unavailable for RCC runtime-context parsing"
  exit 1
fi

CONTEXT_OUTPUT="$(python3 - "$RCC_CONTEXT_FILE" "$RCC_REPOSITORY_ID" "$RCC_REPOSITORY" "$RCC_RUNNER_NAME" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import PurePosixPath
import sys

context_path, repository_id, repository, runner_name = sys.argv[1:]

try:
    with open(context_path, encoding="utf-8") as handle:
        context = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"RUNTIME_CONTEXT_STALE: projection unreadable: {exc}")

if context.get("RepositoryId") != int(repository_id):
    raise SystemExit("RUNTIME_REPOSITORY_ID_MISMATCH")
if context.get("Repository") != repository:
    raise SystemExit("RUNTIME_REPOSITORY_ID_MISMATCH")
if context.get("RunnerName") != runner_name:
    raise SystemExit("RUNTIME_CONTEXT_STALE: runner mismatch")
if context.get("Platform") != "linux-wsl":
    raise SystemExit("RUNTIME_CONTEXT_STALE: platform mismatch")
if context.get("Status") != "PASS" or context.get("PrimaryFailure") not in (None, ""):
    raise SystemExit(
        f"RUNTIME_CONTEXT_STALE: status={context.get('Status')} failure={context.get('PrimaryFailure')}"
    )

checks = {
    item.get("Id"): item.get("Status")
    for item in context.get("Checks", [])
    if isinstance(item, dict)
}
required_checks = {
    "repository_identity",
    "checkout",
    "checkout_repository",
    "env_file",
    "env_keys",
    "interpreter",
    "interpreter_probe",
    "capability:postgresql",
}
failed = sorted(check for check in required_checks if checks.get(check) != "PASS")
if failed:
    raise SystemExit("RUNTIME_CONTEXT_STALE: required checks not PASS: " + ",".join(failed))

checkout = context.get("CheckoutRoot")
interpreter = context.get("Interpreter")
env_file = context.get("EnvFile")
projection_path = context.get("ProjectionPath")
for label, value in (
    ("checkout", checkout),
    ("interpreter", interpreter),
    ("env_file", env_file),
):
    if not isinstance(value, str) or not value.startswith("/") or "\n" in value or "\0" in value:
        raise SystemExit(f"RUNTIME_CONTEXT_STALE: invalid {label} path")

checkout_path = PurePosixPath(checkout)
if checkout_path not in PurePosixPath(interpreter).parents:
    raise SystemExit("RUNTIME_CONTEXT_STALE: interpreter is outside registered checkout")
if checkout_path not in PurePosixPath(env_file).parents:
    raise SystemExit("RUNTIME_CONTEXT_STALE: env file is outside registered checkout")
if projection_path and os.path.normpath(projection_path) != os.path.normpath(context_path):
    raise SystemExit("RUNTIME_CONTEXT_STALE: projection path mismatch")

print(checkout)
print(interpreter)
PY
)" || {
  log "ERROR RCC runtime context rejected"
  exit 1
}

CONTEXT_LINE_1=""
CONTEXT_LINE_2=""
CONTEXT_LINE_3=""
{
  IFS= read -r CONTEXT_LINE_1 || true
  IFS= read -r CONTEXT_LINE_2 || true
  IFS= read -r CONTEXT_LINE_3 || true
} <<< "$CONTEXT_OUTPUT"
if [ -z "$CONTEXT_LINE_1" ] || [ -z "$CONTEXT_LINE_2" ] || [ -n "$CONTEXT_LINE_3" ]; then
  log "ERROR RCC runtime context produced an invalid consumer projection"
  exit 1
fi

PROJECT_DIR="$CONTEXT_LINE_1"
RUNTIME_PYTHON="$CONTEXT_LINE_2"

if [ ! -d "$PROJECT_DIR" ]; then
  log "ERROR RCC checkout unavailable: $PROJECT_DIR"
  exit 1
fi
if [ ! -x "$RUNTIME_PYTHON" ]; then
  log "ERROR RCC interpreter unavailable or not executable: $RUNTIME_PYTHON"
  exit 1
fi

log "project_dir=$PROJECT_DIR"
log "runtime_python=$RUNTIME_PYTHON"

cd "$PROJECT_DIR" || {
  log "ERROR RCC project directory unavailable"
  exit 1
}

DB_READY_EXIT=1
for ((attempt = 1; attempt <= DB_READY_MAX_ATTEMPTS; attempt++)); do
  log "Checking configured Postgres dependency attempt=$attempt/$DB_READY_MAX_ATTEMPTS"
  "$RUNTIME_PYTHON" - <<'PY' 2>&1 | tee -a "$LOG_FILE"
from src.config import get_database_config
import psycopg

config = get_database_config()
with psycopg.connect(**config, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
print("Postgres configured connection ready")
PY
  DB_READY_EXIT=${PIPESTATUS[0]}
  if [ "$DB_READY_EXIT" -eq 0 ]; then
    break
  fi
  if [ "$attempt" -lt "$DB_READY_MAX_ATTEMPTS" ]; then
    sleep "$DB_READY_SLEEP_SECONDS"
  fi
done

if [ "$DB_READY_EXIT" -ne 0 ]; then
  log "FAILED configured Postgres dependency unavailable after $DB_READY_MAX_ATTEMPTS attempts exit_code=$DB_READY_EXIT"
  exit "$DB_READY_EXIT"
fi

ORIGIN_EXIT=0
SENSOR_EXIT=0
SILVER_EXIT=0
SNAPSHOT_EXIT=0

log "Running employer-origin Bronze ingestion"
"$RUNTIME_PYTHON" -m src.ingest_jobs --role employer_origin --log-level INFO 2>&1 | tee -a "$LOG_FILE"
ORIGIN_EXIT=${PIPESTATUS[0]}
if [ "$ORIGIN_EXIT" -ne 0 ]; then
  log "WARN employer-origin ingestion degraded exit_code=$ORIGIN_EXIT; continuing so successful origin observations can reach Silver"
else
  log "Employer-origin ingestion completed"
fi

log "Running sensor Bronze ingestion"
"$RUNTIME_PYTHON" -m src.ingest_jobs --role sensor --log-level INFO 2>&1 | tee -a "$LOG_FILE"
SENSOR_EXIT=${PIPESTATUS[0]}
if [ "$SENSOR_EXIT" -ne 0 ]; then
  log "WARN sensor ingestion degraded exit_code=$SENSOR_EXIT; authoritative origin freshness will continue"
else
  log "Sensor ingestion completed"
fi

log "Running Silver normalization after all successful Bronze observations"
"$RUNTIME_PYTHON" -m src.run_silver_jobs 2>&1 | tee -a "$LOG_FILE"
SILVER_EXIT=${PIPESTATUS[0]}
if [ "$SILVER_EXIT" -ne 0 ]; then
  log "ERROR Silver normalization failed exit_code=$SILVER_EXIT"
else
  log "Silver normalization completed"
fi

if [ "$SILVER_EXIT" -eq 0 ]; then
  log "Creating source value snapshot"
  "$RUNTIME_PYTHON" -m scripts.create_source_value_snapshot --reason scheduled_daily 2>&1 | tee -a "$LOG_FILE"
  SNAPSHOT_EXIT=${PIPESTATUS[0]}
  if [ "$SNAPSHOT_EXIT" -ne 0 ]; then
    log "ERROR source value snapshot failed exit_code=$SNAPSHOT_EXIT"
  fi
else
  SNAPSHOT_EXIT=1
  log "SKIP source value snapshot because Silver normalization failed"
fi

log "component_status origin=$ORIGIN_EXIT sensor=$SENSOR_EXIT silver=$SILVER_EXIT snapshot=$SNAPSHOT_EXIT"

# Employer-origin freshness and Silver are the authoritative daily core. A sensor
# outage remains explicit evidence in ingestion_runs/logs but cannot suppress a
# successful origin observation from reaching Silver/current lifecycle truth.
if [ "$ORIGIN_EXIT" -ne 0 ] || [ "$SILVER_EXIT" -ne 0 ] || [ "$SNAPSHOT_EXIT" -ne 0 ]; then
  log "END daily job pipeline FAILED_AUTHORITATIVE_CORE"
  exit 1
fi

if [ "$SENSOR_EXIT" -ne 0 ]; then
  log "END daily job pipeline OK_WITH_SENSOR_DEGRADATION"
  exit 0
fi

log "END daily job pipeline OK"
exit 0
