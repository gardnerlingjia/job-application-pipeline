import json
from pathlib import Path

from src.career_intelligence.daily import (
    DailyRunLock,
    main,
    recommendation_counts,
    run_daily,
    summary_lines,
)


def successful_summary():
    return {
        "loaded": 5,
        "converted": 3,
        "processed": 2,
        "skipped_existing": 1,
        "errors": [],
        "opportunities": [
            opportunity("apply.json", "APPLY_NOW", 95),
            opportunity("network.json", "NETWORK_FIRST", 85),
            opportunity("explore-a.json", "EXPLORE", 75),
            opportunity("explore-b.json", "EXPLORE", 70),
            opportunity("watch.json", "WATCH", 55),
            opportunity("skip.json", "SKIP", 20),
        ],
    }


def opportunity(source_file, recommendation, score, company="Example", title="Role"):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "company": company,
        "title": title,
        "career_lane": "data",
        "career_lane_label": "Data",
        "opportunity_score": score,
        "recommendation": recommendation,
        "constraint_action": "CLEAR",
        "risks": [],
        "key_matched_capabilities": [],
    }


def test_successful_daily_run_prints_operator_summary(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        "src.career_intelligence.daily.process_silver",
        lambda **kwargs: successful_summary(),
    )

    exit_status = main(
        [
            "--results",
            str(tmp_path / "results"),
            "--runtime-dir",
            str(tmp_path / "runtime"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--limit",
            "5",
        ]
    )

    output = capsys.readouterr().out
    assert exit_status == 0
    assert "Silver jobs loaded: 5" in output
    assert "Converted: 3" in output
    assert "Newly assessed: 2" in output
    assert "Already known/skipped: 1" in output
    assert "APPLY_NOW: 1" in output
    assert "NETWORK_FIRST: 1" in output
    assert "EXPLORE: 2" in output
    assert "WATCH: 1" in output
    assert "SKIP: 1" in output
    assert "NEW: 6" in output
    assert "INTERESTED: 0" in output
    assert "REVIEWED: 0" in output
    assert "DISMISSED: 0" in output
    assert "Exit status: 0" in output
    assert "Log:" in output


def test_ingestion_failure_returns_nonzero_and_writes_log(tmp_path):
    def fail(**kwargs):
        raise RuntimeError("database unavailable")

    exit_status, lines, path = run_daily(
        results=tmp_path / "results",
        runtime_dir=tmp_path / "runtime",
        ingestion=fail,
    )

    assert exit_status == 1
    assert any("database unavailable" in line for line in lines)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["exit_status"] == 1
    assert payload["errors"] == [
        {"record": "daily", "error": "database unavailable"}
    ]


def test_malformed_operator_state_prevents_ingestion(tmp_path):
    calls = []
    state_file = tmp_path / "operator_state.json"
    state_file.write_text("{broken", encoding="utf-8")

    def ingest(**kwargs):
        calls.append(kwargs)
        return successful_summary()

    exit_status, lines, _path = run_daily(
        results=tmp_path / "results",
        runtime_dir=tmp_path / "runtime",
        state_path=state_file,
        ingestion=ingest,
    )

    assert exit_status == 1
    assert calls == []
    assert any("ERROR" in line for line in lines)


def test_lock_prevents_concurrent_daily_run(tmp_path):
    runtime = tmp_path / "runtime"
    lock_path = runtime / "daily.lock"
    with DailyRunLock(lock_path):
        exit_status, lines, path = run_daily(
            results=tmp_path / "results",
            runtime_dir=runtime,
            ingestion=lambda **kwargs: successful_summary(),
        )

    assert exit_status == 2
    assert any("already active" in line for line in lines)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["exit_status"] == 2


def test_stale_lock_is_replaced_and_cleaned_up(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    lock_path = runtime / "daily.lock"
    lock_path.write_text(
        json.dumps({"pid": 999999, "created_at_utc": "2000-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    exit_status, lines, _path = run_daily(
        results=tmp_path / "results",
        runtime_dir=runtime,
        ingestion=lambda **kwargs: successful_summary(),
    )

    assert exit_status == 0
    assert any("Exit status: 0" in line for line in lines)
    assert not lock_path.exists()


def test_log_creation_records_counts_and_status_without_descriptions(tmp_path):
    secret_description = "FULL PRIVATE JOB DESCRIPTION SHOULD NOT APPEAR"

    def ingest(**kwargs):
        summary = successful_summary()
        summary["errors"] = [
            {
                "record": "silver-personio-example.json",
                "error": "missing or empty required fields: description",
                "description": secret_description,
            }
        ]
        return summary

    exit_status, _lines, path = run_daily(
        results=tmp_path / "results",
        runtime_dir=tmp_path / "runtime",
        ingestion=ingest,
    )

    log_text = path.read_text(encoding="utf-8")
    payload = json.loads(log_text)
    assert exit_status == 1
    assert payload["started_at_utc"]
    assert payload["finished_at_utc"]
    assert payload["exit_status"] == 1
    assert "Silver jobs loaded: 5" in payload["summary"]
    assert secret_description not in log_text


def test_recommendation_counts_are_reported_for_all_groups():
    assert recommendation_counts(
        [
            {"recommendation": "APPLY_NOW"},
            {"recommendation": "APPLY_NOW"},
            {"recommendation": "WATCH"},
            {"recommendation": "UNKNOWN"},
        ]
    ) == {
        "APPLY_NOW": 2,
        "NETWORK_FIRST": 0,
        "EXPLORE": 0,
        "WATCH": 1,
        "SKIP": 0,
    }


def test_summary_lines_include_exit_code_and_counts():
    lines = summary_lines(successful_summary(), exit_status=0)

    assert "Silver jobs loaded: 5" in lines
    assert "Errors: 0" in lines
    assert lines[-1] == "Exit status: 0"


def test_main_forwards_arguments_to_ingestion(tmp_path, monkeypatch):
    calls = []

    def ingest(**kwargs):
        calls.append(kwargs)
        return successful_summary()

    monkeypatch.setattr("src.career_intelligence.daily.process_silver", ingest)

    exit_status = main(
        [
            "--results",
            str(tmp_path / "results"),
            "--runtime-dir",
            str(tmp_path / "runtime"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--source",
            "personio",
            "--limit",
            "7",
        ]
    )

    assert exit_status == 0
    assert calls == [
        {
            "results": Path(tmp_path / "results"),
            "limit": 7,
            "source": "personio",
        }
    ]


def test_daily_rerun_preserves_operator_state_and_default_radar_omits_dismissed(
    tmp_path,
    monkeypatch,
):
    from src.career_intelligence.operator_state import set_operator_state

    state_file = tmp_path / "operator_state.json"
    set_operator_state(
        source_file="apply.json",
        state="INTERESTED",
        path=state_file,
    )
    set_operator_state(
        source_file="skip.json",
        state="DISMISSED",
        path=state_file,
    )
    monkeypatch.setattr(
        "src.career_intelligence.daily.process_silver",
        lambda **kwargs: successful_summary(),
    )

    for _index in range(2):
        exit_status, lines, _path = run_daily(
            results=tmp_path / "results",
            runtime_dir=tmp_path / "runtime",
            state_path=state_file,
        )

    radar = (tmp_path / "results" / "opportunity_radar.md").read_text(encoding="utf-8")
    assert exit_status == 0
    assert "INTERESTED: 1" in lines
    assert "DISMISSED: 1" in lines
    assert r"apply\.json" in radar
    assert r"skip\.json" not in radar
