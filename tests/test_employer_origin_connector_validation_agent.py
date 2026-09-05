from __future__ import annotations

import json
from typing import Any

from scripts.run_employer_origin_connector_validation_agent import (
    SourceCandidate,
    ValidationRepository,
    ValidationResult,
    bounded_connector_preview,
    canonical_validation_test_paths,
    evaluate_connector_validation,
)


class RecordingCursor:
    def __init__(self, executions: list[tuple[str, tuple[object, ...]]]) -> None:
        self.executions = executions

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executions.append((query, params))


class RecordingConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def cursor(self, *_args: Any, **_kwargs: Any) -> RecordingCursor:
        return RecordingCursor(self.executions)


def candidate(company_key: str = "missing") -> SourceCandidate:
    return SourceCandidate(
        id=1,
        company_key=company_key,
        company_name="Missing AG",
        source_name_candidate=f"{company_key}:hannover",
        source_family_candidate=company_key,
        source_type_candidate="employer_origin_career_site",
        status="connector_candidate",
    )


def test_validation_fails_when_connector_module_is_missing() -> None:
    result = evaluate_connector_validation(candidate(), run_pytest=False)

    assert result.gate_status == "manual_review_required"
    assert result.decision == "connector_validation_failed"
    assert result.stop_reason == "connector module is missing"
    assert result.evidence["boundary"]["bronze_persistence"] is False
    assert result.evidence["agent"] == "s4b_connector_validation_agent"
    assert result.evidence["expected_files"]["bounded_preview"]["attempted"] is False


def test_validation_is_not_applicable_for_active_controlled_source() -> None:
    active = SourceCandidate(
        id=1,
        company_key="finanz_informatik",
        company_name="Finanz Informatik GmbH & Co. KG",
        source_name_candidate="finanz_informatik:hannover",
        source_family_candidate="finanz_informatik",
        source_type_candidate="employer_origin_career_site",
        status="active_controlled",
    )

    result = evaluate_connector_validation(active, run_pytest=False)

    assert result.gate_status == "not_applicable"
    assert result.decision == "monitor_existing_source"
    assert result.stop_reason == "candidate is already active_controlled"


def test_validation_records_s4b_agent_name_for_active_controlled_source() -> None:
    active = SourceCandidate(
        id=1,
        company_key="finanz_informatik",
        company_name="Finanz Informatik GmbH & Co. KG",
        source_name_candidate="finanz_informatik:hannover",
        source_family_candidate="finanz_informatik",
        source_type_candidate="employer_origin_career_site",
        status="active_controlled",
    )

    result = evaluate_connector_validation(active, run_pytest=False)

    assert result.evidence["agent"] == "s4b_connector_validation_agent"


def test_validation_preview_instantiates_greenhouse_from_source_target() -> None:
    result = bounded_connector_preview(
        "src.connectors.greenhouse",
        "GreenhouseConnector",
        source_name_candidate="greenhouse:moia",
    )

    assert result["class_found"] is True
    assert result["instantiated"] is True
    assert result["error"] is None


def test_greenhouse_validation_uses_canonical_relevant_test_manifest() -> None:
    greenhouse = SourceCandidate(
        id=1,
        company_key="moia",
        company_name="MOIA",
        source_name_candidate="greenhouse:moia",
        source_family_candidate="greenhouse",
        source_type_candidate="employer_origin_career_site",
        status="manual_review_required",
    )

    assert canonical_validation_test_paths(greenhouse) == [
        "tests/test_greenhouse_connector.py",
        "tests/test_connector_registry.py",
        "tests/test_ingest_jobs_cli.py",
        "tests/test_greenhouse_board_candidate_validation.py",
        "tests/test_silver_transformer_canonicalization.py",
        "tests/career_intelligence/test_moia_live_source.py",
    ]


def test_validation_runs_relevant_tests_not_full_repository_pytest(monkeypatch) -> None:
    commands = []

    def fake_run_command(command):
        commands.append(command)
        return {
            "command": command,
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        }

    monkeypatch.setattr(
        "scripts.run_employer_origin_connector_validation_agent.run_command",
        fake_run_command,
    )
    greenhouse = SourceCandidate(
        id=1,
        company_key="moia",
        company_name="MOIA",
        source_name_candidate="greenhouse:moia",
        source_family_candidate="greenhouse",
        source_type_candidate="employer_origin_career_site",
        status="manual_review_required",
    )

    result = evaluate_connector_validation(greenhouse, run_pytest=True)

    assert result.gate_status == "passed"
    assert result.decision == "ready_for_final_approval"
    assert [command[2:] for command in commands] == [
        ["compileall", "src", "scripts", "tests"],
        [
            "pytest",
            "-q",
            "tests/test_greenhouse_connector.py",
            "tests/test_connector_registry.py",
            "tests/test_ingest_jobs_cli.py",
            "tests/test_greenhouse_board_candidate_validation.py",
            "tests/test_silver_transformer_canonicalization.py",
            "tests/career_intelligence/test_moia_live_source.py",
        ],
    ]
    assert [command for command in commands if command == [commands[0][0], "-m", "pytest", "-q"]] == []
    assert result.evidence["validation_tests"] == [
        "tests/test_greenhouse_connector.py",
        "tests/test_connector_registry.py",
        "tests/test_ingest_jobs_cli.py",
        "tests/test_greenhouse_board_candidate_validation.py",
        "tests/test_silver_transformer_canonicalization.py",
        "tests/career_intelligence/test_moia_live_source.py",
    ]


def test_validation_fails_closed_when_relevant_connector_test_fails(monkeypatch) -> None:
    def fake_run_command(command):
        return {
            "command": command,
            "returncode": 1 if "pytest" in command else 0,
            "stdout_tail": "failed relevant connector test",
            "stderr_tail": "",
        }

    monkeypatch.setattr(
        "scripts.run_employer_origin_connector_validation_agent.run_command",
        fake_run_command,
    )
    greenhouse = SourceCandidate(
        id=1,
        company_key="moia",
        company_name="MOIA",
        source_name_candidate="greenhouse:moia",
        source_family_candidate="greenhouse",
        source_type_candidate="employer_origin_career_site",
        status="manual_review_required",
    )

    result = evaluate_connector_validation(greenhouse, run_pytest=True)

    assert result.gate_status == "manual_review_required"
    assert result.decision == "connector_validation_failed"
    assert result.stop_reason == "validation command failed"
    assert result.evidence["commands"][1]["returncode"] == 1


def test_validation_gate_persistence_binds_official_order_and_name() -> None:
    connection = RecordingConnection()
    repository = ValidationRepository(connection)  # type: ignore[arg-type]
    result = ValidationResult(
        gate_status="passed",
        decision="ready_for_final_approval",
        stop_reason=None,
        evidence={"agent": "s4b_connector_validation_agent"},
    )

    repository.record_gate(
        candidate_id=57,
        result=result,
        reviewed_by="connector_autonomy_a1",
    )

    assert len(connection.executions) == 1
    _query, params = connection.executions[0]
    assert len(params) == 8
    assert params[0] == 57
    assert params[1] == 11
    assert params[2] == "connector_validation_gate"
    assert params[3] == "passed"
    assert params[4] == "ready_for_final_approval"
    assert params[5] is None
    assert json.loads(str(params[6])) == {
        "agent": "s4b_connector_validation_agent"
    }
    assert params[7] == "connector_autonomy_a1"
