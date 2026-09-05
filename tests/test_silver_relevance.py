from src.silver.relevance import (
    get_accessibility_matches,
    get_employer_origin_minimum_evidence_reason,
    get_role_matches,
    get_silver_decision_reason,
    get_skill_matches,
    has_ats_backed_provider_identity,
    has_employer_origin_minimum_evidence,
    is_relevant_for_silver,
)


def make_finanz_raw_job(title: str, profile_terms: list[str]) -> dict:
    return {
        "id": 10132,
        "source_name": "finanz_informatik:hannover",
        "source_url": "https://www.f-i.de/de/karriere/offene-stellen/hannover/example",
        "raw_data": {
            "source_family": "finanz_informatik",
            "source_target": "hannover",
            "result_card": {
                "title": title,
                "company_name": "Finanz Informatik GmbH & Co. KG",
                "location": "Hannover",
                "detail_url": "https://www.f-i.de/de/karriere/offene-stellen/hannover/example",
            },
            "job": {
                "title": title,
                "company_name": "Finanz Informatik GmbH & Co. KG",
                "location": "Hannover",
                "source_url": "https://www.f-i.de/de/karriere/offene-stellen/hannover/example",
                "profile_terms": profile_terms,
            },
            "detail_evidence": {
                "page_title": f"{title} - Finanz Informatik",
            },
        },
    }


def test_finanz_product_owner_candidate_is_relevant_for_silver() -> None:
    raw_job = make_finanz_raw_job(
        title="Product Owner OSPlus Versiegelung (m/w/d)",
        profile_terms=["data", "daten", "bi", "product owner"],
    )

    assert "product owner" in get_role_matches(raw_job)
    assert "hannover" in get_accessibility_matches(raw_job)
    assert is_relevant_for_silver(raw_job)


def test_finanz_software_entwickler_candidate_matches_hyphenated_role() -> None:
    raw_job = make_finanz_raw_job(
        title="Software-Entwickler (m/w/d)",
        profile_terms=["software", "entwickler", "data", "ki"],
    )

    assert "software entwickler" in get_role_matches(raw_job)
    assert "hannover" in get_accessibility_matches(raw_job)
    assert is_relevant_for_silver(raw_job)


def test_finanz_javascript_ui_candidate_uses_connector_profile_evidence() -> None:
    raw_job = make_finanz_raw_job(
        title="Java-Script und UI-Entwickler (m/w/d)",
        profile_terms=["javascript", "ui", "sql"],
    )

    assert "ui entwickler" in get_role_matches(raw_job)
    assert {"javascript", "java script", "ui"}.intersection(get_skill_matches(raw_job))
    assert "hannover" in get_accessibility_matches(raw_job)
    assert is_relevant_for_silver(raw_job)


def test_ml_engineer_short_title_is_relevant_for_silver() -> None:
    raw_job = make_finanz_raw_job(
        title="ML Engineer (m/w/d)",
        profile_terms=["python", "pytorch", "remote"],
    )
    raw_job["raw_data"]["job"]["location"] = "Remote Germany"
    raw_job["raw_data"]["result_card"]["location"] = "Remote Germany"

    assert "ml engineer" in get_role_matches(raw_job)
    assert "remote" in get_accessibility_matches(raw_job)
    assert is_relevant_for_silver(raw_job)


def test_mlops_engineer_is_relevant_for_silver() -> None:
    raw_job = make_finanz_raw_job(
        title="MLOps Engineer (m/w/d)",
        profile_terms=["kubernetes", "model monitoring"],
    )

    assert "mlops engineer" in get_role_matches(raw_job)
    assert {"kubernetes", "model monitoring"}.issubset(set(get_skill_matches(raw_job)))
    assert is_relevant_for_silver(raw_job)


def test_ai_reliability_engineer_is_relevant_for_silver() -> None:
    raw_job = make_finanz_raw_job(
        title="AI Reliability Engineer (m/w/d)",
        profile_terms=["observability", "model drift", "python"],
    )

    assert "ai reliability engineer" in get_role_matches(raw_job)
    assert {"observability", "model drift"}.issubset(set(get_skill_matches(raw_job)))
    assert is_relevant_for_silver(raw_job)


def make_moia_unsolicited_raw_job(
    *,
    raw_job_id: int,
    external_job_id: str,
    title: str,
    content: str,
) -> dict:
    return {
        "id": raw_job_id,
        "source_name": "greenhouse:moia",
        "external_job_id": external_job_id,
        "source_url": "https://boards.greenhouse.io/moia/jobs",
        "raw_data": {
            "board_token": "moia",
            "job": {
                "id": int(external_job_id),
                "title": title,
                "absolute_url": f"https://boards.greenhouse.io/moia/jobs/{external_job_id}",
                "location": {"name": "Berlin"},
                "content": content,
                "first_published": "2026-09-01T10:00:00Z",
            },
        },
    }


def test_employer_origin_strong_description_allows_empty_roles_and_skills() -> None:
    raw_job = make_moia_unsolicited_raw_job(
        raw_job_id=8301,
        external_job_id="71001",
        title="Unsolicited Application - Business (all genders)",
        content=(
            "This employer-origin vacancy invites candidates to submit an unsolicited "
            "business application for future teams in Berlin."
        ),
    )

    assert get_role_matches(raw_job) == []
    assert get_skill_matches(raw_job) == []
    assert is_relevant_for_silver(raw_job) is True
    assert get_silver_decision_reason(raw_job) == "employer_origin_strong_canonical_evidence"
    assert get_employer_origin_minimum_evidence_reason(raw_job) == (
        "employer_origin_strong_canonical_evidence"
    )


def test_greenhouse_moia_unsolicited_live_fixture_jobs_are_relevant_for_silver() -> None:
    raw_jobs = [
        make_moia_unsolicited_raw_job(
            raw_job_id=8302,
            external_job_id="71002",
            title="Unsolicited Application - Business (all genders)",
            content=(
                "MOIA invites unsolicited applications for future business-facing "
                "openings based from Berlin and Hamburg."
            ),
        ),
        make_moia_unsolicited_raw_job(
            raw_job_id=8303,
            external_job_id="71003",
            title="Unsolicited Application - Tech & Product (all genders)",
            content=(
                "MOIA invites unsolicited applications for future technology and "
                "product openings based from Berlin and Hamburg."
            ),
        ),
    ]

    for raw_job in raw_jobs:
        assert get_role_matches(raw_job) == []
        assert get_skill_matches(raw_job) == []
        assert is_relevant_for_silver(raw_job) is True


def test_employer_origin_listing_card_description_is_not_strong_evidence() -> None:
    raw_job = {
        "id": 8401,
        "source_name": "computacenter:discovery",
        "external_job_id": "weak-listing-1",
        "source_url": "https://jobs.example.test/weak-listing-1",
        "raw_data": {
            "source_type": "employer_origin_career_site",
            "result_card": {
                "title": "General Opening",
                "company_name": "Computacenter AG & Co. oHG",
                "location": "Berlin",
                "detail_url": "https://jobs.example.test/weak-listing-1",
                "description": (
                    "Listing card teaser only. It should not be enough to create a "
                    "Silver vacancy without a detail description."
                ),
            },
            "job": {
                "title": "General Opening",
                "company_name": "Computacenter AG & Co. oHG",
                "location": "Berlin",
                "source_url": "https://jobs.example.test/weak-listing-1",
            },
        },
    }

    assert get_role_matches(raw_job) == []
    assert get_skill_matches(raw_job) == []
    assert is_relevant_for_silver(raw_job) is False
    assert get_silver_decision_reason(raw_job) == "missing_role_or_skill_signal"


def test_employer_origin_missing_description_still_fails_quality_policy() -> None:
    raw_job = {
        "id": 8402,
        "source_name": "computacenter:discovery",
        "external_job_id": "generic-origin-1",
        "source_url": "https://jobs.example.test/generic-origin-1",
        "raw_data": {
            "source_type": "employer_origin_career_site",
            "job": {
                "title": "General Opening",
                "company_name": "Computacenter AG & Co. oHG",
                "location": "Berlin",
                "source_url": "https://jobs.example.test/generic-origin-1",
            },
        },
    }

    assert get_role_matches(raw_job) == []
    assert get_skill_matches(raw_job) == []
    assert is_relevant_for_silver(raw_job) is False


def test_aggregator_behavior_unchanged_for_empty_roles_and_skills() -> None:
    raw_job = {
        "id": 8403,
        "source_name": "stepstone",
        "external_job_id": "stepstone-weak-1",
        "source_url": "https://www.stepstone.de/jobs/general-opening/in-berlin",
        "raw_data": {
            "result_card": {
                "title": "General Opening",
                "company_name": "Example GmbH",
                "location": "Berlin",
                "detail_url": "https://www.stepstone.de/jobs/general-opening/in-berlin",
            },
            "job": {
                "title": "General Opening",
                "company_name": "Example GmbH",
                "location": "Berlin",
                "description": (
                    "A general aggregator listing with no structured career or skill "
                    "evidence remains outside Silver."
                ),
            },
        },
    }

    assert get_role_matches(raw_job) == []
    assert get_skill_matches(raw_job) == []
    assert is_relevant_for_silver(raw_job) is False


def make_live_greenhouse_moia_raw_job_shape(
    *,
    raw_job_id: int = 1,
    external_job_id: str = "4967879101",
    title: str = "Unsolicited Application – Business (all genders) ",
) -> dict:
    return {
        "id": raw_job_id,
        "source_name": "greenhouse:moia",
        "external_job_id": external_job_id,
        "source_url": f"https://job-boards.eu.greenhouse.io/moia/jobs/{external_job_id}",
        "raw_data": {
            "board_token": "moia",
            "matching": {
                "matched_search_term_ids": [130],
                "matched_terms": ["*"],
                "matching_mode": "field_scoped_case_insensitive_term_match",
            },
            "job": {
                "absolute_url": (
                    f"https://job-boards.eu.greenhouse.io/moia/jobs/{external_job_id}"
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
                "first_published": "2026-09-03T12:13:53+00:00",
                "id": int(external_job_id),
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
                "title": title,
                "updated_at": "2026-09-03T12:13:53+00:00",
            },
        },
    }


def test_live_greenhouse_moia_shape_uses_ats_provider_identity_without_description() -> None:
    raw_job = make_live_greenhouse_moia_raw_job_shape()

    assert get_role_matches(raw_job) == []
    assert get_skill_matches(raw_job) == []
    assert get_accessibility_matches(raw_job) == [
        "germany",
        "hannover",
        "berlin",
        "hamburg",
        "munich",
    ]
    assert has_ats_backed_provider_identity(raw_job) is True
    assert has_employer_origin_minimum_evidence(raw_job) is True
    assert get_employer_origin_minimum_evidence_reason(raw_job) == (
        "employer_origin_ats_provider_identity_evidence"
    )
    assert get_silver_decision_reason(raw_job) == (
        "employer_origin_ats_provider_identity_evidence"
    )
    assert is_relevant_for_silver(raw_job) is True
