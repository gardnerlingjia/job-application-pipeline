import json

import pytest

from src.career_intelligence.batch import RESULT_FIELDS
from src.career_intelligence.ingest_silver import (
    PROVENANCE_FILE,
    assess_silver_inputs,
    parse_args,
    process_silver,
)
from src.career_intelligence.silver_adapter import (
    ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY,
    adapt_silver_row,
    source_file_for_row,
)


def silver_row(**overrides):
    row = {
        "silver_job_id": 42,
        "raw_job_id": 1001,
        "source_name": "personio:example",
        "external_job_id": "job-123",
        "source_url": "https://jobs.example.test/job-123",
        "title": "Senior Data Engineer",
        "company_name": "Example GmbH",
        "city": "Hannover",
        "postal_code": None,
        "country": "DE",
        "canonical_source_type": "unknown",
        "canonical_key_candidate": "example gmbh :: senior data engineer :: hannover | de",
        "raw_data": {
            "job": {
                "description": "Build reliable Python and SQL data platforms in a hybrid setup.",
            }
        },
    }
    row.update(overrides)
    return row


def fake_assessment(company, title, description):
    return {
        "company_name": company,
        "title": title,
        "career_lane": "data",
        "career_lane_label": "Data",
        "opportunity_score": 80,
        "recommendation": "EXPLORE",
        "constraint_action": "CLEAR",
        "hard_skips": [],
        "high_risks": [],
        "reviews": [],
        "matched_capabilities": ["python", "sql"],
        "domain_matches": ["data platform"],
        "evidence_details": [{"capability": "python"}],
        "network_access": 0,
        "scores": {
            "career_lane_fit": 70,
            "capability_fit": 80,
            "domain_fit": 60,
            "location_fit": 40,
            "network_access": 0,
            "evidence_strength": 70,
        },
    }


def test_integration_assesses_silver_rows_with_existing_result_schema(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append((company, title, description))
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository([silver_row()]),
        results=tmp_path,
    )

    assert summary["processed"] == 1
    assert calls == [
        (
            "Example GmbH",
            "Senior Data Engineer",
            "Build reliable Python and SQL data platforms in a hybrid setup.",
        )
    ]
    result = summary["opportunities"][0]
    assert set(result) == RESULT_FIELDS
    assert result["source_file"] == source_file_for_row(silver_row())
    persisted = json.loads((tmp_path / "opportunities.json").read_text())
    assert set(persisted[0]) == RESULT_FIELDS


def test_old_silver_job_receives_freshness_ranking_penalty(tmp_path, monkeypatch):
    def assess(company, title, description):
        result = fake_assessment(company, title, description)
        result["opportunity_score"] = 80
        result["recommendation"] = "APPLY_NOW"
        result["constraint_action"] = "CLEAR"
        result["network_access"] = 70
        return result

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository([silver_row(publication_date="2000-01-01")]),
        results=tmp_path,
    )

    result = summary["opportunities"][0]
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())[0]
    assert result["opportunity_score"] == 65
    assert provenance["base_opportunity_score"] == 80
    assert provenance["freshness_adjusted_opportunity_score"] == 65
    assert provenance["freshness_bucket"] == "OLD"
    assert provenance["freshness_ranking_penalty"] == 15


def test_missing_dates_are_not_fabricated_or_penalized(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.career_intelligence.ingest_silver.assess_opportunity",
        fake_assessment,
    )

    summary = process_silver(repository=FakeRepository([silver_row()]), results=tmp_path)

    result = summary["opportunities"][0]
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())[0]
    assert result["opportunity_score"] == 80
    assert provenance["publication_date"] is None
    assert provenance["first_seen_at"] is None
    assert provenance["last_seen_at"] is None
    assert provenance["job_age_days"] is None
    assert provenance["freshness_bucket"] == "UNKNOWN"
    assert provenance["freshness_ranking_penalty"] == 0


def test_provenance_is_preserved_in_sidecar_without_changing_public_results(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.career_intelligence.ingest_silver.assess_opportunity",
        fake_assessment,
    )

    summary = process_silver(repository=FakeRepository([silver_row()]), results=tmp_path)

    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())
    assert provenance == summary["provenance"]
    assert provenance[0]["source_file"] == summary["opportunities"][0]["source_file"]
    assert provenance[0]["silver_job_id"] == 42
    assert provenance[0]["raw_job_id"] == 1001
    assert provenance[0]["source_url"] == "https://jobs.example.test/job-123"
    assert provenance[0]["description_quality"] == "strong"
    assert provenance[0]["description_source"] == "job.description"
    assert provenance[0]["ingestion_status"] == "assessed"
    assert "stable_identity_sha256" in provenance[0]


def test_profile_terms_only_record_is_not_scored(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append((company, title, description))
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository(
            [
                silver_row(
                    raw_data={
                        "job": {
                            "profile_terms": ["python", "sql"],
                        }
                    }
                )
            ]
        ),
        results=tmp_path,
    )

    assert calls == []
    assert summary["processed"] == 0
    assert "description" in summary["errors"][0]["error"]
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())
    assert provenance[0]["description_quality"] == "missing"
    assert provenance[0]["description_source"] is None
    assert provenance[0]["ingestion_status"] == "skipped"


def test_weak_listing_only_record_is_not_normally_scored(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append((company, title, description))
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository(
            [
                silver_row(
                    raw_data={
                        "listing_evidence": {
                            "listing_text": "Python SQL data role teaser.",
                        }
                    }
                )
            ]
        ),
        results=tmp_path,
    )

    assert calls == []
    assert summary["processed"] == 0
    assert summary["errors"][0]["error"] == (
        "insufficient description evidence: weak listing/card text is not scored"
    )
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())
    assert provenance[0]["description_source"] == "listing_evidence.listing_text"
    assert provenance[0]["description_quality"] == "weak"
    assert provenance[0]["ingestion_status"] == "skipped"


def test_strong_detail_description_record_is_scored(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append(description)
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository(
            [
                silver_row(
                    raw_data={
                        "detail_evidence": {
                            "description": "Full detail text for Python and SQL platform work.",
                        }
                    }
                )
            ]
        ),
        results=tmp_path,
    )

    assert summary["processed"] == 1
    assert calls == ["Full detail text for Python and SQL platform work."]
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())
    assert provenance[0]["description_source"] == "detail_evidence.description"
    assert provenance[0]["description_quality"] == "strong"


def live_greenhouse_moia_silver_row(**overrides):
    row = {
        "silver_job_id": 1,
        "raw_job_id": 1,
        "source_name": "greenhouse:moia",
        "external_job_id": "4967879101",
        "source_url": "https://job-boards.eu.greenhouse.io/moia/jobs/4967879101",
        "title": "Unsolicited Application – Business (all genders) ",
        "company_name": "MOIA GmbH",
        "city": (
            "Berlin, Germany; Hamburg, Germany; Hannover, Germany; "
            "Munich, Germany; Wolfsburg, Germany"
        ),
        "postal_code": None,
        "country": None,
        "publication_date": "2026-09-03",
        "first_seen_at": "2026-09-03T13:10:00+00:00",
        "last_seen_at": "2026-09-03T13:10:00+00:00",
        "canonical_source_type": "employer_origin_ats_backed_career_site",
        "canonical_key_candidate": (
            "moia gmbh :: unsolicited application – business (all genders) :: "
            "berlin, germany; hamburg, germany; hannover, germany; munich, "
            "germany; wolfsburg, germany"
        ),
        "raw_data": {
            "board_token": "moia",
            "matching": {
                "matched_search_term_ids": [130],
                "matched_terms": ["*"],
                "matching_mode": "field_scoped_case_insensitive_term_match",
            },
            "job": {
                "absolute_url": (
                    "https://job-boards.eu.greenhouse.io/moia/jobs/4967879101"
                ),
                "application_deadline": None,
                "company_name": "MOIA GmbH",
                "first_published": "2026-09-03T09:00:20-04:00",
                "id": 4967879101,
                "internal_job_id": 6413596,
                "language": "en",
                "location": {
                    "name": (
                        "Berlin, Germany; Hamburg, Germany; Hannover, Germany; "
                        "Munich, Germany; Wolfsburg, Germany"
                    )
                },
                "metadata": None,
                "requisition_id": "6413596",
                "title": "Unsolicited Application – Business (all genders) ",
                "updated_at": "2026-09-03T09:00:20-04:00",
            },
        },
    }
    row.update(overrides)
    return row


def test_ats_backed_missing_description_record_is_conservatively_scored(
    tmp_path,
    monkeypatch,
):
    calls = []

    def assess(company, title, description):
        calls.append((company, title, description))
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    summary = process_silver(
        repository=FakeRepository([live_greenhouse_moia_silver_row()]),
        results=tmp_path,
    )

    assert summary["converted"] == 1
    assert summary["processed"] == 1
    assert calls == [
        (
            "MOIA GmbH",
            "Unsolicited Application – Business (all genders)",
            "",
        )
    ]
    result = summary["opportunities"][0]
    assert result["key_matched_capabilities"] == []
    assert result["opportunity_score"] < 80
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())[0]
    assert provenance["description_quality"] == ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY
    assert provenance["description_source"] is None
    assert provenance["missing_description_evidence_policy"] == (
        "ats_provider_identity_only_no_capability_or_domain_evidence"
    )


def test_duplicate_records_in_same_run_are_reported_once(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append(company)
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)
    item = adapt_silver_row(silver_row())

    summary = assess_silver_inputs([item, item], results=tmp_path)

    assert summary["processed"] == 1
    assert len(calls) == 1
    assert summary["errors"] == [
        {
            "record": item.source_file,
            "error": "duplicate Silver source identity in this run",
        }
    ]


def test_failure_preparing_provenance_does_not_update_opportunities(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.career_intelligence.ingest_silver.assess_opportunity",
        fake_assessment,
    )
    process_silver(repository=FakeRepository([silver_row()]), results=tmp_path)
    opportunities_before = (tmp_path / "opportunities.json").read_bytes()
    (tmp_path / PROVENANCE_FILE).write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        process_silver(
            repository=FakeRepository(
                [silver_row(raw_job_id=1002, external_job_id="job-124")]
            ),
            results=tmp_path,
        )

    assert (tmp_path / "opportunities.json").read_bytes() == opportunities_before


def test_paired_output_write_failure_leaves_final_files_uncreated(
    tmp_path,
    monkeypatch,
):
    calls = []
    from src.career_intelligence import ingest_silver

    original_write_temporary = ingest_silver._write_temporary

    def fail_on_provenance(directory, content):
        calls.append(content)
        if len(calls) == 3:
            raise OSError("disk full")
        return original_write_temporary(directory, content)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", fake_assessment)
    monkeypatch.setattr(
        "src.career_intelligence.ingest_silver._write_temporary",
        fail_on_provenance,
    )

    with pytest.raises(OSError, match="disk full"):
        process_silver(repository=FakeRepository([silver_row()]), results=tmp_path)

    assert not (tmp_path / "opportunities.json").exists()
    assert not (tmp_path / "opportunity_radar.md").exists()
    assert not (tmp_path / PROVENANCE_FILE).exists()


def test_stable_rerun_skips_existing_silver_identity(tmp_path, monkeypatch):
    calls = []

    def assess(company, title, description):
        calls.append(company)
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)
    first = adapt_silver_row(silver_row())
    second = adapt_silver_row(silver_row(title="Renamed Data Engineer"))

    first_summary = assess_silver_inputs([first], results=tmp_path)
    second_summary = assess_silver_inputs([second], results=tmp_path)

    assert first_summary["processed"] == 1
    assert second_summary["processed"] == 0
    assert second_summary["skipped_existing"] == 1
    assert calls == ["Example GmbH"]
    persisted = json.loads((tmp_path / "opportunities.json").read_text())
    assert len(persisted) == 1
    assert persisted[0]["title"] == "Senior Data Engineer"


def test_stable_rerun_refreshes_freshness_penalty_without_reassessing(
    tmp_path,
    monkeypatch,
):
    calls = []

    def assess(company, title, description):
        calls.append(company)
        return fake_assessment(company, title, description)

    monkeypatch.setattr("src.career_intelligence.ingest_silver.assess_opportunity", assess)

    first_summary = process_silver(
        repository=FakeRepository([silver_row(publication_date="2999-01-01")]),
        results=tmp_path,
    )
    second_summary = process_silver(
        repository=FakeRepository([silver_row(publication_date="2000-01-01")]),
        results=tmp_path,
    )

    persisted = json.loads((tmp_path / "opportunities.json").read_text())
    provenance = json.loads((tmp_path / PROVENANCE_FILE).read_text())
    assert first_summary["processed"] == 1
    assert second_summary["processed"] == 0
    assert second_summary["skipped_existing"] == 1
    assert calls == ["Example GmbH"]
    assert persisted[0]["opportunity_score"] == 65
    assert provenance[0]["base_opportunity_score"] == 80
    assert provenance[0]["freshness_bucket"] == "OLD"
    assert provenance[0]["freshness_adjusted_opportunity_score"] == 65


def test_bad_silver_record_does_not_stop_valid_assessment(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.career_intelligence.ingest_silver.assess_opportunity",
        fake_assessment,
    )

    summary = process_silver(
        repository=FakeRepository([silver_row(raw_data={"job": {}}), silver_row(raw_job_id=2)]),
        results=tmp_path,
    )

    assert summary["loaded"] == 2
    assert summary["converted"] == 1
    assert summary["processed"] == 1
    assert "description" in summary["errors"][0]["error"]


def test_cli_parser_uses_repository_path_conventions():
    args = parse_args(["--source", "personio", "--limit", "7", "--results", "jobs/results"])

    assert args.source == "personio"
    assert args.limit == 7
    assert str(args.results) == "jobs/results"


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def load_silver_jobs(self, *, limit, source_patterns):
        self.calls.append({"limit": limit, "source_patterns": source_patterns})
        return self.rows
