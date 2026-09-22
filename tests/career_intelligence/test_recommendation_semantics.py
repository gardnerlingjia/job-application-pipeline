"""Independent evidence/access gates and immutable historical calibration inputs."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.classifier import strategy_context
from src.career_intelligence.recommender import recommend_strategy_action, recommend_action
from src.career_intelligence.scoring import calculate_candidate_strength

FIXTURES = Path("tests/fixtures/career_intelligence")
ROWS = json.loads((FIXTURES / "strategy_calibration.v4.json").read_text())


def assess_row(key, *, evidence=None, travel_confirmed=False):
    row = next(row for row in ROWS if row["key"] == key)
    return assess_opportunity(
        row["company"],
        row["title"],
        row["description"] + (" No travel required." if travel_confirmed else ""),
        role_evidence=evidence or row.get("role_evidence"),
    )


@pytest.mark.parametrize("access", ["cold", "warm", "referral-based", "sponsor-supported"])
@pytest.mark.parametrize("strength", [20, 59, 60, 90])
@pytest.mark.parametrize("blocked", [False, True])
def test_network_first_invariant(access, strength, blocked):
    context = strategy_context("Robotics Technical Program Manager", "Berlin. Deployment.")
    result = recommend_strategy_action(
        strength,
        "CLEAR",
        context,
        {"location_matches": ["berlin"], "compatibility": "confirmed"},
        access,
        {"core_technical_gap": "Missing ownership"} if blocked else {},
        "not_applicable",
    )
    if result == "NETWORK_FIRST":
        assert access == "cold" and strength >= 60 and not blocked
    if blocked or strength < 60:
        assert result in {"WATCH", "SKIP"}
    if access != "cold":
        assert result != "NETWORK_FIRST"
    if access == "cold" and strength >= 60 and not blocked:
        assert result == "NETWORK_FIRST"


@pytest.mark.parametrize("key", ["robotics_tpm", "cos", "dx", "freenow", "amr", "cariad"])
@pytest.mark.parametrize(
    "level", ["employee_referral", "hiring_manager_access", "internal_sponsor"]
)
def test_documented_access_never_routes_to_network_first(key, level):
    row = next(row for row in ROWS if row["key"] == key)
    evidence = copy.deepcopy(row.get("role_evidence", {}))
    evidence["network"] = {
        "relationship_level": level,
        "status": "confirmed",
        "evidence_source": "Synthetic documented role access",
    }
    result = assess_row(key, evidence=evidence)
    assert result["recommendation"] != "NETWORK_FIRST"


def test_candidate_strength_ignores_strategy_location_and_access():
    scores = {
        "capability_fit": 45,
        "evidence_strength": 30,
        "career_lane_fit": 0,
        "domain_fit": 0,
        "location_fit": 0,
        "network_access": 0,
    }
    before = calculate_candidate_strength(scores)
    scores.update(career_lane_fit=100, domain_fit=100, location_fit=100, network_access=100)
    assert calculate_candidate_strength(scores) == before == 30


def test_career_priority_cannot_inflate_candidate_strength(monkeypatch):
    from src.career_intelligence import classifier

    row = next(row for row in ROWS if row["key"] == "robotics_tpm")
    baseline = assess_row("robotics_tpm")
    profile = classifier.load_career_profile()
    for lane in profile["career_lanes"].values():
        lane["allocation_percent"] = 100
        lane["role_keywords"] += [row["title"]]
        lane["classification_multiplier"] = 50
    monkeypatch.setattr(classifier, "load_career_profile", lambda: profile)
    result = assess_row("robotics_tpm")
    assert result["candidate_strength"] == baseline["candidate_strength"]
    assert result["recommendation"] == baseline["recommendation"]


@pytest.mark.parametrize(
    "value,status,source",
    [
        (False, "unknown", "test"),
        (False, "inferred", "test"),
        (False, "confirmed", ""),
        ("false", "confirmed", "test"),
        (None, "confirmed", "test"),
    ],
)
def test_amr_requires_confirmed_sourced_boolean_scope(value, status, source):
    evidence = {
        "requirements": {
            "engineering_commissioning_core": {
                "value": value,
                "status": status,
                "evidence_source": source,
            }
        }
    }
    result = assess_row("amr", evidence=evidence)
    assert result["recommendation"] == "WATCH"
    assert result["explanation"]["role_requirements"]["commissioning_status"] == "unknown"


def test_amr_no_mention_is_not_confirmation():
    assert assess_row("amr")["recommendation"] == "WATCH"
    assert assess_row("amr_confirmed_delivery", travel_confirmed=True)["recommendation"] == "APPLY_NOW"
    assert assess_row("amr_core_commissioning")["recommendation"] == "WATCH"


def test_core_requirement_text_overrides_conflicting_negative_scope_fact():
    row = next(row for row in ROWS if row["key"] == "amr_confirmed_delivery")
    result = assess_opportunity(
        row["company"],
        row["title"],
        row["description"] + " Hands-on commissioning required.",
        role_evidence=row["role_evidence"],
    )
    assert result["recommendation"] == "WATCH"
    assert result["explanation"]["role_requirements"]["commissioning_status"] == "core_required"


def test_freenow_feedback_is_preserved_separately_from_role_text():
    result = assess_row("freenow")
    assert result["strategic_attractiveness"]["sufficient"]
    assert result["candidate_strength"]["score"] == 40
    assert result["recommendation"] == "WATCH"
    assert (
        "real FREENOW"
        in result["explanation"]["role_requirements"]["facts"]["commercial_core"]["evidence_source"]
    )


def test_legacy_composite_score_cannot_create_network_first():
    for access in (0, 90):
        assert recommend_action(95, "CLEAR", access, [], []) == "WATCH"


def test_v1_inputs_and_results_remain_exact():
    manifest = json.loads((FIXTURES / "strategy_calibration.v1.manifest.json").read_text())
    for version in ("v0.json", "v1.json", "v1.results.json"):
        path = FIXTURES / f"strategy_calibration.{version}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"][str(path)]
    assert (FIXTURES / "strategy_calibration.json").read_bytes() == (
        FIXTURES / "strategy_calibration.v1.json"
    ).read_bytes()
    old = json.loads((FIXTURES / "strategy_calibration.v1.json").read_text())
    for row in old:
        new = next(new for new in ROWS if new["key"] == row["key"])
        assert (new["company"], new["title"], new["description"]) == (
            row["company"],
            row["title"],
            row["description"],
        )


def test_access_cannot_increase_candidate_strength_for_selective_bridge():
    args = ("Example", "AI Product Owner", "Berlin. Data products for a new industry.")
    cold = assess_opportunity(*args)
    warm = assess_opportunity(
        *args,
        role_evidence={
            "network": {
                "relationship_level": "hiring_manager_access",
                "status": "confirmed",
                "evidence_source": "Synthetic access",
            }
        },
    )
    assert cold["candidate_strength"] == warm["candidate_strength"]
    assert warm["recommendation"] != "NETWORK_FIRST"


def test_insufficient_strategy_blocks_network_even_with_strong_candidate():
    context = strategy_context("Program Manager", "Generic administration.")
    assert (
        recommend_strategy_action(
            100, "CLEAR", context, {"location_matches": ["berlin"], "compatibility": "confirmed"}, "cold", {}, "not_applicable"
        )
        == "SKIP"
    )


@pytest.mark.parametrize("key", ["dx", "freenow", "cariad", "amr", "robotics_tpm"])
@pytest.mark.parametrize("date", ["2026-09-14", "2020-01-01"])
def test_silver_freshness_cannot_bypass_capability_access_gates(key, date):
    from datetime import date as date_type
    from types import SimpleNamespace
    from src.career_intelligence.freshness import calculate_job_freshness
    from src.career_intelligence.ingest_silver import _apply_freshness_to_assessment

    baseline = assess_row(key)
    item = SimpleNamespace(
        freshness=calculate_job_freshness(publication_date=date, today=date_type(2026, 9, 15)),
        provenance={},
    )
    result = _apply_freshness_to_assessment(baseline, item)
    if baseline["recommendation"] == "WATCH":
        assert result["recommendation"] == "WATCH"
    if baseline["access_type"] != "cold":
        assert result["recommendation"] != "NETWORK_FIRST"
    assert result["candidate_strength"] == baseline["candidate_strength"]
    assert result["explanation"]["recommended_action"] == {
        "NETWORK_FIRST": "NETWORK FIRST",
        "APPLY_NOW": "APPLY",
    }.get(result["recommendation"], result["recommendation"])


def test_batch_retains_referred_dx_decision_and_strength(tmp_path):
    from src.career_intelligence.batch import process_batch

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    row = next(row for row in ROWS if row["key"] == "dx")
    (inbox / "dx.json").write_text(json.dumps(row))
    summary = process_batch(inbox, tmp_path / "processed", tmp_path / "results")
    result = summary["opportunities"][0]
    assert result["recommendation"] == "WATCH"
    assert result["explanation"]["access"] == "referral-based"
    assert result["explanation"]["candidate_strength"]["score"] == 40


def test_exact_v4_assessment_snapshots():
    expected = json.loads((FIXTURES / "strategy_calibration.v4.results.json").read_text())
    assert [{"key": row["key"], "assessment": assess_row(row["key"])} for row in ROWS] == expected


def test_v2_fixtures_are_frozen():
    manifest = json.loads((FIXTURES / "strategy_calibration.v2.manifest.json").read_text())
    for suffix in ("json", "results.json"):
        path = FIXTURES / f"strategy_calibration.v2.{suffix}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"][str(path)]


def test_current_total_is_weighted_candidacy_and_access_independent():
    row = next(row for row in ROWS if row["key"] == "robotics_tpm")
    cold = assess_row("robotics_tpm")
    warm = assess_opportunity(
        row["company"],
        row["title"],
        row["description"],
        role_evidence={
            "network": {
                "relationship_level": "employee_referral",
                "status": "confirmed",
                "evidence_source": "Synthetic referral",
            }
        },
    )
    from src.career_intelligence.scoring import calculate_opportunity_score

    for result in (cold, warm):
        assert result["opportunity_score"] == min(
            calculate_opportunity_score(result["scores"]), result["candidate_strength"]["gap_cap"]
        )
        assert result["opportunity_score"] == result["candidate_strength"]["score"]
        assert result["explanation"]["strategic_value"]["search_allocation_percent"] == 55
    assert warm["opportunity_score"] == cold["opportunity_score"]
    assert warm["network_access"] > cold["network_access"]


def test_adjacent_anchor_cannot_become_direct_by_repeating_keywords():
    row = next(row for row in ROWS if row["key"] == "robotics_tpm")
    result = assess_opportunity(row["company"], row["title"], row["description"] * 20)
    assert result["opportunity_score"] <= 75
    assert result["candidate_strength"]["anchors"]["basis"] == "adjacent"
    assert result["scores"]["career_lane_fit"] == 75
    assert result["opportunity_score"] == assess_row("robotics_tpm")["opportunity_score"]


def test_direct_anchor_requires_supported_professional_role_and_domain():
    result = assess_row("here", travel_confirmed=True)
    anchor = result["candidate_strength"]["anchors"]
    assert anchor["basis"] == "direct"
    assert anchor["direct_role_evidence"] and anchor["direct_domain_evidence"]
    assert result["scores"]["career_lane_fit"] == result["scores"]["domain_fit"] == 85
    assert result["recommendation"] == "NETWORK_FIRST"


def test_high_candidacy_location_skip_has_explicit_override():
    result = assess_row("munich")
    assert result["opportunity_score"] > 80
    assert result["recommendation"] == "SKIP"
    assert any(g["gate"] == "location_conflict" for g in result["explanation"]["gates"])


@pytest.mark.parametrize(
    "key,gap",
    [
        ("robotics_tpm_direct_years", "professional_robotics_years_missing"),
        ("amr_linux_field_engineering", "core_engineering_gap"),
        ("cos_finance_fundraising", "executive_fundraising_gap"),
    ],
)
def test_material_ownership_or_experience_gap_is_watch_not_network(key, gap):
    result = assess_row(key)
    assert result["recommendation"] == "WATCH"
    assert gap in result["candidate_strength"]["blocking_gaps"]
    assert result["opportunity_score"] <= 40
    assert any(g["gate"] == gap for g in result["explanation"]["gates"])


def test_cariad_bridge_variant_does_not_erase_historical_required_depth():
    strict = assess_row("cariad")
    bridge = assess_row("cariad_bridge_scope", travel_confirmed=True)
    assert strict["recommendation"] == "WATCH"
    assert bridge["recommendation"] == "APPLY_NOW"
    assert bridge["opportunity_score"] <= 75
    assert bridge["explanation"]["strategic_value"]["search_allocation_percent"] == 20
    assert "cloud_mlops_depth_missing" in bridge["explanation"]["gaps"]
    assert bridge["access_type"] == "warm"


def test_v3_freshness_preserves_published_candidacy():
    from datetime import date
    from types import SimpleNamespace
    from src.career_intelligence.freshness import calculate_job_freshness
    from src.career_intelligence.ingest_silver import (
        _apply_freshness_to_assessment,
        _refresh_existing_freshness,
    )

    baseline = assess_row("robotics_tpm")
    item = SimpleNamespace(
        freshness=calculate_job_freshness(publication_date="2020-01-01", today=date(2026, 9, 22)),
        provenance={},
    )
    result = _apply_freshness_to_assessment(baseline, item)
    assert result["opportunity_score"] == baseline["opportunity_score"]
    assert result["explanation"]["freshness_ranking_score"] < result["opportunity_score"]
    assert result["recommendation"] == "WATCH"
    existing = copy.deepcopy(baseline)
    assert _refresh_existing_freshness(existing, {}, item)
    assert existing["opportunity_score"] == baseline["opportunity_score"]
    assert existing["recommendation"] == "WATCH"


def test_invalid_weights_cannot_reintroduce_access_into_candidacy():
    from scripts.validate_career_config import validate_strategy
    from src.career_intelligence.classifier import load_career_profile

    profile = load_career_profile()
    validate_strategy(profile)
    profile["strategy_policy"]["candidacy_weights"]["network_access"] = 0.1
    profile["strategy_policy"]["candidacy_weights"]["capability_fit"] -= 0.1
    with pytest.raises(ValueError, match="Access/location"):
        validate_strategy(profile)


def test_missing_description_clears_current_candidacy():
    from types import SimpleNamespace
    from src.career_intelligence.ingest_silver import _remove_missing_description_evidence
    from src.career_intelligence.silver_adapter import ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY

    item = SimpleNamespace(
        description_quality=ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY, provenance={}
    )
    result = _remove_missing_description_evidence(assess_row("robotics_tpm"), item)
    assert result["opportunity_score"] == result["candidate_strength"]["score"] == 0
    assert result["recommendation"] == "WATCH"
