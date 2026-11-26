import copy
import json
from pathlib import Path

import pytest
import requests

from src.career_intelligence.competency_qualification import (
    assess_qualified_vacancy, load_candidate_evidence, load_strategy, qualify_vacancy,
)
from src.career_intelligence.discovery_v3 import build_query_plan, _load
from src.career_intelligence.market_intelligence import build_market_intelligence
from src.career_intelligence.source_adapters import RetrievalLimits, fetch_ba, fetch_smartrecruiters
from tests.career_intelligence.test_discovery_v3 import Response, Session

FIXTURE = Path("tests/fixtures/career_intelligence/v34_evaluation.json")
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.fixture(scope="module")
def context():
    config = load_strategy()
    config["candidate_evidence"].pop("approved_facts_file", None)
    config["candidate_evidence"]["preview_review_enabled"] = False
    return config, load_candidate_evidence(config)


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["id"])
def test_reproducible_qualification_review_cases(row, context):
    config, candidate = context
    original = copy.deepcopy(row)
    q = qualify_vacancy(row, config=config, candidate=candidate)
    assert q["status"] == row["expected_status"]
    assert q["career_compatibility"] == "not_assessed"
    assert q["assessment_eligible"] is False  # Master CV is deliberately not fabricated.
    assert row == original
    assert "opportunity_score" not in q and "recommendation" not in q
    if q["status"] == "STRONG_TRANSFERABLE_FIT":
        assert len(q["competency_evidence"]) >= 3
        assert q["location"]["status"] == "confirmed_compatible"


@pytest.mark.parametrize("key,expected", [
    ("china_core", "Core requirement"),
    ("china_preferred", "Strong advantage"),
    ("china_language_only", "Additional advantage"),
    ("china_employer_only", "Not relevant"),
    ("international_no_china", "Additional advantage"),
    ("china_title_only", "Not relevant"),
    ("energy_core", "Not relevant"),
])
def test_china_europe_job_scope_is_not_a_candidate_claim(key, expected, context):
    config, candidate = context
    row = next(row for row in CASES if row["id"] == key)
    q = qualify_vacancy(row, config=config, candidate=candidate)
    assert q["china_europe"]["relevance"] == expected
    assert q["china_europe"]["candidate_support"] == "not_verified"
    assert not q["china_europe"]["candidate_evidence"]
    assert q["china_europe"]["score_contribution"] == 0
    assert q["china_europe"]["no_china_component_penalty"] is False


def test_china_verified_professional_fact_requires_specific_evidence(context):
    config, candidate = context
    candidate = copy.deepcopy(candidate)
    candidate["verified_professional_facts"] = [{
        "fact_key": "test.china_europe", "capability_tags": ["international_cross_border"],
        "statement": "Coordinated engineering supplier programs and stakeholders in China and "
                     "Germany, using Mandarin, German and English in professional collaboration.",
        "provenance": [{"source_type": "canonical_cv", "reference": "test fixture CV"}],
    }]
    row = next(row for row in CASES if row["id"] == "china_core")
    q = qualify_vacancy(row, config=config, candidate=candidate)
    dimension = q["china_europe"]
    assert dimension["candidate_support"] == "cv_verified_professional"
    assert dimension["verified_dimensions"]["mandarin_german_english_communication"]
    assert not dimension["verified_dimensions"]["china_market_knowledge"]
    assert dimension["score_contribution"] == 0
    candidate["verified_professional_facts"][0]["statement"] = "Speaks Mandarin."
    assert qualify_vacancy(row, config=config, candidate=candidate)[
        "china_europe"]["candidate_support"] == "not_verified"


def test_china_competence_does_not_offset_specialist_gap_or_travel(context):
    config, candidate = context
    row = next(row for row in CASES if row["id"] == "china_core")
    base = qualify_vacancy(row, config=config, candidate=candidate)
    changed = {**row, "description": row["description"] +
               "\nRequirements: Deep cloud architecture expertise is required."}
    q = qualify_vacancy(changed, config=config, candidate=candidate)
    assert q["china_europe"]["relevance"] == base["china_europe"]["relevance"]
    assert q["specialist_gaps"] and not q["plausible_cross_industry"]
    assert q["assessment_eligible"] is False


def test_provisional_absence_is_not_a_confirmed_experience_mismatch(context):
    config, candidate = context
    row = next(row for row in CASES if row["id"] == "production_ai")
    q = qualify_vacancy(row, config=config, candidate=candidate)
    assert q["status"] == "POSSIBLE_FIT"
    assert q["specialist_gaps"][0]["evidence_status"] == "not_documented_in_provisional_profile"
    assert not q["plausible_cross_industry"]


def test_unconventional_title_can_qualify_without_changing_legacy_gate(context):
    config, candidate = context
    row = next(row for row in CASES if row["id"] == "unconventional")
    q = qualify_vacancy(row, config=config, candidate=candidate)
    assert q["title_gate"]["reason"] == "AMBIGUOUS_REVIEW"
    assert q["status"] == "STRONG_TRANSFERABLE_FIT"


def test_qualification_does_not_run_full_assessment_without_cv(context):
    config, candidate = context
    row = next(row for row in CASES if row["id"] == "energy_core")
    with pytest.raises(ValueError, match="CV-backed"):
        assess_qualified_vacancy(row, config=config, candidate=candidate)


def test_market_preview_reconciles_without_activating_or_overwriting_assessments():
    before = copy.deepcopy(CASES)
    legacy = build_market_intelligence(CASES)
    preview = build_market_intelligence(CASES, strategy_version="v3.4")
    assert CASES == before
    assert legacy["strategy_version"] == "v3.3"
    assert not any("qualification" in row for row in legacy["vacancies"])
    assert preview["summary"]["gate_counts"] == legacy["summary"]["gate_counts"]
    assert sum(preview["summary"]["qualification_counts"].values()) == len(CASES)
    assert sum(row["vacancy_count"] for row in preview["industries"]) == len(CASES)
    assert preview["summary"]["full_assessment_count"] == 0
    assert all(row["qualification"]["strategy_version"] == "v3.4"
               for row in preview["vacancies"])


def test_query_attention_is_request_allocation_and_rotation_is_bounded():
    from collections import Counter
    config = _load(Path("config/career_discovery_v34.yaml"))
    plan = build_query_plan(config)
    counts = Counter(profile for profile, _, _ in plan)
    assert counts == {"A": 20, "B": 14, "C": 6}
    assert len(plan) == 40
    assert {row[0] for row in build_query_plan(config, maximum=8)} == set(counts)
    rotated = build_query_plan(config, offset=6)
    assert any("China" in query for _, query, _ in rotated)
    bank = " ".join(query for terms in config["profiles"].values() for query in terms)
    assert "International Technical Program Manager" in bank
    assert "Global Engineering Program Manager" in bank
    assert "Internationale Programmleitung" in bank


def test_smartrecruiters_detail_evidence_preserves_raw_list_and_stable_identity():
    listing = {"id": "12", "name": "Program Manager", "ref": "https://jobs/12",
               "location": {"country": "de", "city": "Berlin"}}
    session = Session([{"totalFound": 1, "content": [listing]},
                       {"jobAd": {"sections": {"jobDescription": {"text": "Your tasks: Lead."}}}}])
    result = fetch_smartrecruiters(board_id="Acme", employer="Acme",
        country="DE", max_details=1, limits=RetrievalLimits(), session=session)
    row = result["records"][0]
    assert session.calls[0][1]["params"]["country"] == "de"
    assert row["external_job_id"] == "12"
    assert row["raw"]["name"] == listing["name"]
    assert row["raw"]["_v34_detail"]["jobAd"]["sections"]
    assert row["description"] == ""  # Optional enrichment must not change list-content identity/hash.
    assert result["details_requested"] == 1


def test_failed_ba_later_page_retains_successful_observations():
    class PartialSession:
        count = 0

        def get(self, *args, **kwargs):
            self.count += 1
            if self.count == 1:
                return Response({"maxErgebnisse": 4, "ergebnisliste": [
                    {"referenznummer": "1"}, {"referenznummer": "2"}]})
            raise requests.Timeout("second page timed out")
    result = fetch_ba(query="program", location="Berlin", api_key="test",
                      session=PartialSession(), limits=RetrievalLimits(
                          page_size=2, max_pages=2, max_retries=0))
    assert len(result["records"]) == 2
    assert result["pages_requested"] == 2
    assert result["retrieval_errors"]
    assert result["snapshot_complete"] is False


def test_v34_registry_does_not_activate_unverified_sources():
    registry = _load(Path("config/career_employer_sources_v34.yaml"))
    active = [source for source in registry["sources"] if source.get("active")]
    assert all(source["access_status"] == "public_board" for source in active)
    assert all(not target.get("active") for target in registry["targets"])
    assert {source["board_id"] for source in active} == {"waymo", "moia", "BoschGroup", "ServiceNow"}


def test_curated_plausibility_labels_are_not_title_matches():
    from scripts.evaluate_career_v34 import evaluate_cases
    report = evaluate_cases(CASES)
    assert not report["false_positives_on_curated_plausibility_labels"]
    assert not report["false_negatives_on_curated_plausibility_labels"]
    assert report["reviewed_paraphrases"] == 13
    assert report["synthetic_controls"] == 24


def test_smartrecruiters_description_keeps_required_and_employer_scopes_separate():
    from src.career_intelligence.market_intelligence import observation_description
    row = {"raw_payload": {"_v34_detail": {"jobAd": {"sections": {
        "companyDescription": {"text": "We work with Chinese suppliers and global AI programs."},
        "jobDescription": {"text": CASES[0]["description"]},
        "qualifications": {"text": "Deep cloud architecture expertise is required."},
    }}}, "_v34_detail_url": "https://example.test/detail"}}
    description, source = observation_description(row)
    assert "Requirements:" in description
    assert source == "https://example.test/detail"
    q = qualify_vacancy({**CASES[0], "description": description})
    assert q["specialist_gaps"]
    assert not q["plausible_cross_industry"]
    assert q["china_europe"]["relevance"] == "Not relevant"


def test_optional_technology_does_not_erase_mandatory_requirement(context):
    config, candidate = context
    row = {**CASES[0], "description": CASES[0]["description"] +
           "\nRequirements: Deep cloud architecture expertise (AWS certification preferred) is required."}
    q = qualify_vacancy(row, config=config, candidate=candidate)
    assert q["specialist_gaps"]


def test_contract_term_is_evidenced_without_affecting_scores():
    q = qualify_vacancy({**CASES[0], "title": "Program Manager, 6 months fixed-term"})
    assert q["employment_conditions"]["status"] == "source_terms_captured"
    assert q["employment_conditions"]["evidence"][0]["type"] == "contract_term"
    assert q["career_compatibility"] == "not_assessed"


def test_no_universal_china_or_mandarin_bonus(context):
    config, candidate = context
    base = next(row for row in CASES if row["id"] == "energy_core")
    plain = qualify_vacancy(base, config=config, candidate=candidate)
    language = qualify_vacancy({**base, "description": base["description"] +
                               "\nPreferred qualifications: Mandarin language skills."},
                              config=config, candidate=candidate)
    assert plain["status"] == language["status"]
    assert plain["plausible_cross_industry"] == language["plausible_cross_industry"]
    assert plain["competency_evidence"] == language["competency_evidence"]
    assert plain["china_europe"]["relevance"] == "Not relevant"
    assert language["china_europe"]["score_contribution"] == 0


def test_production_activation_cannot_be_enabled_by_preview_config(tmp_path):
    import yaml
    config = load_strategy()
    config["production_default"] = True
    path = tmp_path / "strategy.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="explicitly selected preview"):
        load_strategy(path)


def test_configured_active_but_unauthorized_board_makes_no_http_calls(monkeypatch, tmp_path):
    from src.career_intelligence import discovery_v3
    config = _load(Path("config/career_discovery_v3.yaml"))
    registry = {"schema_version": "career_intelligence.employer_sources.v1",
                "sources": [{"employer": "Unverified", "ats": "greenhouse", "board_id": "bad",
                             "active": True, "access_status": "awaiting_validation"}]}
    monkeypatch.setattr(discovery_v3, "_load",
                        lambda path: config if path == discovery_v3.CONFIG else registry)
    monkeypatch.setattr(discovery_v3, "BA_API_KEY", "")
    monkeypatch.setattr(discovery_v3, "register_configured_sources", lambda *args: None)
    monkeypatch.setattr(discovery_v3, "finalize_run_group", lambda *args: None)
    monkeypatch.setattr(discovery_v3, "load_monitoring_summary", lambda *args: {})

    def forbidden(**kwargs):
        raise AssertionError("Unverified boards must not make HTTP requests")

    monkeypatch.setattr(discovery_v3, "fetch_greenhouse", forbidden)
    report = discovery_v3.run(database=object(), results_dir=tmp_path)
    assert report["http_requests"] == 0
    assert all(run["status"] == "blocked" for run in report["runs"])
