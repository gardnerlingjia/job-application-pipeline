from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import psycopg

from src.career_intelligence import moia_live_source as moia


def test_moia_source_identity_uses_greenhouse_board_token() -> None:
    assert moia.MOIA_SOURCE_NAME == "greenhouse:moia"
    assert moia.MOIA_BOARD_TOKEN == "moia"
    assert moia.MOIA_PROFILE_NAME == "moia_controlled_hannover_precision"
    assert "autonomous mobility" in moia.MOIA_SEARCH_TERMS
    assert "technical program" in moia.MOIA_SEARCH_TERMS
    assert "data" in moia.MOIA_SEARCH_TERMS


def test_moia_daily_commands_reuse_canonical_pipeline() -> None:
    commands = moia.build_moia_daily_commands("python")

    assert commands == [
        ["python", "-m", "src.ingest_jobs", "--profile", moia.MOIA_PROFILE_NAME],
        [
            "python",
            "-m",
            "src.run_silver_jobs",
            "--source",
            "greenhouse:moia",
            "--limit",
            str(moia.MOIA_PAGE_SIZE),
        ],
        [
            "python",
            "-m",
            "src.career_intelligence.daily",
            "--source",
            "greenhouse:moia",
            "--limit",
            str(moia.MOIA_PAGE_SIZE),
        ],
    ]


def test_moia_daily_flow_stops_on_canonical_command_failure() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 2)

    exit_status = moia.run_moia_daily_flow(runner=runner, python_executable="python")

    assert exit_status == 2
    assert calls == [["python", "-m", "src.ingest_jobs", "--profile", moia.MOIA_PROFILE_NAME]]


def test_moia_activation_preflight_requires_all_existing_gates() -> None:
    missing_candidate = moia.MoiaActivationPreflight(
        candidate_id=None,
        candidate_status=None,
        connector_validation_passed=False,
        final_approval_passed=False,
        active_profile_exists=False,
    )
    missing_final = moia.MoiaActivationPreflight(
        candidate_id=42,
        candidate_status="manual_review_required",
        connector_validation_passed=True,
        final_approval_passed=False,
        active_profile_exists=False,
    )
    ready = moia.MoiaActivationPreflight(
        candidate_id=42,
        candidate_status="manual_review_required",
        connector_validation_passed=True,
        final_approval_passed=True,
        active_profile_exists=False,
    )

    assert missing_candidate.activation_allowed is False
    assert missing_candidate.status == "blocked_missing_source_candidate"
    assert missing_final.activation_allowed is False
    assert missing_final.status == "blocked_missing_final_approval"
    assert ready.activation_allowed is True
    assert ready.status == "activation_ready"


def test_moia_preflight_recommends_correct_next_commands() -> None:
    assert (
        moia.MoiaActivationPreflight(None, None, False, False, False).next_recommended_command
        == "register the MOIA source candidate, then rerun preflight"
    )
    assert (
        moia.MoiaActivationPreflight(1, "manual_review_required", False, False, False)
        .next_recommended_command
        == "python -m src.career_intelligence.moia_live_source validate --dry-run"
    )
    assert (
        moia.MoiaActivationPreflight(1, "manual_review_required", True, False, False)
        .next_recommended_command
        == "python -m src.career_intelligence.moia_live_source approve --reviewed-by lingjia"
    )
    assert (
        moia.MoiaActivationPreflight(1, "manual_review_required", True, True, False)
        .next_recommended_command
        == "python -m src.career_intelligence.moia_live_source activate"
    )
    assert (
        moia.MoiaActivationPreflight(1, "active_controlled", True, True, True)
        .next_recommended_command
        == "python -m src.career_intelligence.moia_live_source run-daily"
    )


def test_moia_validate_dry_run_delegates_without_writing(monkeypatch) -> None:
    recorded = {}

    def fake_run_agent(args):
        recorded.update(vars(args))
        return 0

    monkeypatch.setattr(moia, "ensure_operational_database", lambda: None)
    monkeypatch.setattr(moia.validation_agent, "run_agent", fake_run_agent)

    exit_code = moia.run_moia_validate(
        argparse.Namespace(
            reviewed_by="lingjia",
            dry_run=True,
            no_pytest=True,
            print_json=False,
        )
    )

    assert exit_code == 0
    assert recorded == {
        "candidate_id": None,
        "company_key": "moia",
        "reviewed_by": "lingjia",
        "dry_run": True,
        "no_pytest": True,
        "print_json": False,
    }


def test_moia_validate_real_run_records_only_connector_validation_gate(monkeypatch) -> None:
    recorded = {}

    def fake_run_agent(args):
        recorded.update(vars(args))
        return 0

    monkeypatch.setattr(moia, "ensure_operational_database", lambda: None)
    monkeypatch.setattr(moia.validation_agent, "run_agent", fake_run_agent)

    exit_code = moia.run_moia_validate(
        argparse.Namespace(
            reviewed_by="lingjia",
            dry_run=False,
            no_pytest=True,
            print_json=False,
        )
    )

    assert exit_code == 0
    assert recorded["dry_run"] is False
    assert recorded["company_key"] == "moia"
    assert "connector_validation_gate" in Path(
        "scripts/run_employer_origin_connector_validation_agent.py"
    ).read_text(encoding="utf-8")
    assert "final_approval_gate" not in Path(
        "scripts/run_employer_origin_connector_validation_agent.py"
    ).read_text(encoding="utf-8")


def test_moia_approve_refuses_before_validation(monkeypatch) -> None:
    recorded = {}

    def fake_run_agent(args):
        recorded.update(vars(args))
        return 2

    monkeypatch.setattr(moia, "ensure_operational_database", lambda: None)
    monkeypatch.setattr(moia.approval_agent, "run_agent", fake_run_agent)

    exit_code = moia.run_moia_approve(
        argparse.Namespace(
            reviewed_by="lingjia",
            approval_token=None,
            dry_run=False,
            print_json=False,
        )
    )

    assert exit_code == 2
    assert recorded["company_key"] == "moia"
    assert recorded["approved_by"] == "lingjia"


def test_moia_approve_requires_explicit_operator_command() -> None:
    parser = moia.build_parser()

    args = parser.parse_args(["approve", "--reviewed-by", "lingjia"])

    assert args.command == "approve"
    assert args.reviewed_by == "lingjia"


def test_moia_activate_refuses_before_both_gates() -> None:
    missing_validation = moia.MoiaActivationPreflight(
        candidate_id=1,
        candidate_status="manual_review_required",
        connector_validation_passed=False,
        final_approval_passed=False,
        active_profile_exists=False,
    )
    missing_approval = moia.MoiaActivationPreflight(
        candidate_id=1,
        candidate_status="manual_review_required",
        connector_validation_passed=True,
        final_approval_passed=False,
        active_profile_exists=False,
    )

    assert missing_validation.activation_allowed is False
    assert missing_approval.activation_allowed is False


def test_moia_activate_succeeds_only_after_both_gates() -> None:
    ready = moia.MoiaActivationPreflight(
        candidate_id=1,
        candidate_status="manual_review_required",
        connector_validation_passed=True,
        final_approval_passed=True,
        active_profile_exists=False,
    )

    assert ready.activation_allowed is True


def test_moia_run_daily_refuses_before_activation(capsys) -> None:
    preflight = moia.MoiaActivationPreflight(
        candidate_id=1,
        candidate_status="manual_review_required",
        connector_validation_passed=True,
        final_approval_passed=True,
        active_profile_exists=False,
    )
    calls = []

    exit_code = moia.run_moia_daily_if_activated(
        preflight,
        daily_runner=lambda: calls.append("daily") or 0,
    )

    assert exit_code == 2
    assert calls == []
    assert "MOIA run-daily blocked: activation_ready" in capsys.readouterr().out


def test_moia_run_daily_uses_canonical_flow_after_activation() -> None:
    preflight = moia.MoiaActivationPreflight(
        candidate_id=1,
        candidate_status="active_controlled",
        connector_validation_passed=True,
        final_approval_passed=True,
        active_profile_exists=True,
    )

    assert moia.run_moia_daily_if_activated(preflight, daily_runner=lambda: 0) == 0


def test_moia_missing_database_prints_clean_guidance(monkeypatch, capsys) -> None:
    def unavailable_connect(**_kwargs):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(moia.psycopg, "connect", unavailable_connect)

    exit_code = moia.main(["preflight"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "Database unavailable. Start with: docker compose up -d postgres" in output
    assert "Traceback" not in output


def test_moia_missing_schema_prints_migration_command(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        moia.psycopg,
        "connect",
        lambda **_kwargs: FakeMoiaConnection(existing_tables={"schema_migrations"}),
    )

    exit_code = moia.main(["preflight"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "Schema not initialized. Missing required table(s):" in output
    assert ".venv/bin/python scripts/apply_db_migrations.py --apply --applied-by local" in output
    assert "Traceback" not in output


def test_moia_doctor_reports_next_action_for_missing_schema(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        moia.psycopg,
        "connect",
        lambda **_kwargs: FakeMoiaConnection(existing_tables={"schema_migrations"}),
    )

    exit_code = moia.main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "MOIA live-source doctor" in output
    assert "database: PASS" in output
    assert "schema: BLOCKED" in output
    assert "next: .venv/bin/python scripts/apply_db_migrations.py --apply --applied-by local" in output


def test_moia_doctor_reports_next_action_from_preflight(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        moia.psycopg,
        "connect",
        lambda **_kwargs: FakeMoiaConnection(
            existing_tables=set(moia.REQUIRED_SCHEMA_TABLES) | {"schema_migrations"},
            candidate={
                "id": 1,
                "status": "manual_review_required",
            },
        ),
    )

    exit_code = moia.main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "schema: PASS" in output
    assert "moia_candidate: PASS" in output
    assert "connector_validation_gate: BLOCKED" in output
    assert "next: python -m src.career_intelligence.moia_live_source validate --dry-run" in output


def test_moia_live_source_does_not_bypass_activation_or_application_boundaries() -> None:
    source = Path("src/career_intelligence/moia_live_source.py").read_text(encoding="utf-8")

    assert "validation_agent.run_agent" in source
    assert "approval_agent.run_agent" in source
    assert "apply_controlled_activation" in source
    assert "connector_validation_gate" in source
    assert "ready_for_final_approval" in source
    assert "final_approval_gate" in source
    assert "approve_connector_registration" in source
    assert "src.ingest_jobs" in source
    assert "src.run_silver_jobs" in source
    assert "src.career_intelligence.daily" in source
    assert "product_v1_ranking_authority" in source
    assert "application_submission" in source
    assert "requests.get" not in source
    assert "application_draft" not in source


def test_moia_candidate_migration_seeds_candidate_without_approval_or_activation() -> None:
    migration = Path(
        "db/migrations/107_register_moia_greenhouse_source_candidate.sql"
    ).read_text(encoding="utf-8")

    assert "source_name_candidate" in migration
    assert "'greenhouse:moia'" in migration
    assert "'manual_review_required'" in migration
    assert "INSERT INTO search_profiles" not in migration
    assert "gate_status = 'passed'" not in migration
    assert "run ingestion" in migration


def test_module_entrypoint_is_python_m_compatible() -> None:
    commands = moia.build_moia_daily_commands(sys.executable)

    assert commands[0][0] == sys.executable


class FakeMoiaConnection:
    def __init__(
        self,
        *,
        existing_tables: set[str],
        candidate: dict[str, object] | None = None,
        gates: dict[str, dict[str, object]] | None = None,
        active_profile: bool = False,
    ) -> None:
        self.existing_tables = existing_tables
        self.candidate = candidate
        self.gates = gates or {}
        self.active_profile = active_profile

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def rollback(self) -> None:
        return None

    def cursor(self, *args, **kwargs):
        return FakeMoiaCursor(self)


class FakeMoiaCursor:
    def __init__(self, conn: FakeMoiaConnection) -> None:
        self.conn = conn
        self.fetchone_row = None
        self.fetchall_rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query: str, params=None) -> None:
        normalized = " ".join(query.split())
        if "FROM information_schema.tables" in normalized:
            requested = set(params[0])
            self.fetchall_rows = [
                {"table_name": table}
                for table in sorted(self.conn.existing_tables & requested)
            ]
            return
        if "to_regclass('public.schema_migrations')" in normalized:
            self.fetchone_row = {
                "relation": (
                    "schema_migrations"
                    if "schema_migrations" in self.conn.existing_tables
                    else None
                )
            }
            return
        if "FROM schema_migrations" in normalized:
            self.fetchone_row = {"applied_count": 1, "failed_count": 0}
            return
        if "FROM employer_origin_source_candidates" in normalized:
            self.fetchone_row = self.conn.candidate
            return
        if "FROM search_profiles" in normalized:
            self.fetchone_row = {"exists": 1} if self.conn.active_profile else None
            return
        if "FROM employer_origin_candidate_gate_reviews" in normalized:
            gate = self.conn.gates.get(str(params[1]))
            self.fetchone_row = gate
            return
        raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self.fetchone_row

    def fetchall(self):
        return self.fetchall_rows
