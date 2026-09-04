from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.career_intelligence import moia_live_source as moia


def test_moia_source_identity_uses_greenhouse_board_token() -> None:
    assert moia.MOIA_SOURCE_NAME == "greenhouse:moia"
    assert moia.MOIA_BOARD_TOKEN == "moia"
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


def test_moia_live_source_does_not_bypass_activation_or_application_boundaries() -> None:
    source = Path("src/career_intelligence/moia_live_source.py").read_text(encoding="utf-8")

    assert "connector_validation_gate" in source
    assert "ready_for_final_approval" in source
    assert "final_approval_gate" in source
    assert "approve_connector_registration" in source
    assert "recurring_ingestion_enabled" in source
    assert "VALUES (%s, %s, %s, %s, %s, %s, TRUE, FALSE)" in source
    assert "src.ingest_jobs" in source
    assert "src.run_silver_jobs" in source
    assert "src.career_intelligence.daily" in source
    assert "product_v1_ranking_authority" in source
    assert "application_submission" in source
    assert "requests.get" not in source


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
