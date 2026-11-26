from src.career_intelligence.market_intelligence import build_market_intelligence


def test_market_inventory_uses_existing_gate_and_separates_discovery_from_assessment():
    report = build_market_intelligence([
        {"id": 1, "company_name": "MOIA", "title": "Fleet Operations Lead",
         "locations": ["Berlin, Germany", "Munich, Germany"]},
        {"id": 2, "company_name": "Example", "title": "Product Manager",
         "location_text": "London, UK"},
        {"id": 3, "company_name": "Other", "title": "Software Engineer",
         "location_text": "San Francisco, US"},
        {"id": 4, "company_name": "Other", "title": "Open Application",
         "vacancy_type": "unsolicited_application"},
        {"id": 5, "company_name": "Old", "title": "Program Manager",
         "lifecycle_status": "removed"},
    ])

    assert report["summary"]["vacancy_count"] == 3
    assert report["summary"]["gate_counts"]["RELEVANT_ROLE"] == 1
    assert report["summary"]["gate_counts"]["AMBIGUOUS_REVIEW"] == 1
    assert report["summary"]["gate_counts"]["EXCLUDED_ENGINEERING"] == 1
    assert report["summary"]["full_assessment_count"] == 0
    assert report["boundaries"]["scoring_unchanged"] is True
    relevant = next(row for row in report["vacancies"] if row["gate_reason"] == "RELEVANT_ROLE")
    assert relevant["why"].startswith("Title matched configured rule:")
    assert all(row["career_compatibility"] == "not_assessed" for row in report["vacancies"])


def test_geography_counts_distinct_vacancies_and_berlin_is_within_germany():
    report = build_market_intelligence([
        {"id": 1, "company_name": "Multi", "title": "Program Manager",
         "locations": ["Berlin, Germany", "Amsterdam, Netherlands"]},
        {"id": 2, "company_name": "Unknown", "title": "Program Manager"},
    ])
    geography = {item["name"]: item["vacancy_count"] for item in report["geography"]}

    assert geography["Germany"] == 1
    assert geography["Berlin"] == 1
    assert geography["Other Europe"] == 1
    assert geography["Unknown"] == 1
    assert report["summary"]["vacancy_count"] == 2


def test_market_inventory_retains_source_identity_and_timestamps():
    row = {
        "id": 17, "company_name": "Acme", "title": "Program Manager",
        "source_key": "greenhouse:acme", "source_job_id": "gh-12",
        "source_url": "https://jobs.example.test/gh-12", "publication_at": "2026-10-01",
        "source_updated_at": "2026-10-04", "first_seen_at": "2026-10-02",
        "last_seen_at": "2026-10-05",
    }
    vacancy = build_market_intelligence([row])["vacancies"][0]

    assert vacancy["source_key"] == "greenhouse:acme"
    assert vacancy["source_job_id"] == "gh-12"
    assert vacancy["publication_at"] == "2026-10-01"
    assert vacancy["source_updated_at"] == "2026-10-04"
