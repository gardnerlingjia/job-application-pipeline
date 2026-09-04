import json
from pathlib import Path

from src.career_intelligence.control_center import (
    load_career_intelligence_control_center,
    merge_career_intelligence_payload,
)
from src.career_intelligence.operator_state import set_operator_state


def _opportunity(source_file: str, *, score: int = 88, recommendation: str = "APPLY_NOW"):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "company": "Example GmbH",
        "title": "Data Engineer",
        "career_lane": "data_platform",
        "career_lane_label": "Data Platform",
        "opportunity_score": score,
        "recommendation": recommendation,
        "constraint_action": "CLEAR",
        "risks": [{"constraint": "location", "reason": "hybrid"}],
        "key_matched_capabilities": [{"name": "Python"}],
    }


def _provenance(source_file: str, *, silver_job_id: int | None = 42):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "ingestion_status": "assessed",
        "stable_identity_type": "source_name_external_job_id",
        "stable_identity_sha256": "a" * 64,
        "description_source": "raw_data.job.description",
        "description_quality": "strong",
        "silver_job_id": silver_job_id,
        "raw_job_id": 7,
        "source_name": "personio:target",
        "external_job_id": "abc-123",
        "source_url": "https://jobs.example.test/abc-123",
    }


def _write_runtime(
    root: Path,
    opportunities: list[dict[str, object]],
    provenance: list[dict[str, object]],
) -> Path:
    results = root / "jobs" / "results"
    results.mkdir(parents=True)
    (results / "opportunities.json").write_text(
        json.dumps(opportunities) + "\n",
        encoding="utf-8",
    )
    (results / "silver_ingestion_provenance.json").write_text(
        json.dumps(provenance) + "\n",
        encoding="utf-8",
    )
    return results


def test_control_center_read_model_joins_by_silver_provenance(tmp_path):
    results = _write_runtime(
        tmp_path,
        [_opportunity("silver-a.json")],
        [_provenance("silver-a.json")],
    )
    product_payload = {
        "job_readiness": [{"silver_job_id": 42, "title": "Product row"}],
        "top_jobs": [],
    }

    payload = load_career_intelligence_control_center(product_payload, results=results)

    assert payload["available"] is True
    record = payload["records"][0]
    assert record["silver_job_id"] == 42
    assert record["job_join_status"] == "joined"
    assert record["workspace_available"] is True
    assert record["operator_state"] == "NEW"
    assert record["network_access"] is None
    assert record["network_status"] == "not_available_in_v1_1_result_schema"
    assert payload["by_silver_job_id"]["42"]["source_file"] == "silver-a.json"


def test_control_center_read_model_handles_missing_runtime_files(tmp_path):
    payload = load_career_intelligence_control_center(
        {"job_readiness": [], "top_jobs": []},
        results=tmp_path / "missing",
    )

    assert payload["available"] is False
    assert payload["status"] == "not_run"
    assert payload["records"] == []


def test_control_center_read_model_fails_safely_on_malformed_runtime(tmp_path):
    results = tmp_path / "jobs" / "results"
    results.mkdir(parents=True)
    (results / "opportunities.json").write_text("{broken", encoding="utf-8")

    payload = load_career_intelligence_control_center(
        {"job_readiness": [], "top_jobs": []},
        results=results,
    )

    assert payload["available"] is False
    assert payload["status"] == "error"
    assert "JSONDecodeError" in payload["reason"]


def test_control_center_read_model_preserves_operator_state_and_provenance(tmp_path):
    results = _write_runtime(
        tmp_path,
        [_opportunity("silver-a.json", recommendation="NETWORK_FIRST")],
        [_provenance("silver-a.json")],
    )
    state_path = tmp_path / ".runtime" / "career_intelligence" / "operator_state.json"
    set_operator_state(source_file="silver-a.json", state="INTERESTED", path=state_path)

    payload = load_career_intelligence_control_center(
        {"job_readiness": [{"silver_job_id": 42}], "top_jobs": []},
        results=results,
        state_path=state_path,
    )

    record = payload["records"][0]
    assert record["operator_state"] == "INTERESTED"
    assert record["provenance"]["source_name"] == "personio:target"
    assert record["provenance"]["external_job_id"] == "abc-123"
    assert record["provenance"]["description_quality"] == "strong"
    assert payload["summary"]["operator_state_counts"]["INTERESTED"] == 1


def test_merge_career_intelligence_payload_preserves_product_v1_ordering(tmp_path):
    results = _write_runtime(
        tmp_path,
        [_opportunity("silver-a.json", score=99), _opportunity("silver-b.json", score=10)],
        [_provenance("silver-a.json", silver_job_id=2), _provenance("silver-b.json", silver_job_id=1)],
    )
    product_payload = {
        "summary": {},
        "boundaries": {},
        "job_readiness": [{"silver_job_id": 1}, {"silver_job_id": 2}],
        "top_jobs": [{"silver_job_id": 1}],
    }
    career = load_career_intelligence_control_center(product_payload, results=results)

    merged = merge_career_intelligence_payload(product_payload, career)

    assert [job["silver_job_id"] for job in merged["job_readiness"]] == [1, 2]
    assert [job["silver_job_id"] for job in merged["top_jobs"]] == [1]
    assert merged["job_readiness"][0]["career_intelligence"]["source_file"] == "silver-b.json"
    assert merged["job_readiness"][1]["career_intelligence"]["source_file"] == "silver-a.json"
    assert merged["boundaries"]["career_intelligence_is_not_product_v1_ranking_authority"] is True
