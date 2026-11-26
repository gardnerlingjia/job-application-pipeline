"""V3.4 provider coverage and independent professional evidence regressions."""
import copy

import pytest
import requests

from src.career_intelligence.competency_qualification import (
    china_europe_dimension, classify_china_europe_requirements, load_strategy,
)
from src.career_intelligence.discovery_store import vacancy_keys
from src.career_intelligence.source_adapters import (
    ProviderParseError, RetrievalLimits, fetch_smartrecruiters,
)


class Session:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = next(self.payloads)
        if isinstance(payload, Exception):
            raise payload
        return self.Response(payload)

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload


def posting(identity):
    return {"id": identity, "name": "Same title", "ref": f"https://jobs.test/{identity}",
            "location": {"city": "Berlin", "country": "de"}}


def fetch(payloads, **kwargs):
    session = Session(payloads)
    result = fetch_smartrecruiters(board_id="acme", employer="Acme", session=session,
                                  limits=RetrievalLimits(page_size=2, max_pages=3, max_retries=0),
                                  **kwargs)
    return result, session


@pytest.mark.parametrize("country", ["DE", "de", " de "])
def test_provider_country_normalized(country):
    result, session = fetch([{"totalFound": 0, "content": []}], country=country)
    assert session.calls[0][1]["params"]["country"] == "de"
    assert result["snapshot_complete"]
    assert result["coverage_scope"] == "filtered_query"


@pytest.mark.parametrize("country", ["Germany", "", "DEU", "de&offset=20", "zz", "EU"])
def test_invalid_country_never_becomes_empty_coverage(country):
    with pytest.raises(ProviderParseError):
        fetch([], country=country)


@pytest.mark.parametrize("payload", [{}, [], {"content": []},
                                     {"content": [], "totalFound": "0"}])
def test_malformed_empty_not_valid_coverage(payload):
    with pytest.raises(ProviderParseError):
        fetch([payload])


def test_short_pages_continue_until_reported_total_and_distinct_ids_survive():
    result, session = fetch([{"totalFound": 2, "content": [posting("one")]},
                             {"totalFound": 2, "content": [posting("two")]}])
    assert [call[1]["params"]["offset"] for call in session.calls] == [0, 1]
    assert result["snapshot_complete"]
    assert result["unique_source_vacancies"] == 2
    assert vacancy_keys(result["records"][0]) != vacancy_keys(result["records"][1])


def test_duplicate_pages_preserve_observations_without_false_completion():
    result, _ = fetch([{"totalFound": 4, "content": [posting("one"), posting("two")]},
                       {"totalFound": 4, "content": [posting("one"), posting("two")]}])
    assert len(result["records"]) == 4
    assert result["unique_source_vacancies"] == 2
    assert not result["snapshot_complete"]
    assert result["retrieval_errors"]


@pytest.mark.parametrize("later", [requests.ConnectionError("offline"),
                                   {"content": [], "totalFound": 3}])
def test_partial_results_and_attempt_counts_preserved(later):
    result, _ = fetch([{"totalFound": 3, "content": [posting("one"), posting("two")]},
                       later])
    assert len(result["records"]) == 2
    assert result["pages_requested"] == 2
    assert result["retrieval_errors"]
    assert not result["snapshot_complete"]


def test_country_response_mismatch_is_failure():
    job = posting("one")
    job["location"]["country"] = "us"
    with pytest.raises(ProviderParseError):
        fetch([{"totalFound": 1, "content": [job]}], country="DE")


def sections(text):
    return {"duties": "", "required": text, "preferred": "", "unstructured": ""}


def candidate(statement):
    return {"verified_professional_facts": [{
        "fact_key": "synthetic.cv", "statement": statement,
        "capability_tags": ["international_cross_border"],
        "provenance": [{"source_type": "canonical_cv", "reference": "synthetic fixture"}],
    }]}


@pytest.mark.parametrize("statement", [
    "Chinese nationality, speaks Mandarin, German and English.",
    "Chinese engineer with international supplier coordination experience.",
    "Mandarin speaker who managed engineering programs in Germany.",
    "Chinese cultural background and strong international collaboration skills.",
])
def test_background_or_languages_do_not_verify_achievements(statement):
    value = china_europe_dimension(sections("Manage supplier programs in China."),
                                   candidate(statement), load_strategy())
    assert value["candidate_support"] == "not_verified"
    assert value["candidate_evidence_status"] == "pending_cv_verification"
    assert value["score_contribution"] == 0


def test_requirements_independent_and_unmatched_dimensions_pending():
    config = load_strategy()
    role = sections("Manage engineering supplier programs in China; China market knowledge required.")
    verified = candidate("Coordinated engineering supplier programs in China and Germany.")
    empty = china_europe_dimension(role, {}, config)
    qualified = china_europe_dimension(role, verified, config)
    assert classify_china_europe_requirements(role, config) == {
        "relevance": empty["relevance"], "job_evidence": empty["job_evidence"]}
    assert qualified["relevance"] == empty["relevance"]
    assert qualified["job_evidence"] == empty["job_evidence"]
    assert qualified["verified_dimensions"]["engineering_supplier_coordination"]
    assert "china_market_knowledge" in qualified["pending_dimensions"]
    assert qualified["candidate_evidence_status"] == "pending_cv_verification"
    unproven = copy.deepcopy(verified)
    unproven["verified_professional_facts"][0]["provenance"] = []
    assert china_europe_dimension(role, unproven, config)["candidate_support"] == "not_verified"


@pytest.mark.parametrize("errors,details", [(["page limit"], []), ([], ["detail offline"])])
def test_runner_marks_partial_health_and_never_confirms_removal(monkeypatch, tmp_path,
                                                               errors, details):
    from src.career_intelligence import discovery_v3
    config = discovery_v3._load(discovery_v3.CONFIG)
    registry = {"schema_version": "career_intelligence.employer_sources.v1", "sources": [{
        "employer": "Acme", "ats": "smartrecruiters", "board_id": "acme", "regions": ["DE"],
        "active": True, "access_status": "public_board"}]}
    monkeypatch.setattr(discovery_v3, "_load",
                        lambda path: config if path == discovery_v3.CONFIG else registry)
    monkeypatch.setattr(discovery_v3, "BA_API_KEY", "")
    monkeypatch.setattr(discovery_v3, "register_configured_sources", lambda *args: None)
    monkeypatch.setattr(discovery_v3, "finalize_run_group", lambda *args: None)
    monkeypatch.setattr(discovery_v3, "load_monitoring_summary", lambda *args: {})
    monkeypatch.setattr(discovery_v3, "fetch_smartrecruiters", lambda **kwargs: {
        "records": [], "pages": [{"raw_results": 0}], "pages_requested": 2,
        "snapshot_complete": True, "retrieval_errors": errors, "detail_errors": details})
    captured = []

    def record(conn, **kwargs):
        captured.append(kwargs)
        return {}

    monkeypatch.setattr(discovery_v3, "record_run", record)
    report = discovery_v3.run(database=object(), results_dir=tmp_path)
    assert captured[0]["status"] == "partial"
    assert captured[0]["snapshot_complete"] is False
    assert captured[0]["telemetry"]["pages_requested"] == 2
    assert next(run for run in report["runs"] if run.get("source") == "smartrecruiters:acme")["retrieval_errors"] == errors + details


def test_detail_failure_does_not_discard_posting():
    result, _ = fetch([{"totalFound": 1, "content": [posting("one")]},
                       requests.ConnectionError("detail unavailable")], max_details=1)
    assert len(result["records"]) == 1
    assert result["detail_errors"]


def test_acceptance_report_does_not_confuse_discovery_and_candidate_evidence():
    from scripts.evaluate_career_v34 import acceptance_funnel
    from src.career_intelligence.competency_qualification import (
        load_candidate_evidence, qualify_vacancy,
    )
    config = load_strategy()
    q = qualify_vacancy({"title": "Program Manager", "description": ""},
                        config=config, candidate=load_candidate_evidence(config))
    funnel = acceptance_funnel({"vacancies": [{"qualification": q}]})
    assert funnel["newly_discovered_vacancies_this_evaluation"] == 0
    assert funnel["verified_candidate_fact_keys_matched"] == []
    assert funnel["opportunity_quality_change_vs_v33"]["confirmed_gain"] is None


def test_page_cap_and_detail_budget_exhaustion_remain_explicit():
    payloads = [{"totalFound": 20, "content": [posting(str(i)), posting(str(i + 1))]}
                for i in (0, 2, 4)]
    result, _ = fetch(payloads)
    assert result["pages_requested"] == 3
    assert not result["snapshot_complete"]
    assert "Pagination limit" in result["retrieval_errors"][0]
    result, _ = fetch([{"totalFound": 1, "content": [posting("one")]},
                       RuntimeError("per-run HTTP request budget exhausted")], max_details=1)
    assert len(result["records"]) == 1
    assert result["detail_errors"]
