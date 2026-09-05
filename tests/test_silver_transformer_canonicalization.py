from src.silver.transformer import (
    add_canonicalization_fields,
    build_canonical_key_candidate,
    build_normalized_location,
    get_supported_source_patterns,
    normalize_text,
    transform_raw_job_to_silver,
)


def test_normalize_text_strips_lowercases_and_collapses_whitespace() -> None:
    assert normalize_text("  Senior   Data Engineer  ") == "senior data engineer"


def test_normalize_text_returns_none_for_empty_or_non_string_values() -> None:
    assert normalize_text("") is None
    assert normalize_text("   ") is None
    assert normalize_text(None) is None
    assert normalize_text(123) is None


def test_build_normalized_location_joins_available_location_parts() -> None:
    assert (
        build_normalized_location(" Hannover ", " 30159 ", " DE ")
        == "hannover | 30159 | de"
    )


def test_build_normalized_location_ignores_missing_parts() -> None:
    assert build_normalized_location("Hannover", None, "") == "hannover"


def test_build_canonical_key_candidate_joins_available_parts() -> None:
    assert (
        build_canonical_key_candidate(
            "volkswagen ag",
            "data engineer",
            "hannover | de",
        )
        == "volkswagen ag :: data engineer :: hannover | de"
    )


def test_build_canonical_key_candidate_returns_none_without_parts() -> None:
    assert build_canonical_key_candidate(None, None, None) is None


def test_add_canonicalization_fields_sets_first_layer_defaults() -> None:
    job = {
        "title": "  Data Engineer  ",
        "company_name": " Volkswagen AG ",
        "city": " Hannover ",
        "postal_code": None,
        "country": " DE ",
    }

    result = add_canonicalization_fields(job)

    assert result["normalized_title"] == "data engineer"
    assert result["normalized_company_name"] == "volkswagen ag"
    assert result["normalized_location"] == "hannover | de"
    assert result["canonical_status"] == "discovery_only"
    assert result["canonical_source_type"] == "unknown"
    assert (
        result["canonical_key_candidate"]
        == "volkswagen ag :: data engineer :: hannover | de"
    )


def test_transform_personio_raw_job_uses_stable_bronze_job_fields() -> None:
    raw_job = {
        "id": 5959,
        "source_name": "personio:schluetersche-mediengruppe",
        "external_job_id": "2498694",
        "source_url": "https://schluetersche-mediengruppe.jobs.personio.de/xml?language=de",
        "raw_data": {
            "source_target": {
                "source_family": "personio",
                "target_key": "schluetersche-mediengruppe",
            },
            "job": {
                "id": "2498694",
                "title": "Data Engineer (m/w/d)",
                "company_name": "Schlütersche Verlagsgesellschaft mbH & Co. KG",
                "location": "Hannover",
                "source_url": (
                    "https://schluetersche-mediengruppe.jobs.personio.de"
                    "/job/2498694?language=de"
                ),
            },
            "source_specific": {
                "raw_position": {
                    "name": "Data Engineer (m/w/d)",
                },
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["raw_job_id"] == 5959
    assert result["source_name"] == "personio:schluetersche-mediengruppe"
    assert result["external_job_id"] == "2498694"
    assert result["source_url"] == (
        "https://schluetersche-mediengruppe.jobs.personio.de"
        "/job/2498694?language=de"
    )
    assert result["title"] == "Data Engineer (m/w/d)"
    assert result["company_name"] == "Schlütersche Verlagsgesellschaft mbH & Co. KG"
    assert result["city"] == "Hannover"
    assert result["postal_code"] is None
    assert result["country"] is None
    assert result["publication_date"] is None
    assert result["normalized_title"] == "data engineer (m/w/d)"
    assert (
        result["normalized_company_name"]
        == "schlütersche verlagsgesellschaft mbh & co. kg"
    )
    assert result["normalized_location"] == "hannover"
    assert result["canonical_status"] == "discovery_only"
    assert result["canonical_source_type"] == "unknown"
    assert result["canonical_key_candidate"] == (
        "schlütersche verlagsgesellschaft mbh & co. kg"
        " :: data engineer (m/w/d)"
        " :: hannover"
    )


def test_supported_source_patterns_include_personio() -> None:
    assert "personio:%" in get_supported_source_patterns()


def test_transform_greenhouse_moia_raw_job_uses_source_identity_fallbacks() -> None:
    raw_job = {
        "id": 8101,
        "source_name": "greenhouse:moia",
        "external_job_id": "12345",
        "source_url": "https://boards-api.greenhouse.io/v1/boards/moia/jobs",
        "raw_data": {
            "board_token": "moia",
            "job": {
                "id": 12345,
                "title": "Senior Technical Program Manager",
                "absolute_url": "https://boards.greenhouse.io/moia/jobs/12345",
                "location": {"name": "Berlin"},
                "content": "<p>Lead autonomous mobility programs with data teams.</p>",
                "first_published": "2026-09-01T10:00:00Z",
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["raw_job_id"] == 8101
    assert result["source_name"] == "greenhouse:moia"
    assert result["external_job_id"] == "12345"
    assert result["source_url"] == "https://boards.greenhouse.io/moia/jobs/12345"
    assert result["title"] == "Senior Technical Program Manager"
    assert result["company_name"] == "MOIA"
    assert result["city"] == "Berlin"
    assert result["canonical_source_type"] == "employer_origin_ats_backed_career_site"
    assert result["canonical_key_candidate"] == (
        "moia :: senior technical program manager :: berlin"
    )


def test_transform_greenhouse_moia_unsolicited_live_fixture_jobs() -> None:
    raw_jobs = [
        {
            "id": 8302,
            "source_name": "greenhouse:moia",
            "external_job_id": "71002",
            "source_url": "https://boards-api.greenhouse.io/v1/boards/moia/jobs",
            "raw_data": {
                "board_token": "moia",
                "job": {
                    "id": 71002,
                    "title": "Unsolicited Application - Business (all genders)",
                    "absolute_url": "https://boards.greenhouse.io/moia/jobs/71002",
                    "location": {"name": "Berlin"},
                    "content": (
                        "MOIA invites unsolicited applications for future business-facing "
                        "openings based from Berlin and Hamburg."
                    ),
                    "first_published": "2026-09-01T10:00:00Z",
                },
            },
        },
        {
            "id": 8303,
            "source_name": "greenhouse:moia",
            "external_job_id": "71003",
            "source_url": "https://boards-api.greenhouse.io/v1/boards/moia/jobs",
            "raw_data": {
                "board_token": "moia",
                "job": {
                    "id": 71003,
                    "title": "Unsolicited Application - Tech & Product (all genders)",
                    "absolute_url": "https://boards.greenhouse.io/moia/jobs/71003",
                    "location": {"name": "Berlin"},
                    "content": (
                        "MOIA invites unsolicited applications for future technology and "
                        "product openings based from Berlin and Hamburg."
                    ),
                    "first_published": "2026-09-01T10:00:00Z",
                },
            },
        },
    ]

    transformed = [transform_raw_job_to_silver(raw_job) for raw_job in raw_jobs]

    assert [job["title"] for job in transformed] == [
        "Unsolicited Application - Business (all genders)",
        "Unsolicited Application - Tech & Product (all genders)",
    ]
    assert {job["company_name"] for job in transformed} == {"MOIA"}
    assert {job["city"] for job in transformed} == {"Berlin"}
    assert {job["canonical_source_type"] for job in transformed} == {
        "employer_origin_ats_backed_career_site"
    }


def test_transform_stepstone_raw_job_uses_result_card_fields() -> None:
    raw_job = {
        "id": 6001,
        "source_name": "stepstone",
        "external_job_id": "123456",
        "source_url": "https://www.stepstone.de/jobs/data-engineer/in-hannover",
        "raw_data": {
            "result_card": {
                "title": "Senior Data Engineer (m/w/d)",
                "company_name": "Example GmbH",
                "location": "Hannover",
                "detail_url": (
                    "https://www.stepstone.de/stellenangebote--"
                    "Senior-Data-Engineer-Hannover-Example-GmbH--123456-inline.html"
                ),
                "external_job_id_candidate": "123456",
            },
            "source_specific": {
                "raw_card_text": "Evidence only. Silver must not parse this field.",
            },
            "extraction": {
                "extracted_from": "search_result_page",
                "detail_page_fetched": False,
                "pagination_used": False,
                "connector_mode": "limited_result_card",
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["raw_job_id"] == 6001
    assert result["source_name"] == "stepstone"
    assert result["external_job_id"] == "123456"
    assert result["source_url"] == (
        "https://www.stepstone.de/stellenangebote--"
        "Senior-Data-Engineer-Hannover-Example-GmbH--123456-inline.html"
    )
    assert result["title"] == "Senior Data Engineer (m/w/d)"
    assert result["company_name"] == "Example GmbH"
    assert result["city"] == "Hannover"
    assert result["postal_code"] is None
    assert result["country"] is None
    assert result["publication_date"] is None
    assert result["normalized_title"] == "senior data engineer (m/w/d)"
    assert result["normalized_company_name"] == "example gmbh"
    assert result["normalized_location"] == "hannover"
    assert result["canonical_status"] == "discovery_only"
    assert result["canonical_source_type"] == "unknown"
    assert result["canonical_key_candidate"] == (
        "example gmbh :: senior data engineer (m/w/d) :: hannover"
    )


def test_supported_source_patterns_include_stepstone() -> None:
    assert "stepstone" in get_supported_source_patterns()


def test_transform_finanz_informatik_raw_job_uses_bounded_connector_fields() -> None:
    raw_job = {
        "id": 7001,
        "source_name": "finanz_informatik:hannover",
        "external_job_id": "product-owner-osplus-versiegelung-m-w-d:e216499b2369",
        "source_url": "https://www.f-i.de/de/karriere/offene-stellen",
        "raw_data": {
            "result_card": {
                "title": "Product Owner OSPlus Versiegelung (m/w/d)",
                "company_name": "Finanz Informatik GmbH & Co. KG",
                "location": "Hannover",
                "detail_url": "https://www.f-i.de/de/karriere/offene-stellen/hannover/product-owner-osplus-versiegelung-m-w-d",
            },
            "job": {
                "title": "Product Owner OSPlus Versiegelung (m/w/d)",
                "company_name": "Finanz Informatik GmbH & Co. KG",
                "location": "Hannover",
                "source_url": "https://www.f-i.de/de/karriere/offene-stellen/hannover/product-owner-osplus-versiegelung-m-w-d",
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["raw_job_id"] == 7001
    assert result["source_name"] == "finanz_informatik:hannover"
    assert result["source_url"] == "https://www.f-i.de/de/karriere/offene-stellen/hannover/product-owner-osplus-versiegelung-m-w-d"
    assert result["title"] == "Product Owner OSPlus Versiegelung (m/w/d)"
    assert result["company_name"] == "Finanz Informatik GmbH & Co. KG"
    assert result["city"] == "Hannover"
    assert result["country"] == "DE"
    assert result["normalized_company_name"] == "finanz informatik gmbh & co. kg"
    assert result["normalized_location"] == "hannover | de"


def test_supported_source_patterns_include_finanz_informatik_family() -> None:
    assert "finanz_informatik:%" in get_supported_source_patterns()


def test_transform_enercity_raw_job_uses_bounded_connector_fields() -> None:
    raw_job = {
        "id": 11872,
        "source_name": "enercity:discovery",
        "external_job_id": "cloud-infrastructure-devops-engineer-f-m-d-azure-focus-J2026011:2fabb8ff5e85",
        "source_url": "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-f-m-d-azure-focus-J2026011",
        "raw_data": {
            "result_card": {
                "title": "Cloud Infrastructure & DevOps Engineer (f/m/d) – Azure Focus",
                "company_name": "enercity AG",
                "location": "hannover; remote; deutschland; hybrid",
                "detail_url": "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-f-m-d-azure-focus-J2026011",
            },
            "job": {
                "title": "Cloud Infrastructure & DevOps Engineer (f/m/d) – Azure Focus",
                "company_name": "enercity AG",
                "location": "hannover; remote; deutschland; hybrid",
                "source_url": "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-f-m-d-azure-focus-J2026011",
                "profile_terms": ["Azure", "Cloud", "DevOps"],
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["raw_job_id"] == 11872
    assert result["source_name"] == "enercity:discovery"
    assert result["source_url"] == "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-f-m-d-azure-focus-J2026011"
    assert result["title"] == "Cloud Infrastructure & DevOps Engineer (f/m/d) – Azure Focus"
    assert result["company_name"] == "enercity AG"
    assert result["city"] == "hannover; remote; deutschland; hybrid"
    assert result["country"] == "DE"
    assert result["normalized_title"] == "cloud infrastructure & devops engineer (f/m/d) – azure focus"
    assert result["normalized_company_name"] == "enercity ag"
    assert result["normalized_location"] == "hannover; remote; deutschland; hybrid | de"
    assert result["canonical_source_type"] == "employer_origin_career_site"
    assert result["canonical_key_candidate"] == (
        "enercity ag :: cloud infrastructure & devops engineer (f/m/d) – azure focus"
        " :: hannover; remote; deutschland; hybrid | de"
    )


def test_supported_source_patterns_include_enercity_family() -> None:
    assert "enercity:%" in get_supported_source_patterns()



def test_transform_hdi_raw_job_uses_bounded_connector_fields() -> None:
    raw_job = {
        "id": 11938,
        "source_name": "hdi:hannover",
        "external_job_id": "1371415133:c70418faa5fb",
        "source_url": "https://job.hdi.group/job/Hannover-Portfolio-Steering-Actuary-&-Business-Analyst-(Long-Tail)/743-en_US/",
        "raw_data": {
            "job": {
                "title": "Portfolio Steering - Actuary & Business Analyst (Long Tail) Job Details | HDI",
                "company_name": "HDI Group",
                "location": "hannover; remote; deutschland",
                "source_url": "https://job.hdi.group/job/Hannover-Portfolio-Steering-Actuary-&-Business-Analyst-(Long-Tail)/743-en_US/",
            },
            "result_card": {
                "title": "Portfolio Steering - Actuary & Business Analyst (Long Tail) Job Details | HDI",
                "company_name": "HDI Group",
                "location": "hannover; remote; deutschland",
                "detail_url": "https://job.hdi.group/job/Hannover-Portfolio-Steering-Actuary-&-Business-Analyst-(Long-Tail)/743-en_US/",
            },
        },
    }

    result = transform_raw_job_to_silver(raw_job)

    assert result["source_name"] == "hdi:hannover"
    assert result["source_url"] == "https://job.hdi.group/job/Hannover-Portfolio-Steering-Actuary-&-Business-Analyst-(Long-Tail)/743-en_US/"
    assert result["title"] == "Portfolio Steering - Actuary & Business Analyst (Long Tail) Job Details | HDI"
    assert result["company_name"] == "HDI Group"
    assert result["city"] == "hannover; remote; deutschland"
    assert result["country"] == "DE"
    assert result["canonical_source_type"] == "employer_origin_career_site"
    assert result["canonical_key_candidate"].startswith(
        "hdi group :: portfolio steering - actuary & business analyst"
    )


def test_supported_source_patterns_include_hdi_family() -> None:
    assert "hdi:%" in get_supported_source_patterns()
