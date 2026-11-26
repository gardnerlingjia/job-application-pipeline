from __future__ import annotations

import argparse
import importlib
import inspect
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.config import get_database_config
from src.search_intelligence.employer_origin_gate_registry import gate_order

VALIDATION_GATE = "connector_validation_gate"
DEFAULT_CONNECTOR_VALIDATION_TESTS = (
    "tests/test_connector_registry.py",
    "tests/test_ingest_jobs_cli.py",
)
SOURCE_FAMILY_VALIDATION_TESTS = {
    "greenhouse": (
        "tests/test_greenhouse_connector.py",
        "tests/test_greenhouse_board_candidate_validation.py",
        "tests/test_silver_transformer_canonicalization.py",
        "tests/career_intelligence/test_moia_live_source.py",
    ),
}


@dataclass(frozen=True)
class SourceCandidate:
    id: int
    company_key: str
    company_name: str
    source_name_candidate: str
    source_family_candidate: str
    source_type_candidate: str
    status: str


@dataclass(frozen=True)
class ValidationResult:
    gate_status: str
    decision: str
    stop_reason: str | None
    evidence: dict[str, Any]


def snake_case(value: str) -> str:
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def module_path_for(candidate: SourceCandidate) -> Path:
    return Path("src/connectors") / f"{snake_case(candidate.source_family_candidate)}.py"


def test_path_for(candidate: SourceCandidate) -> Path:
    return Path("tests") / f"test_{snake_case(candidate.source_family_candidate)}_connector.py"


def module_import_path_for(candidate: SourceCandidate) -> str:
    return f"src.connectors.{snake_case(candidate.source_family_candidate)}"


def pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in snake_case(value).split("_") if part)


def class_name_for(candidate: SourceCandidate) -> str:
    return f"{pascal_case(candidate.source_family_candidate)}Connector"


def canonical_validation_test_paths(candidate: SourceCandidate) -> list[str]:
    paths = [
        str(test_path_for(candidate)),
        *DEFAULT_CONNECTOR_VALIDATION_TESTS,
        *(
            path
            for path in SOURCE_FAMILY_VALIDATION_TESTS.get(
                snake_case(candidate.source_family_candidate),
                (),
            )
        ),
    ]
    unique_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        unique_paths.append(path)
        seen.add(path)
    return unique_paths


def bounded_connector_preview(
    import_path: str,
    class_name: str,
    *,
    source_name_candidate: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempted": True,
        "import_path": import_path,
        "class_name": class_name,
        "class_found": False,
        "instantiated": False,
        "fetch_jobs_present": False,
        "safe_fetcher_used": False,
        "method_invoked": False,
        "record_count": None,
        "source_url": None,
        "error": None,
    }

    try:
        module = importlib.import_module(import_path)
        connector_class = getattr(module, class_name, None)
        if connector_class is None:
            result["error"] = "connector class not found"
            return result

        result["class_found"] = True
        result["fetch_jobs_present"] = callable(getattr(connector_class, "fetch_jobs", None))

        init_signature = inspect.signature(connector_class)
        kwargs: dict[str, Any] = {}

        if "board_token" in init_signature.parameters and source_name_candidate:
            from src.connectors.registry import source_target

            kwargs["board_token"] = source_target(source_name_candidate)

        if "target_key" in init_signature.parameters and source_name_candidate:
            from src.connectors.registry import source_target

            kwargs["target_key"] = source_target(source_name_candidate)

        if "fetcher" in init_signature.parameters:
            result["safe_fetcher_used"] = True

            def fake_fetcher(url: str) -> tuple[str, str, int]:
                html = (
                    "<html><head><title>Product Owner Data Platform - Test</title></head>"
                    "<body>"
                    "<a href='/jobs/product-owner-data-platform'>"
                    "Product Owner Data Platform Hannover Data Analytics"
                    "</a>"
                    "Product Owner Data Platform Hannover Data Analytics Python SQL"
                    "</body></html>"
                )
                return html, url, 200

            kwargs["fetcher"] = fake_fetcher

        if "max_detail_pages" in init_signature.parameters:
            kwargs["max_detail_pages"] = 1

        connector = connector_class(**kwargs)
        result["instantiated"] = True

        if result["safe_fetcher_used"] and result["fetch_jobs_present"]:
            from src.connectors.base import SearchProfile, SearchTerm

            records, source_url = connector.fetch_jobs(
                SearchProfile(
                    id=0,
                    profile_name="validation_smoke",
                    source_name=getattr(connector, "source_name", "validation"),
                    search_location="hannover",
                    search_radius_km=None,
                    offer_type=None,
                    page_size=1,
                ),
                SearchTerm(search_term="data", id=0),
            )
            result["method_invoked"] = True
            result["record_count"] = len(records)
            result["source_url"] = source_url

    except Exception as exc:  # noqa: BLE001 - validation must report smoke failures.
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def import_connector_module(import_path: str) -> tuple[bool, str | None]:
    try:
        importlib.import_module(import_path)
    except Exception as exc:  # noqa: BLE001 - validation must report import failures.
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


def evaluate_connector_validation(candidate: SourceCandidate, *, run_pytest: bool) -> ValidationResult:
    if candidate.status == "active_controlled":
        evidence = {
            "agent": "s4b_connector_validation_agent",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "candidate": {
                "candidate_id": candidate.id,
                "company_key": candidate.company_key,
                "source_name_candidate": candidate.source_name_candidate,
                "source_family_candidate": candidate.source_family_candidate,
                "source_type_candidate": candidate.source_type_candidate,
                "status": candidate.status,
            },
            "boundary": {
                "database_writes": True,
                "bronze_persistence": False,
                "connector_registration": False,
                "source_activation": False,
                "recurring_ingestion": False,
                "csv_or_export_inputs_used": False,
            },
        }
        return ValidationResult(
            gate_status="not_applicable",
            decision="monitor_existing_source",
            stop_reason="candidate is already active_controlled",
            evidence=evidence,
        )

    module_path = module_path_for(candidate)
    test_path = test_path_for(candidate)
    import_path = module_import_path_for(candidate)
    validation_test_paths = canonical_validation_test_paths(candidate)

    module_exists = module_path.exists()
    test_exists = test_path.exists()
    missing_validation_tests = [
        str(path)
        for path in validation_test_paths
        if not Path(path).exists()
    ]
    import_ok = False
    import_error = None

    bounded_preview: dict[str, Any] = {"attempted": False}

    if module_exists:
        import_ok, import_error = import_connector_module(import_path)
        if import_ok:
            bounded_preview = bounded_connector_preview(
                import_path,
                class_name_for(candidate),
                source_name_candidate=candidate.source_name_candidate,
            )

    commands: list[dict[str, Any]] = []
    commands.append(run_command([sys.executable, "-m", "compileall", "src", "scripts", "tests"]))

    if run_pytest and not missing_validation_tests:
        commands.append(
            run_command(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    *validation_test_paths,
                ]
            )
        )

    failed_commands = [command for command in commands if command["returncode"] != 0]

    evidence = {
        "agent": "s4b_connector_validation_agent",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "candidate": {
            "candidate_id": candidate.id,
            "company_key": candidate.company_key,
            "source_name_candidate": candidate.source_name_candidate,
            "source_family_candidate": candidate.source_family_candidate,
            "source_type_candidate": candidate.source_type_candidate,
            "status": candidate.status,
        },
        "expected_files": {
            "module_path": str(module_path),
            "test_path": str(test_path),
            "module_exists": module_exists,
            "test_exists": test_exists,
            "import_path": import_path,
            "import_ok": import_ok,
            "import_error": import_error,
            "bounded_preview": bounded_preview,
        },
        "validation_tests": validation_test_paths,
        "missing_validation_tests": missing_validation_tests,
        "commands": commands,
        "boundary": {
            "database_writes": True,
            "bronze_persistence": False,
            "connector_registration": False,
            "source_activation": False,
            "recurring_ingestion": False,
            "csv_or_export_inputs_used": False,
        },
    }

    if not module_exists:
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="connector module is missing",
            evidence=evidence,
        )

    if not test_exists:
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="connector test file is missing",
            evidence=evidence,
        )

    if missing_validation_tests:
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="canonical validation test file is missing",
            evidence=evidence,
        )

    if not import_ok:
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="connector module import failed",
            evidence=evidence,
        )

    if bounded_preview.get("error"):
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="bounded connector preview failed",
            evidence=evidence,
        )

    if failed_commands:
        return ValidationResult(
            gate_status="manual_review_required",
            decision="connector_validation_failed",
            stop_reason="validation command failed",
            evidence=evidence,
        )

    return ValidationResult(
        gate_status="passed",
        decision="ready_for_final_approval",
        stop_reason=None,
        evidence=evidence,
    )


def validation_lines(candidate: SourceCandidate, result: ValidationResult) -> list[str]:
    lines = [
        f"candidate_id: {candidate.id}",
        f"candidate: {candidate.company_key} | {candidate.source_name_candidate}",
        f"{VALIDATION_GATE}: {result.gate_status} / {result.decision}",
    ]
    if result.stop_reason:
        lines.append(f"STOP: {result.stop_reason}")
    else:
        lines.append("NEXT: final approval gate may be requested.")
    return lines


class ValidationRepository:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn

    def load_candidate(self, *, candidate_id: int | None, company_key: str | None) -> SourceCandidate:
        if candidate_id is None and not company_key:
            raise ValueError("Either candidate_id or company_key is required.")

        with self.conn.cursor(row_factory=dict_row) as cur:
            if candidate_id is not None:
                cur.execute(
                    """
                    select *
                    from employer_origin_source_candidates
                    where id = %s
                    """,
                    (candidate_id,),
                )
            else:
                cur.execute(
                    """
                    select *
                    from employer_origin_source_candidates
                    where company_key = %s
                    order by id desc
                    limit 1
                    """,
                    (company_key,),
                )
            row = cur.fetchone()

        if row is None:
            raise ValueError("No employer-origin source candidate found.")

        return SourceCandidate(
            id=int(row["id"]),
            company_key=str(row["company_key"]),
            company_name=str(row["company_name"]),
            source_name_candidate=str(row["source_name_candidate"]),
            source_family_candidate=str(row["source_family_candidate"]),
            source_type_candidate=str(row["source_type_candidate"]),
            status=str(row["status"]),
        )

    def record_gate(self, *, candidate_id: int, result: ValidationResult, reviewed_by: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into employer_origin_candidate_gate_reviews (
                    candidate_id,
                    gate_order,
                    gate_name,
                    gate_status,
                    decision,
                    stop_reason,
                    evidence,
                    reviewed_by
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (candidate_id, gate_name)
                do update set
                    gate_status = excluded.gate_status,
                    decision = excluded.decision,
                    stop_reason = excluded.stop_reason,
                    evidence = excluded.evidence,
                    reviewed_by = excluded.reviewed_by
                """,
                (
                    candidate_id,
                    gate_order(VALIDATION_GATE),
                    VALIDATION_GATE,
                    result.gate_status,
                    result.decision,
                    result.stop_reason,
                    json.dumps(result.evidence),
                    reviewed_by,
                ),
            )


def run_agent(args: argparse.Namespace) -> int:
    with psycopg.connect(**get_database_config()) as conn:
        repo = ValidationRepository(conn)
        candidate = repo.load_candidate(candidate_id=args.candidate_id, company_key=args.company_key)
        result = evaluate_connector_validation(candidate, run_pytest=not args.no_pytest)

        if not args.dry_run:
            repo.record_gate(candidate_id=candidate.id, result=result, reviewed_by=args.reviewed_by)
            conn.commit()

    for line in validation_lines(candidate, result):
        print(line)

    if args.dry_run:
        print("DRY RUN: no DB gate state was changed.")

    if args.print_json:
        print(json.dumps(result.evidence, indent=2, ensure_ascii=False, default=str))

    return 0 if result.gate_status in {"passed", "not_applicable"} else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an employer-origin connector candidate before final approval.")
    candidate = parser.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--candidate-id", type=int)
    candidate.add_argument("--company-key")
    parser.add_argument("--reviewed-by", default="agent")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-pytest", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    return parser


def main() -> None:
    raise SystemExit(run_agent(build_parser().parse_args()))


if __name__ == "__main__":
    main()
