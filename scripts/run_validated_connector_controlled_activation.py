from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from scripts.review_employer_origin_activation_readiness import (
    DEFAULT_LOCATION,
    DEFAULT_OFFER_TYPE,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RADIUS_KM,
    run_activation_readiness,
)
from src.config import get_database_config
from src.search_intelligence.connector_autonomy import (
    A1_POLICY_KEY,
    ConnectorAutonomyPolicy,
    policy_from_row,
)
from src.search_intelligence.controlled_activation import (
    ControlledActivationDecision,
    controlled_profile_name,
    decide_controlled_activation,
)


CONTROLLED_SEARCH_TERM = "*"
RECORDED_BY = "job_pipeline_agent"


def gate_passed(
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
            LIMIT 1
            """,
            (candidate_id, gate_name),
        )
        row = cur.fetchone()
    return bool(row and row["gate_status"] == "passed" and row["decision"] == decision)


def load_a1_policy(conn: psycopg.Connection[Any]) -> ConnectorAutonomyPolicy | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *
            FROM connector_autonomy_policies
            WHERE policy_key = %s
            """,
            (A1_POLICY_KEY,),
        )
        row = cur.fetchone()
    return policy_from_row(dict(row)) if row else None


def build_preflight(
    *,
    conn: psycopg.Connection[Any],
    company_key: str,
    profile_config: dict | None = None,
) -> tuple[dict[str, Any], ControlledActivationDecision, ConnectorAutonomyPolicy | None]:
    if company_key == 'waymo' and profile_config is None:
        raise ValueError('Waymo requires an explicit --profile-config; Hannover defaults prohibited')
    readiness = run_activation_readiness(
        conn=conn,
        candidate_id=None,
        company_key=company_key,
        output_dir=Path("docs/planning/active/source-candidates"),
        write=False,
        page_size=profile_config['page_size'] if profile_config else DEFAULT_PAGE_SIZE,
        **({'profile_config': profile_config} if profile_config else {}),
    )
    if profile_config:
        readiness['controlled_profile'] = profile_config
    candidate = readiness["candidate"]
    candidate_id = int(candidate["candidate_id"])
    validation_passed = gate_passed(
        conn,
        candidate_id=candidate_id,
        gate_name="connector_validation_gate",
        decision="ready_for_final_approval",
    )
    final_approval = gate_passed(
        conn,
        candidate_id=candidate_id,
        gate_name="final_approval_gate",
        decision="approve_connector_registration",
    )
    policy = load_a1_policy(conn)
    decision = decide_controlled_activation(
        connector_validation_passed=validation_passed,
        final_approval_passed=final_approval,
        candidate_status=str(candidate["status"]),
        active_profile_count=int(readiness["active_search_profile_count"]),
        activation_readiness=str(readiness["overall_readiness"]),
        policy=policy,
    )
    readiness["connector_validation_passed"] = validation_passed
    readiness["final_approval_passed"] = final_approval
    return readiness, decision, policy


def apply_activation(
    *,
    conn: psycopg.Connection[Any],
    readiness: dict[str, Any],
    decision: ControlledActivationDecision,
    policy: ConnectorAutonomyPolicy | None,
) -> dict[str, Any]:
    if not decision.allowed or policy is None:
        raise RuntimeError("Controlled activation apply requested without A1 authorization.")

    candidate = readiness["candidate"]
    candidate_id = int(candidate["candidate_id"])
    company_key = str(candidate["company_key"])
    source_name = str(candidate["source_name_candidate"])
    scope = readiness.get('controlled_profile')
    if company_key == 'waymo' and scope is None:
        raise ValueError('Explicit Waymo profile required')
    if scope and scope['source_name'] != source_name:
        raise ValueError('Controlled profile source mismatch')
    profile_name = scope['profile_name'] if scope else controlled_profile_name(company_key)
    terms = scope['search_terms'] if scope else [CONTROLLED_SEARCH_TERM]

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, source_name, is_active, recurring_ingestion_enabled
            FROM search_profiles
            WHERE profile_name = %s
            """,
            (profile_name,),
        )
        if cur.fetchone() is not None:
            raise RuntimeError(
                f"Controlled profile already exists and will not be overwritten: {profile_name}"
            )

        cur.execute(
            """
            INSERT INTO search_profiles (
                profile_name,
                source_name,
                search_term,
                search_location,
                search_radius_km,
                offer_type,
                page_size,
                is_active,
                recurring_ingestion_enabled
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, FALSE)
            RETURNING id, profile_name, source_name, is_active, recurring_ingestion_enabled
            """,
            (
                profile_name,
                source_name,
                terms[0],
                scope['search_location'] if scope else DEFAULT_LOCATION,
                scope['search_radius_km'] if scope else DEFAULT_RADIUS_KM,
                DEFAULT_OFFER_TYPE,
                scope["page_size"] if scope else DEFAULT_PAGE_SIZE,
            ),
        )
        profile = dict(cur.fetchone())

        for term in terms:
            cur.execute(
                """
                INSERT INTO search_terms (search_profile_id, search_term, is_active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (search_profile_id, search_term) DO NOTHING
                """,
                (profile["id"], term),
            )

        cur.execute(
            """
            UPDATE employer_origin_source_candidates
            SET status = 'active_controlled',
                updated_at = NOW()
            WHERE id = %s
              AND status <> 'active_controlled'
            """,
            (candidate_id,),
        )

        evidence = {
            "s7u_overall_readiness": readiness["overall_readiness"],
            "s7u_candidate_count": readiness["candidate_count"],
            "s7u_evaluable_candidate_count": readiness["evaluable_candidate_count"],
            "s7u_non_job_preview_count": readiness["non_job_preview_count"],
            "profile_name": profile_name,
            "source_name": source_name,
            "page_size": DEFAULT_PAGE_SIZE,
            "search_term": terms[0],
            "controlled_profile": scope,
            "recurring_ingestion_enabled": False,
            "boundary": {
                "controlled_source_activation": True,
                "bounded_first_ingestion_allowed": True,
                "recurring_ingestion_allowed": False,
                "scheduler_change_allowed": False,
                "provider_requests_allowed": False,
                "ranking_mutation_allowed": False,
                "application_actions_allowed": False,
            },
        }
        cur.execute(
            """
            INSERT INTO connector_autonomy_authorization_events (
                candidate_id,
                source_name_candidate,
                action,
                decision,
                authorization_mode,
                policy_key,
                policy_version,
                evidence,
                recorded_by
            ) VALUES (%s, %s, 'controlled_source_activation', 'allowed', %s, %s, %s, %s::jsonb, %s)
            RETURNING id, created_at
            """,
            (
                candidate_id,
                source_name,
                "standing_a1_validated_connector_authorization",
                policy.policy_key,
                policy.policy_version,
                json.dumps(evidence, sort_keys=True),
                RECORDED_BY,
            ),
        )
        event = dict(cur.fetchone())

    return {
        "profile": profile,
        "authorization_event": event,
        "next_commands": {
            "bounded_first_ingestion": (
                f"python -m src.ingest_jobs --profile {profile_name}"
            ),
            "source_bounded_silver": (
                f"python -m src.run_silver_jobs --source {source_name} --limit {DEFAULT_PAGE_SIZE}"
            ),
        },
    }


def build_manifest(
    *,
    readiness: dict[str, Any],
    decision: ControlledActivationDecision,
    policy: ConnectorAutonomyPolicy | None,
    apply_requested: bool,
    applied: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = readiness["candidate"]
    return {
        "agent": "validated_connector_controlled_activation",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "candidate": candidate,
        "controlled_profile": readiness.get("controlled_profile"),
        "fresh_s7u": {
            "overall_readiness": readiness["overall_readiness"],
            "candidate_count": readiness["candidate_count"],
            "evaluable_candidate_count": readiness["evaluable_candidate_count"],
            "non_job_preview_count": readiness["non_job_preview_count"],
            "active_search_profile_count": readiness["active_search_profile_count"],
        },
        "connector_validation_passed": readiness["connector_validation_passed"],
        "final_approval_passed": readiness["final_approval_passed"],
        "a1_policy": {
            "present": policy is not None,
            "policy_key": policy.policy_key if policy else None,
            "policy_version": policy.policy_version if policy else None,
            "status": policy.status if policy else None,
        },
        "decision": {
            "allowed": decision.allowed,
            "status": decision.status,
            "reason": decision.reason,
        },
        "apply_requested": apply_requested,
        "applied": applied,
        "boundary": {
            "provider_calls": False,
            "scheduler_change": False,
            "recurring_ingestion_enabled": False,
            "automatic_first_ingestion": False,
            "ranking_mutation": False,
            "application_action": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run fresh S7U + A1 preflight and optionally apply one controlled, "
            "non-recurring employer-origin source activation."
        )
    )
    parser.add_argument("--company-key", required=True)
    parser.add_argument("--profile-config", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    from src.search_intelligence.controlled_profile import load_controlled_profile
    scope = load_controlled_profile(args.profile_config, args.company_key) if args.profile_config else None
    if args.company_key == 'waymo' and scope is None:
        raise ValueError('Waymo requires --profile-config')
    with psycopg.connect(**get_database_config()) as conn:
        try:
            readiness, decision, policy = build_preflight(
                conn=conn,
                company_key=args.company_key,
                **({"profile_config": scope} if scope else {}),
            )
            applied = None
            if args.apply:
                if not decision.allowed:
                    raise RuntimeError(
                        f"Controlled activation blocked: {decision.status}: {decision.reason}"
                    )
                applied = apply_activation(
                    conn=conn,
                    readiness=readiness,
                    decision=decision,
                    policy=policy,
                )
                conn.commit()
            else:
                conn.rollback()

            manifest = build_manifest(
                readiness=readiness,
                decision=decision,
                policy=policy,
                apply_requested=args.apply,
                applied=applied,
            )
        except Exception:
            conn.rollback()
            raise

    print("Validated Connector Controlled Activation")
    print(f"company_key: {args.company_key}")
    print(f"status: {manifest['decision']['status']}")
    print(f"apply_requested: {args.apply}")
    if manifest["applied"]:
        print(f"profile: {manifest['applied']['profile']['profile_name']}")
        print("recurring_ingestion_enabled: false")
        print("next: run the exact bounded first-ingestion command from the JSON manifest")
    if args.print_json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
