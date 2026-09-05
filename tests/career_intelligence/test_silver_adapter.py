import pytest

from src.career_intelligence.silver_adapter import (
    ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY,
    adapt_silver_row,
    adapt_silver_rows,
    extract_description,
    has_ats_backed_provider_identity,
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
                "data_compliance": [
                    {
                        "demographic_data_consent_applies": False,
                        "requires_consent": False,
                        "requires_processing_consent": False,
                        "requires_retention_consent": False,
                        "retention_period": None,
                        "type": "gdpr",
                    }
                ],
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


def test_live_greenhouse_moia_missing_description_uses_ats_provider_identity():
    row = live_greenhouse_moia_silver_row()

    assert extract_description(row["raw_data"]) == (None, None, "missing")
    assert has_ats_backed_provider_identity(row) is True

    result = adapt_silver_row(row)

    assert result.company == "MOIA GmbH"
    assert result.title == "Unsolicited Application – Business (all genders)"
    assert result.description == ""
    assert result.description_quality == ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY
    assert result.provenance["description_source"] is None
    assert result.provenance["description_quality"] == (
        ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY
    )
    assert result.provenance["ingestion_status"] == "assessed"
    assert result.provenance["canonical_source_type"] == (
        "employer_origin_ats_backed_career_site"
    )


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
