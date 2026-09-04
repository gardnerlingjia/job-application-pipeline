"""MOIA live-source activation and daily flow for Career Intelligence V2.3."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import psycopg
from psycopg.rows import dict_row

from src.config import get_database_config


MOIA_COMPANY_KEY = "moia"
MOIA_COMPANY_NAME = "MOIA"
MOIA_SOURCE_NAME = "greenhouse:moia"
MOIA_PROFILE_NAME = "moia_greenhouse_lingjia_daily"
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
    preflight = load_moia_activation_preflight(conn)
    if not preflight.activation_allowed or preflight.candidate_id is None:
        raise RuntimeError(f"MOIA activation blocked: {preflight.status}")

    with conn.cursor(row_factory=dict_row) as cur:
        evidence = {
            "source_name": MOIA_SOURCE_NAME,
            "profile_name": MOIA_PROFILE_NAME,
            "boundary": {
                "source_activation_allowed": True,
                "bronze_persistence_allowed": False,
                "first_ingestion_automatic": False,
                "recurring_ingestion_enabled": False,
                "scheduler_change_allowed": False,
                "ranking_mutation_allowed": False,
                "application_actions_allowed": False,
            },
        }
        cur.execute(
            """
            INSERT INTO search_profiles (
                profile_name,
                source_name,
                search_location,
                search_radius_km,
                offer_type,
                page_size,
                is_active,
                recurring_ingestion_enabled
            ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, FALSE)
            RETURNING id, profile_name, source_name, is_active, recurring_ingestion_enabled;
            """,
            (
                MOIA_PROFILE_NAME,
                MOIA_SOURCE_NAME,
                MOIA_SEARCH_LOCATION,
                MOIA_SEARCH_RADIUS_KM,
                1,
                MOIA_PAGE_SIZE,
            ),
        )
        profile = dict(cur.fetchone())

        for term in MOIA_SEARCH_TERMS:
            cur.execute(
                """
                INSERT INTO search_terms (search_profile_id, search_term, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (search_profile_id, search_term) DO NOTHING;
                """,
                (profile["id"], term),
            )

        cur.execute(
            """
            INSERT INTO employer_origin_candidate_gate_reviews (
                candidate_id,
                gate_name,
                gate_order,
                gate_status,
                decision,
                is_hard_gate,
                stop_reason,
                evidence,
                reviewed_by
            )
            VALUES (
                %s,
                'controlled_activation_gate',
                13,
                'passed',
                'passed',
                TRUE,
                NULL,
                %s::jsonb,
                'career_intelligence_v2_3'
            )
            ON CONFLICT (candidate_id, gate_name)
            DO UPDATE SET
                gate_status = EXCLUDED.gate_status,
                decision = EXCLUDED.decision,
                evidence = EXCLUDED.evidence,
                reviewed_by = EXCLUDED.reviewed_by,
                updated_at = NOW();
            """,
            (
                preflight.candidate_id,
                json.dumps(evidence, sort_keys=True),
            ),
        )
        cur.execute(
            """
            UPDATE employer_origin_source_candidates
            SET status = 'active_controlled',
                source_target_candidate = %s,
                updated_at = NOW()
            WHERE id = %s;
            """,
            (MOIA_BOARD_TOKEN, preflight.candidate_id),
        )

    return {
        "status": "activated",
        "profile": profile,
        "source_name": MOIA_SOURCE_NAME,
        "search_terms": list(MOIA_SEARCH_TERMS),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MOIA Greenhouse activation preflight or daily live-source flow."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight", help="Show activation gate status without writes.")
    activate = subcommands.add_parser("activate", help="Create the active MOIA profile.")
    activate.add_argument("--apply", action="store_true", help="Required to write activation.")
    subcommands.add_parser("run-daily", help="Run ingestion, Silver, and Career daily refresh.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run-daily":
        return run_moia_daily_flow()

    with psycopg.connect(**get_database_config()) as conn:
        if args.command == "preflight":
            preflight = load_moia_activation_preflight(conn)
            conn.rollback()
            print(f"MOIA source: {MOIA_SOURCE_NAME}")
            print(f"status: {preflight.status}")
            print(f"candidate_id: {preflight.candidate_id}")
            print(f"connector_validation_passed: {preflight.connector_validation_passed}")
            print(f"final_approval_passed: {preflight.final_approval_passed}")
            print(f"active_profile_exists: {preflight.active_profile_exists}")
            return 0 if preflight.activation_allowed else 1

        if not args.apply:
            conn.rollback()
            print("MOIA activation requires --apply and passed source gates.")
            return 2
        result = apply_moia_activation(conn)
        conn.commit()
        print(f"MOIA activated as {result['profile']['profile_name']}")
        print("Next: python -m src.career_intelligence.moia_live_source run-daily")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
