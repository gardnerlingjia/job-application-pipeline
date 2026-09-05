"""MOIA live-source activation and daily flow for Career Intelligence V2.3."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import psycopg
from psycopg.rows import dict_row

from scripts import run_employer_origin_connector_validation_agent as validation_agent
from scripts import run_employer_origin_final_approval_gate_agent as approval_agent
from scripts.run_validated_connector_controlled_activation import (
    apply_activation as apply_controlled_activation,
)
from scripts.run_validated_connector_controlled_activation import (
    build_manifest as build_controlled_activation_manifest,
)
from scripts.run_validated_connector_controlled_activation import (
    build_preflight as build_controlled_activation_preflight,
)
from src.config import get_database_config
from src.search_intelligence.controlled_activation import controlled_profile_name


MOIA_COMPANY_KEY = "moia"
MOIA_COMPANY_NAME = "MOIA"
MOIA_SOURCE_NAME = "greenhouse:moia"
MOIA_PROFILE_NAME = controlled_profile_name(MOIA_COMPANY_KEY)
MOIA_BOARD_TOKEN = "moia"
MOIA_SEARCH_LOCATION = "Berlin"
MOIA_SEARCH_RADIUS_KM = 50
MOIA_PAGE_SIZE = 25
MOIA_SEARCH_TERMS = (
    "autonomous mobility",
    "robotics",
    "technical program",
    "program manager",
    "product manager",
    "product operations",
    "AI",
    "data",
    "mobility",
)
REQUIRED_SCHEMA_TABLES = (
    "search_profiles",
    "search_terms",
    "raw_jobs",
    "silver_jobs",
    "employer_origin_source_candidates",
    "employer_origin_candidate_gate_reviews",
)
MIGRATION_COMMAND = ".venv/bin/python scripts/apply_db_migrations.py --apply --applied-by local"
START_DATABASE_COMMAND = "docker compose up -d postgres"


class OperationalBlocker(RuntimeError):
    def __init__(self, message: str, *, next_command: str | None = None) -> None:
        super().__init__(message)
        self.next_command = next_command


@dataclass(frozen=True)
class MoiaActivationPreflight:
    candidate_id: int | None
    candidate_status: str | None
    connector_validation_passed: bool
    final_approval_passed: bool
    active_profile_exists: bool

    @property
    def activation_allowed(self) -> bool:
        return bool(
            self.candidate_id
            and self.connector_validation_passed
            and self.final_approval_passed
            and not self.active_profile_exists
        )

    @property
    def daily_allowed(self) -> bool:
        return bool(
            self.candidate_id
            and self.connector_validation_passed
            and self.final_approval_passed
            and self.active_profile_exists
        )

    @property
    def status(self) -> str:
        if self.candidate_id is None:
            return "blocked_missing_source_candidate"
        if not self.connector_validation_passed:
            return "blocked_missing_connector_validation"
        if not self.final_approval_passed:
            return "blocked_missing_final_approval"
        if self.active_profile_exists:
            return "already_active"
        return "activation_ready"

    @property
    def next_recommended_command(self) -> str:
        prefix = "python -m src.career_intelligence.moia_live_source"
        if self.candidate_id is None:
            return "register the MOIA source candidate, then rerun preflight"
        if not self.connector_validation_passed:
            return f"{prefix} validate --dry-run"
        if not self.final_approval_passed:
            return f"{prefix} approve --reviewed-by lingjia"
        if not self.active_profile_exists:
            return f"{prefix} activate"
        return f"{prefix} run-daily"


def _gate_passed(
    conn: psycopg.Connection[Any],
    *,
    candidate_id: int,
    gate_name: str,
    decision: str,
) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT gate_status, decision
            FROM employer_origin_candidate_gate_reviews
            WHERE candidate_id = %s
              AND gate_name = %s
            ORDER BY updated_at DESC
            LIMIT 1;
            """,
            (candidate_id, gate_name),
        )
        row = cur.fetchone()
    return bool(row and row["gate_status"] == "passed" and row["decision"] == decision)


def connect_database() -> psycopg.Connection[Any]:
    try:
        return psycopg.connect(**get_database_config())
    except psycopg.OperationalError as exc:
        raise OperationalBlocker(
            f"Database unavailable. Start with: {START_DATABASE_COMMAND}",
            next_command=START_DATABASE_COMMAND,
        ) from exc


def missing_required_schema_tables(conn: psycopg.Connection[Any]) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(REQUIRED_SCHEMA_TABLES),),
        )
        existing = {str(row["table_name"]) for row in cur.fetchall()}
    return [table for table in REQUIRED_SCHEMA_TABLES if table not in existing]


def ensure_required_schema(conn: psycopg.Connection[Any]) -> None:
    missing = missing_required_schema_tables(conn)
    if missing:
        raise OperationalBlocker(
            "Schema not initialized. Missing required table(s): " + ", ".join(missing),
            next_command=MIGRATION_COMMAND,
        )


def ensure_operational_database() -> None:
    with connect_database() as conn:
        ensure_required_schema(conn)
        conn.rollback()


def load_migration_status(conn: psycopg.Connection[Any]) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') AS relation")
        relation = cur.fetchone()
        if relation is None or relation["relation"] is None:
            return "BLOCKED: schema_migrations missing"
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE execution_status IN ('success', 'bootstrapped')) AS applied_count,
                count(*) FILTER (WHERE execution_status = 'failed') AS failed_count
            FROM schema_migrations
            """
        )
        row = cur.fetchone()
    return f"PASS: applied={int(row['applied_count'] or 0)} failed={int(row['failed_count'] or 0)}"


def load_moia_activation_preflight(conn: psycopg.Connection[Any]) -> MoiaActivationPreflight:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, status
            FROM employer_origin_source_candidates
            WHERE company_key = %s
              AND source_name_candidate = %s
            ORDER BY updated_at DESC, id DESC
            LIMIT 1;
            """,
            (MOIA_COMPANY_KEY, MOIA_SOURCE_NAME),
        )
        candidate = cur.fetchone()

        cur.execute(
            """
            SELECT 1
            FROM search_profiles
            WHERE profile_name = %s
              AND source_name = %s
              AND is_active = TRUE
            LIMIT 1;
            """,
            (MOIA_PROFILE_NAME, MOIA_SOURCE_NAME),
        )
        active_profile_exists = cur.fetchone() is not None

    if candidate is None:
        return MoiaActivationPreflight(
            candidate_id=None,
            candidate_status=None,
            connector_validation_passed=False,
            final_approval_passed=False,
            active_profile_exists=active_profile_exists,
        )

    candidate_id = int(candidate["id"])
    return MoiaActivationPreflight(
        candidate_id=candidate_id,
        candidate_status=str(candidate["status"]),
        connector_validation_passed=_gate_passed(
            conn,
            candidate_id=candidate_id,
            gate_name="connector_validation_gate",
            decision="ready_for_final_approval",
        ),
        final_approval_passed=_gate_passed(
            conn,
            candidate_id=candidate_id,
            gate_name="final_approval_gate",
            decision="approve_connector_registration",
        ),
        active_profile_exists=active_profile_exists,
    )


def apply_moia_activation(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    readiness, decision, policy = build_controlled_activation_preflight(
        conn=conn,
        company_key=MOIA_COMPANY_KEY,
    )
    if not decision.allowed:
        raise RuntimeError(f"MOIA activation blocked: {decision.status}: {decision.reason}")
    result = apply_controlled_activation(
        conn=conn,
        readiness=readiness,
        decision=decision,
        policy=policy,
    )
    return {
        "status": "activated",
        "profile": result["profile"],
        "source_name": MOIA_SOURCE_NAME,
        "search_terms": [result["next_commands"]["bounded_first_ingestion"]],
        "authorization_event": result["authorization_event"],
        "next_commands": build_moia_daily_commands(sys.executable),
        "boundary": {
            "connector_registration": False,
            "provider_requests": False,
            "ingestion_started": False,
            "product_v1_ranking_authority": False,
            "application_submission": False,
        },
    }


def build_moia_daily_commands(python_executable: str = sys.executable) -> list[list[str]]:
    return [
        [
            python_executable,
            "-m",
            "src.ingest_jobs",
            "--profile",
            MOIA_PROFILE_NAME,
        ],
        [
            python_executable,
            "-m",
            "src.run_silver_jobs",
            "--source",
            MOIA_SOURCE_NAME,
            "--limit",
            str(MOIA_PAGE_SIZE),
        ],
        [
            python_executable,
            "-m",
            "src.career_intelligence.daily",
            "--source",
            MOIA_SOURCE_NAME,
            "--limit",
            str(MOIA_PAGE_SIZE),
        ],
    ]


def run_moia_daily_flow(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str = sys.executable,
) -> int:
    for command in build_moia_daily_commands(python_executable):
        print("+ " + " ".join(command))
        completed = runner(command, check=False, text=True)
        if completed.returncode != 0:
            return int(completed.returncode)
    return 0


def run_moia_daily_if_activated(
    preflight: MoiaActivationPreflight,
    *,
    daily_runner: Callable[[], int] = run_moia_daily_flow,
) -> int:
    if not preflight.daily_allowed:
        print(f"MOIA run-daily blocked: {preflight.status}")
        print(f"Next: {preflight.next_recommended_command}")
        return 2
    return daily_runner()


def run_moia_validate(args: argparse.Namespace) -> int:
    ensure_operational_database()
    agent_args = argparse.Namespace(
        candidate_id=None,
        company_key=MOIA_COMPANY_KEY,
        reviewed_by=args.reviewed_by,
        dry_run=args.dry_run,
        no_pytest=args.no_pytest,
        print_json=args.print_json,
    )
    exit_code = validation_agent.run_agent(agent_args)
    print(f"Next: {next_command_after_validation(exit_code)}")
    return exit_code


def next_command_after_validation(exit_code: int) -> str:
    if exit_code == 0:
        return "python -m src.career_intelligence.moia_live_source approve --reviewed-by lingjia"
    return "fix connector validation blockers, then rerun validate --dry-run"


def run_moia_approve(args: argparse.Namespace) -> int:
    ensure_operational_database()
    agent_args = argparse.Namespace(
        candidate_id=None,
        company_key=MOIA_COMPANY_KEY,
        approval_token=args.approval_token,
        approved_by=args.reviewed_by,
        dry_run=args.dry_run,
        print_json=args.print_json,
    )
    exit_code = approval_agent.run_agent(agent_args)
    print(f"Next: {next_command_after_approval(exit_code)}")
    return exit_code


def next_command_after_approval(exit_code: int) -> str:
    if exit_code == 0:
        return "python -m src.career_intelligence.moia_live_source activate"
    return "complete connector validation and explicit approval requirements, then rerun approve"


def print_moia_preflight(preflight: MoiaActivationPreflight) -> None:
    print(f"MOIA source: {MOIA_SOURCE_NAME}")
    print(f"status: {preflight.status}")
    print(f"candidate_id: {preflight.candidate_id}")
    print(f"connector_validation_passed: {preflight.connector_validation_passed}")
    print(f"final_approval_passed: {preflight.final_approval_passed}")
    print(f"active_profile_exists: {preflight.active_profile_exists}")
    print(f"next: {preflight.next_recommended_command}")


def run_moia_doctor() -> int:
    print("MOIA live-source doctor")
    print(f"interpreter: {sys.executable}")
    print(f"virtualenv: {'PASS' if sys.prefix != sys.base_prefix else 'BLOCKED'}")

    try:
        with connect_database() as conn:
            print("database: PASS")
            missing = missing_required_schema_tables(conn)
            if missing:
                print("schema: BLOCKED")
                print("missing_tables: " + ", ".join(missing))
                print(f"migration_status: {load_migration_status(conn)}")
                print(f"next: {MIGRATION_COMMAND}")
                conn.rollback()
                return 2

            print("schema: PASS")
            print(f"migration_status: {load_migration_status(conn)}")
            preflight = load_moia_activation_preflight(conn)
            conn.rollback()
    except OperationalBlocker as exc:
        print("database: BLOCKED")
        print(str(exc))
        if exc.next_command:
            print(f"next: {exc.next_command}")
        return 2

    print(f"moia_candidate: {'PASS' if preflight.candidate_id else 'BLOCKED'}")
    print(f"candidate_id: {preflight.candidate_id}")
    print(f"connector_validation_gate: {'PASS' if preflight.connector_validation_passed else 'BLOCKED'}")
    print(f"final_approval_gate: {'PASS' if preflight.final_approval_passed else 'BLOCKED'}")
    print(f"active_profile: {'PASS' if preflight.active_profile_exists else 'BLOCKED'}")
    print(f"next: {preflight.next_recommended_command}")
    return 0 if preflight.daily_allowed else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MOIA Greenhouse activation preflight or daily live-source flow."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="Check local DB, schema, gates, and MOIA activation.")
    subcommands.add_parser("preflight", help="Show activation gate status without writes.")
    validate = subcommands.add_parser("validate", help="Run the canonical connector validation gate.")
    validate.add_argument("--reviewed-by", default="agent")
    validate.add_argument("--dry-run", action="store_true")
    validate.add_argument("--no-pytest", action="store_true")
    validate.add_argument("--print-json", action="store_true")
    approve = subcommands.add_parser("approve", help="Run the canonical final approval gate.")
    approve.add_argument("--reviewed-by", default="lingjia")
    approve.add_argument("--approval-token")
    approve.add_argument("--dry-run", action="store_true")
    approve.add_argument("--print-json", action="store_true")
    activate = subcommands.add_parser("activate", help="Create the active MOIA profile.")
    activate.add_argument("--dry-run", action="store_true", help="Check activation readiness without writing.")
    subcommands.add_parser("run-daily", help="Run ingestion, Silver, and Career daily refresh.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return run_moia_doctor()
        if args.command == "validate":
            return run_moia_validate(args)
        if args.command == "approve":
            return run_moia_approve(args)

        with connect_database() as conn:
            ensure_required_schema(conn)
            if args.command == "preflight":
                preflight = load_moia_activation_preflight(conn)
                conn.rollback()
                print_moia_preflight(preflight)
                return 0 if preflight.activation_allowed or preflight.daily_allowed else 1

            if args.command == "run-daily":
                preflight = load_moia_activation_preflight(conn)
                conn.rollback()
                return run_moia_daily_if_activated(preflight)

            if args.dry_run:
                readiness, decision, policy = build_controlled_activation_preflight(
                    conn=conn,
                    company_key=MOIA_COMPANY_KEY,
                )
                manifest = build_controlled_activation_manifest(
                    readiness=readiness,
                    decision=decision,
                    policy=policy,
                    apply_requested=False,
                    applied=None,
                )
                conn.rollback()
                print("MOIA activation dry run")
                print(f"status: {manifest['decision']['status']}")
                print(f"reason: {manifest['decision']['reason']}")
                print(f"next: {preflight_next_from_activation_status(manifest['decision']['status'])}")
                return 0 if decision.allowed else 2

            result = apply_moia_activation(conn)
            conn.commit()
            print(f"MOIA activated as {result['profile']['profile_name']}")
            print("Next: python -m src.career_intelligence.moia_live_source run-daily")
            return 0
    except OperationalBlocker as exc:
        print(str(exc))
        if exc.next_command:
            print(f"next: {exc.next_command}")
        return 2
    except RuntimeError as exc:
        print(str(exc))
        return 2
    except psycopg.Error as exc:
        print(f"Database operation failed: {exc.__class__.__name__}")
        print(f"next: python -m src.career_intelligence.moia_live_source doctor")
        return 2

    raise AssertionError(f"Unhandled command: {args.command}")


def preflight_next_from_activation_status(status: str) -> str:
    if status == "controlled_activation_apply_ready":
        return "python -m src.career_intelligence.moia_live_source activate"
    if status == "controlled_activation_blocked_missing_validation":
        return "python -m src.career_intelligence.moia_live_source validate --dry-run"
    if status == "controlled_activation_blocked_missing_final_approval":
        return "python -m src.career_intelligence.moia_live_source approve --reviewed-by lingjia"
    return "resolve controlled activation blockers, then rerun activate --dry-run"


if __name__ == "__main__":
    raise SystemExit(main())
