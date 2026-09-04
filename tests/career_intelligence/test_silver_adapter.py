import pytest

from src.career_intelligence.silver_adapter import (
    adapt_silver_row,
    adapt_silver_rows,
    extract_description,
    normalize_source_patterns,
    source_file_for_row,
    stable_identity,
)


def silver_row(**overrides):
    row = {
        "silver_job_id": 42,
        "raw_job_id": 1001,
        "source_name": "personio:example",
        "external_job_id": "job-123",
        "source_url": "https://jobs.example.test/job-123",
        "title": " Senior Data Engineer ",
        "company_name": " Example GmbH ",
        "city": "Hannover",
        "postal_code": None,
        "country": "DE",
        "canonical_source_type": "unknown",
        "canonical_key_candidate": "example gmbh :: senior data engineer :: hannover | de",
        "raw_data": {
            "job": {
                "description": " Build reliable Python and SQL data platforms. ",
            }
        },
    }
    row.update(overrides)
    return row


def test_valid_silver_record_conversion_preserves_required_fields_and_source_identity():
    result = adapt_silver_row(silver_row())

    assert result.company == "Example GmbH"
    assert result.title == "Senior Data Engineer"
    assert result.description == "Build reliable Python and SQL data platforms."
    assert result.source_file.startswith("silver-personio-example-")
    assert result.source_file.endswith(".json")
    assert result.provenance["silver_job_id"] == 42
    assert result.provenance["raw_job_id"] == 1001
    assert result.provenance["source_name"] == "personio:example"
    assert result.provenance["external_job_id"] == "job-123"
    assert result.provenance["description_source"] == "job.description"
    assert result.provenance["description_quality"] == "strong"
    assert result.provenance["ingestion_status"] == "assessed"
    assert result.provenance["stable_identity_type"] == "source_name_external_job_id"
    assert result.provenance["freshness_bucket"] == "UNKNOWN"
    assert result.provenance["publication_date"] is None
    assert result.provenance["job_age_date_source"] is None


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("company_name", "company"),
        ("title", "title"),
    ),
)
def test_missing_silver_required_fields_are_reported(field, message):
    row = silver_row(**{field: " "})

    with pytest.raises(ValueError, match=message):
        adapt_silver_row(row)


def test_missing_description_is_reported_without_stopping_other_rows():
    valid = silver_row(raw_job_id=1002, external_job_id="job-124")
    invalid = silver_row(raw_data={"job": {}})

    inputs, errors = adapt_silver_rows([invalid, valid])

    assert len(inputs) == 1
    assert inputs[0].source_file == source_file_for_row(valid)
    assert errors[0]["record"] == "42"
    assert "description" in errors[0]["error"]


def test_malformed_record_is_reported_without_stopping_other_rows():
    valid = silver_row(raw_job_id=1002, external_job_id="job-124")

    inputs, errors = adapt_silver_rows([["not", "a", "row"], valid])

    assert len(inputs) == 1
    assert errors == [
        {
            "record": "unknown",
            "index": "0",
            "error": "Silver row must be an object",
        }
    ]


def test_extract_description_marks_listing_evidence_as_weak():
    description, source, quality = extract_description(
        {
            "listing_evidence": {
                "listing_text": "Cloud platform role with hybrid work.",
            }
        }
    )

    assert description == "Cloud platform role with hybrid work."
    assert source == "listing_evidence.listing_text"
    assert quality == "weak"


def test_profile_terms_are_never_used_as_description():
    description, source, quality = extract_description({"job": {"profile_terms": ["data", "ai"]}})

    assert description is None
    assert source is None
    assert quality == "missing"


def test_weak_listing_only_record_is_reported_as_insufficient_evidence():
    inputs, errors = adapt_silver_rows(
        [
            silver_row(
                raw_data={
                    "listing_evidence": {
                        "listing_text": "Cloud platform role with hybrid work.",
                    }
                }
            )
        ]
    )

    assert inputs == []
    assert errors[0]["error"] == (
        "insufficient description evidence: weak listing/card text is not scored"
    )
    assert errors[0]["provenance"]["description_source"] == "listing_evidence.listing_text"
    assert errors[0]["provenance"]["description_quality"] == "weak"
    assert errors[0]["provenance"]["ingestion_status"] == "skipped"


def test_strong_detail_description_record_is_scorable():
    result = adapt_silver_row(
        silver_row(
            raw_data={
                "detail_evidence": {
                    "text": "Permanent data platform role with Python and SQL.",
                }
            }
        )
    )

    assert result.description == "Permanent data platform role with Python and SQL."
    assert result.description_quality == "strong"
    assert result.provenance["description_source"] == "detail_evidence.text"


def test_greenhouse_job_content_is_strong_description_evidence_for_live_moia():
    result = adapt_silver_row(
        silver_row(
            source_name="greenhouse:moia",
            company_name="MOIA",
            title="Technical Program Lead",
            raw_data={
                "job": {
                    "content": "Lead autonomous mobility programs across Berlin teams.",
                }
            },
        )
    )

    assert result.description == "Lead autonomous mobility programs across Berlin teams."
    assert result.description_quality == "strong"
    assert result.provenance["description_source"] == "job.content"
    assert result.provenance["source_name"] == "greenhouse:moia"


def test_publication_date_is_preserved_separately_from_first_and_last_seen():
    result = adapt_silver_row(
        silver_row(
            publication_date="2026-09-01",
            first_seen_at="2026-09-03T08:00:00+00:00",
            last_seen_at="2026-09-04T08:00:00+00:00",
        )
    )

    assert result.provenance["publication_date"] == "2026-09-01"
    assert result.provenance["first_seen_at"] == "2026-09-03T08:00:00+00:00"
    assert result.provenance["last_seen_at"] == "2026-09-04T08:00:00+00:00"
    assert result.provenance["job_age_date_source"] == "publication_date"


def test_stable_identity_prefers_source_name_and_external_job_id():
    assert stable_identity(silver_row()) == (
        "source_name_external_job_id",
        "personio:example\0job-123",
    )


def test_stable_identity_uses_raw_job_id_fallback_when_external_id_is_missing():
    assert stable_identity(silver_row(external_job_id=None)) == ("raw_job_id", "1001")


def test_source_file_is_stable_for_same_source_identity():
    first = source_file_for_row(silver_row(title="Data Engineer"))
    second = source_file_for_row(silver_row(title="Data Platform Engineer"))

    assert first == second


def test_normalize_source_patterns_matches_silver_cli_conventions():
    assert normalize_source_patterns(None) == []
    assert normalize_source_patterns("personio") == ["personio:%"]
    assert normalize_source_patterns("personio:example") == ["personio:example"]
    assert normalize_source_patterns("personio:%") == ["personio:%"]
