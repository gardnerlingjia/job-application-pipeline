from __future__ import annotations

import json

import pytest

from src.career_intelligence.adaptive_sources import (
    derive_adaptive_source_candidates,
    derive_source_advisories,
    load_adaptive_source_read_model,
    load_adaptive_source_rules,
    normalize_company_key,
    set_adaptive_source_decision,
    validate_decision,
)
from src.career_intelligence.source_strategy import strategy_from_mapping


def _rules():
    return load_adaptive_source_rules()


def _strategy(**overrides):
    record = {
        "company_name": "MOIA",
        "source_name": "greenhouse:moia",
        "tier": "A",
        "strategic_priority": 100,
        "relevant_career_lanes": ["autonomy_robotics"],
        "preferred_evidence_type": "employer_origin_vacancy",
        "source_role": "employer_origin",
        "location_relevance": ["Berlin preferred"],
        "status": "active",
    }
    record.update(overrides)
    return strategy_from_mapping(record)


def _opportunity(
    source_file: str,
    *,
    company: str = "Fleet Robotics GmbH",
    score: int = 88,
    recommendation: str = "APPLY_NOW",
    lane: str = "autonomy_robotics",
):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "company": company,
        "title": "Senior Robotics Program Lead Berlin",
        "career_lane": lane,
        "career_lane_label": "Autonomy Robotics",
        "opportunity_score": score,
        "recommendation": recommendation,
        "constraint_action": "review",
        "risks": [],
        "key_matched_capabilities": [],
    }


def _provenance(
    source_file: str,
    *,
    source_name: str = "employer:fleet_robotics",
    quality: str = "strong",
    source_url: str = "https://example.test/jobs/berlin",
    canonical_type: str = "employer_origin",
):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "ingestion_status": "assessed",
        "stable_identity_type": "source_name_external_job_id",
        "stable_identity_sha256": "abc",
        "description_source": "job.description",
        "description_quality": quality,
        "silver_job_id": 1,
        "raw_job_id": 1,
        "source_name": source_name,
        "external_job_id": source_file,
        "source_url": source_url,
        "canonical_source_type": canonical_type,
        "canonical_key_candidate": None,
    }


def test_config_loading_and_company_normalization():
    rules = _rules()

    assert rules.lookback_days == 60
    assert "autonomy_robotics" in rules.primary_lanes
    assert normalize_company_key("Fleet Robotics GmbH") == "fleet robotics"
    assert normalize_company_key("Fleet Robotics AG") == "fleet robotics"


def test_repeated_opportunities_aggregate_and_suggest_tier_a():
    candidates = derive_adaptive_source_candidates(
        [
            _opportunity("a.json", score=91),
            _opportunity("b.json", score=86, recommendation="NETWORK_FIRST"),
        ],
        [_provenance("a.json"), _provenance("b.json")],
        strategies=[],
        rules=_rules(),
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["company_name"] == "Fleet Robotics GmbH"
    assert candidate["normalized_company_key"] == "fleet robotics"
    assert candidate["observed_opportunity_count"] == 2
    assert candidate["assessed_opportunity_count"] == 2
    assert candidate["highest_opportunity_score"] == 91
    assert candidate["average_opportunity_score"] == 88.5
    assert candidate["recommendations_distribution"]["APPLY_NOW"] == 1
    assert candidate["recommendations_distribution"]["NETWORK_FIRST"] == 1
    assert candidate["employer_origin_evidence_available"] is True
    assert candidate["suggested_action"] == "PROMOTE_TO_TIER_A"
    assert "employer-origin evidence available" in candidate["promotion_reasons"]


def test_existing_configured_sources_are_not_duplicated_as_candidates():
    candidates = derive_adaptive_source_candidates(
        [_opportunity("moia.json", company="MOIA")],
        [_provenance("moia.json", source_name="greenhouse:moia")],
        strategies=[_strategy()],
        rules=_rules(),
    )

    assert candidates == []


def test_tier_b_watch_ignore_location_and_weak_evidence_paths():
    tier_b = derive_adaptive_source_candidates(
        [_opportunity("b.json", score=74, lane="ai_data_transformation")],
        [_provenance("b.json")],
        strategies=[],
        rules=_rules(),
    )[0]
    watch = derive_adaptive_source_candidates(
        [_opportunity("w.json", score=81)],
        [_provenance("w.json", quality="weak", canonical_type="aggregator")],
        strategies=[],
        rules=_rules(),
    )[0]
    ignored = derive_adaptive_source_candidates(
        [_opportunity("i.json", score=90)],
        [_provenance("i.json", source_url="https://example.test/jobs/munich")],
        strategies=[],
        rules=_rules(),
    )[0]

    assert tier_b["suggested_action"] == "PROMOTE_TO_TIER_B"
    assert watch["suggested_action"] == "WATCH"
    assert watch["discovery_source_evidence_available"] is True
    assert "weak evidence quality" in watch["promotion_reasons"]
    assert ignored["suggested_action"] == "IGNORE"
    assert ignored["location_constraint_conflicts"] is True


def test_operator_decision_persistence_is_validated_and_survives_rerun(tmp_path):
    path = tmp_path / "adaptive_source_state.json"

    payload = set_adaptive_source_decision(
        normalized_company_key="Fleet Robotics GmbH",
        company_name="Fleet Robotics GmbH",
        decision="PROMOTED_A",
        path=path,
    )

    assert payload["decisions"]["fleet robotics"]["decision"] == "PROMOTED_A"
    assert validate_decision("ignored") == "IGNORED"
    with pytest.raises(ValueError, match="invalid adaptive source decision"):
        set_adaptive_source_decision(
            normalized_company_key="Fleet Robotics",
            decision="ACTIVATE",
            path=path,
        )
    candidates = derive_adaptive_source_candidates(
        [_opportunity("a.json")],
        [_provenance("a.json")],
        strategies=[],
        rules=_rules(),
        state_payload=json.loads(path.read_text(encoding="utf-8")),
    )
    assert candidates[0]["operator_decision"] == "PROMOTED_A"


def test_malformed_state_fails_closed_without_product_authority(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    state = tmp_path / "state.json"
    state.write_text("{bad json", encoding="utf-8")
    (results / "opportunities.json").write_text("[]\n", encoding="utf-8")
    (results / "silver_ingestion_provenance.json").write_text("[]\n", encoding="utf-8")

    payload = load_adaptive_source_read_model(results=results, state_path=state)

    assert payload["available"] is False
    assert payload["candidates"] == []
    assert payload["summary"]["candidate_count"] == 0


def test_source_advisories_are_advisory_only():
    advisories = derive_source_advisories(
        [_opportunity("moia.json", company="MOIA", score=40)],
        [_provenance("moia.json", source_name="greenhouse:moia")],
        strategies=[_strategy()],
    )

    assert advisories["greenhouse:moia"]["status"] == "LOW_RELEVANCE"
    assert advisories["greenhouse:moia"]["automatic_downgrade"] is False


def test_candidates_sort_deterministically():
    candidates = derive_adaptive_source_candidates(
        [
            _opportunity("b.json", company="Beta Robotics", score=80),
            _opportunity("a.json", company="Alpha Robotics", score=80),
        ],
        [_provenance("b.json"), _provenance("a.json")],
        strategies=[],
        rules=_rules(),
    )

    assert [candidate["company_name"] for candidate in candidates] == [
        "Alpha Robotics",
        "Beta Robotics",
    ]
