"""Offline strategy calibration; synthetic descriptions are not live market evidence."""

import json
from pathlib import Path

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.classifier import contains_term, load_career_profile
from src.career_intelligence.network_matcher import match_network
from src.career_intelligence.batch import _load_job

ROWS = json.loads(
    Path("tests/fixtures/career_intelligence/strategy_calibration.v3.json").read_text()
)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["key"])
def test_strategy_examples(row):
    result = assess_opportunity(
        row["company"], row["title"], row["description"], role_evidence=row.get("role_evidence")
    )
    assert result["recommendation"] in row["expected_actions"]
    assert result["explanation"]["recommended_action"] in {
        "APPLY",
        "NETWORK FIRST",
        "WATCH",
        "SKIP",
    }
    assert result["market_evidence"]["hiring_intent_strength"]["status"] == "unknown"
    if row["key"] == "dx":
        assert result["access_type"] == "referral-based"
        assert result["recommendation"] == "WATCH"
        assert result["candidate_strength"]["score"] < 60
        assert any(
            r["constraint"] == "several_years_formal_product_owner_required"
            for r in result["high_risks"]
        )
    if row["key"] == "cariad":
        assert result["transition"] == "bridge"
        assert "cloud_mlops_depth_missing" in result["explanation"]["gaps"]
    if row["key"] == "freenow":
        assert "commercial_ownership_needs_evidence" in result["explanation"]["gaps"]


def test_allocations_and_term_boundaries():
    lanes = load_career_profile()["career_lanes"]
    assert [
        lanes[k]["allocation_percent"]
        for k in ("autonomy_robotics", "technology_programs", "ai_data_transformation")
    ] == [55, 25, 20]
    assert not contains_term("chair maintenance lead", "AI")
    assert not contains_term("lead", "AD")


def test_referral_never_overrides_engineering_mismatch():
    evidence = {
        "network": {
            "relationship_level": "internal_sponsor",
            "status": "confirmed",
            "evidence_source": "test fixture",
        }
    }
    result = assess_opportunity(
        "Example",
        "Robotics Perception Engineer",
        "Berlin. ROS 2, C++ and perception algorithms.",
        role_evidence=evidence,
    )
    assert result["recommendation"] == "SKIP"
    assert result["candidate_strength"]["score"] <= 25


def test_unconfirmed_network_is_not_positive_evidence():
    result = match_network(
        "Unknown",
        role_evidence={
            "network": {
                "relationship_level": "employee_referral",
                "status": "unknown",
                "evidence_source": "test",
            }
        },
    )
    assert result["network_access"] == 0
    assert result["access_type"] == "cold"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Remote Germany. Headquarters Munich.", False),
        ("Berlin. No relocation required.", False),
        ("Daily presence in Hamburg required.", True),
        ("Munich on-site.", True),
        ("Europe-China collaboration. Berlin.", False),
    ],
)
def test_location_presence(description, expected):
    result = assess_opportunity("Example", "ADAS Delivery Lead", description)
    assert (result["recommendation"] == "SKIP") == expected


def test_market_unknown_and_inferred_do_not_change_scores():
    args = ("Example", "Vehicle Software Delivery Lead", "Berlin. Automotive software delivery.")
    baseline = assess_opportunity(*args)
    market = {
        "traditional_automotive_exposure": {
            "value": True,
            "status": "inferred",
            "evidence_source": "fixture",
            "evidence_freshness": "2026-09-15",
        }
    }
    inferred = assess_opportunity(*args, market_evidence=market)
    assert inferred["opportunity_score"] == baseline["opportunity_score"]
    assert "automotive_headcount_exposure" not in inferred["explanation"]["gaps"]
    market["traditional_automotive_exposure"]["status"] = "confirmed"
    confirmed = assess_opportunity(*args, market_evidence=market)
    assert "automotive_headcount_exposure" in confirmed["explanation"]["gaps"]
    market["traditional_automotive_exposure"].pop("evidence_source")
    assert (
        assess_opportunity(*args, market_evidence=market)["market_evidence"][
            "traditional_automotive_exposure"
        ]["status"]
        == "unknown"
    )


def test_batch_preserves_optional_evidence(tmp_path):
    row = next(row for row in ROWS if row["key"] == "dx")
    path = tmp_path / "role.json"
    path.write_text(json.dumps(row))
    assert _load_job(path)["role_evidence"] == row["role_evidence"]


def test_planned_project_does_not_count_as_completed_evidence(monkeypatch):
    from src.career_intelligence import capability_matcher

    monkeypatch.setattr(
        capability_matcher,
        "load_capability_profile",
        lambda: {
            "capabilities": {
                "ros2": {
                    "strength": 5,
                    "category": "core",
                    "match_keywords": ["ROS 2"],
                    "evidence_status": "in_development",
                    "evidence": ["planned project"],
                }
            }
        },
    )
    assert capability_matcher.match_capabilities("ROS 2", "")["matched_capabilities"] == []


def test_traditional_automotive_keywords_do_not_qualify_generic_delivery():
    result = assess_opportunity(
        "Example",
        "Automotive Program Manager",
        "Berlin. Traditional mechanical component delivery.",
    )
    assert result["transition"] == "unknown"
    assert result["recommendation"] in {"WATCH", "SKIP"}


def test_confirmed_budget_freeze_caps_action_but_unknown_does_not():
    args = ("Example", "ADAS Delivery Lead", "Berlin. Vehicle software delivery.")
    market = {
        "funding_or_budget_signal": {
            "value": "frozen",
            "status": "confirmed",
            "evidence_source": "synthetic fixture",
        }
    }
    assert assess_opportunity(*args, market_evidence=market)["recommendation"] == "WATCH"
    market["funding_or_budget_signal"]["status"] = "unknown"
    assert (
        assess_opportunity(*args, market_evidence=market)["recommendation"]
        == assess_opportunity(*args)["recommendation"]
    )
