import pytest

from src.career_intelligence.source_strategy import (
    enrich_source_overview_with_strategy,
    load_source_strategy,
    strategy_from_mapping,
)


def strategy_record(**overrides):
    record = {
        "company_name": "MOIA",
        "source_name": "personio:moia",
        "tier": "A",
        "strategic_priority": 100,
        "relevant_career_lanes": ["autonomous_mobility"],
        "preferred_evidence_type": "employer_origin_vacancy",
        "source_role": "employer_origin",
        "location_relevance": ["Berlin preferred"],
        "status": "active",
    }
    record.update(overrides)
    return record


def source_row(source_name="personio:moia", **overrides):
    row = {
        "candidate_id": 1,
        "source_name": source_name,
        "source_label": "MOIA",
        "source_type": "employer_origin_career_site",
        "candidate_status": "manual_review_required",
        "connector": {
            "implemented": True,
            "implementation_status": "implemented",
            "code_backed_registered": True,
            "registration_status": "registered",
            "connector_class": "src.connectors.personio.PersonioConnector",
        },
        "gates": {
            "connector_validation_gate": {"status": "unknown", "passed": False},
            "final_approval_gate": {"status": "unknown", "passed": False},
        },
        "activation": {"status": "not_activated", "active": False},
        "search_profiles": {
            "profile_count": 0,
            "active_profile_count": 0,
            "active_search_term_count": 0,
        },
        "last_ingestion": {"status": "not_run", "total_loaded": 0, "inserted_count": 0},
        "layers": {"bronze_count": 0, "silver_count": 0},
        "current_blocker": "final_approval_incomplete",
        "next_action": "Complete the final approval gate",
    }
    row.update(overrides)
    return row


def overview(*sources):
    return {
        "schema_version": "pipeline.source_connector_overview.v1",
        "summary": {"source_count": len(sources), "attention_count": 0},
        "sources": list(sources),
        "boundaries": {"read_only": True, "no_source_activation": True},
    }


def test_source_strategy_config_loads_lingjia_tiers():
    strategies = load_source_strategy()

    by_source = {item.source_name: item for item in strategies}
    assert by_source["personio:moia"].tier == "A"
    assert by_source["personio:moia"].source_role == "employer_origin"
    assert by_source["stepstone"].tier == "C"
    assert by_source["stepstone"].source_role == "discovery"
    assert "autonomous_mobility" in by_source["personio:moia"].relevant_career_lanes


def test_source_strategy_validation_rejects_bad_tier_role_pairing():
    with pytest.raises(ValueError, match="Tier C"):
        strategy_from_mapping(strategy_record(tier="C", source_role="employer_origin"))

    with pytest.raises(ValueError, match="must be employer_origin"):
        strategy_from_mapping(strategy_record(tier="A", source_role="discovery"))


def test_source_strategy_classifies_employer_origin_and_discovery_roles():
    employer = strategy_from_mapping(strategy_record())
    discovery = strategy_from_mapping(
        strategy_record(
            company_name="Stepstone",
            source_name="stepstone",
            tier="C",
            strategic_priority=50,
            preferred_evidence_type="discovery_signal",
            source_role="discovery",
        )
    )

    assert employer.tier_label == "Strategic employer"
    assert discovery.tier_label == "Discovery source"


def test_source_strategy_read_model_enriches_existing_source_deterministically():
    result = enrich_source_overview_with_strategy(
        overview(source_row(), source_row("legacy:demo", source_label="Legacy Demo")),
        strategies=[strategy_from_mapping(strategy_record())],
    )

    names = [source["source_name"] for source in result["sources"]]
    assert names == ["personio:moia", "legacy:demo"]
    strategy = result["sources"][0]["career_source_strategy"]
    assert strategy["configured"] is True
    assert strategy["tier"] == "A"
    assert strategy["source_role"] == "employer_origin"
    assert strategy["is_employer_origin"] is True
    assert result["sources"][1]["career_source_strategy"]["strategy_group"] == (
        "Existing generic/demo sources"
    )


def test_source_strategy_adds_missing_configured_source_as_gap():
    result = enrich_source_overview_with_strategy(
        overview(),
        strategies=[strategy_from_mapping(strategy_record(source_name="motor_ai:careers"))],
        registry=FakeRegistry(supported=set()),
    )

    source = result["sources"][0]
    assert source["source_name"] == "motor_ai:careers"
    assert source["career_source_strategy"]["source_status"] == "connector_gap"
    assert source["connector"]["code_backed_registered"] is False
    assert source["activation"]["active"] is False
    assert source["current_blocker"] == "candidate_source_gap"


def test_source_strategy_marks_supported_but_unconfigured_without_activation():
    result = enrich_source_overview_with_strategy(
        overview(),
        strategies=[strategy_from_mapping(strategy_record(source_name="personio:moia"))],
        registry=FakeRegistry(supported={"personio:moia"}),
    )

    source = result["sources"][0]
    assert source["career_source_strategy"]["source_status"] == (
        "connector_supported_unconfigured"
    )
    assert source["connector"]["code_backed_registered"] is True
    assert source["activation"]["active"] is False
    assert source["search_profiles"]["active_profile_count"] == 0
    assert result["boundaries"]["career_source_strategy_does_not_activate_connectors"] is True


def test_source_strategy_summary_preserves_generic_demo_sources():
    result = enrich_source_overview_with_strategy(
        overview(source_row("legacy:demo", source_label="Legacy Demo")),
        strategies=[
            strategy_from_mapping(strategy_record(source_name="personio:moia")),
            strategy_from_mapping(
                strategy_record(
                    company_name="Stepstone",
                    source_name="stepstone",
                    tier="C",
                    strategic_priority=50,
                    preferred_evidence_type="discovery_signal",
                    source_role="discovery",
                )
            ),
        ],
        registry=FakeRegistry(supported={"personio:moia", "stepstone"}),
    )

    assert result["summary"]["career_strategy_tier_a_count"] == 1
    assert result["summary"]["career_strategy_discovery_count"] == 1
    assert result["summary"]["generic_demo_source_count"] == 1
    assert result["boundaries"]["generic_demo_sources_preserved"] is True
    assert result["boundaries"]["employer_origin_preferred_over_discovery_for_career_evidence"] is True


class FakeRegistry:
    def __init__(self, *, supported):
        self.supported = supported

    def create(self, source_name):
        if source_name not in self.supported:
            raise ValueError(f"No connector configured for source: {source_name}")
        return object()
