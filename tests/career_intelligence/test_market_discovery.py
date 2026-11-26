from pathlib import Path

import pytest

from src.career_intelligence.ingest_silver import deduplicate_silver_inputs
from src.career_intelligence.market_discovery import (
    IngestionProfileResult,
    load_market_discovery_config,
    run_doctor,
    run_market_discovery,
)
from src.career_intelligence.silver_adapter import SilverCareerInput
from src.career_intelligence.silver_adapter import adapt_silver_rows
from src.connectors.registry import SourceRole, source_role
from src.silver.relevance import is_relevant_for_silver


def test_market_discovery_migration_creates_recurring_sensor_profiles_only():
    sql = Path("db/migrations/109_create_lingjia_broad_market_discovery_profiles.sql").read_text(
        encoding="utf-8"
    )

    assert "lingjia_market_stepstone_autonomy_robotics" in sql
    assert "lingjia_market_ba_ai_data_transformation" in sql
    assert "recurring_ingestion_enabled" in sql
    assert "'stepstone'" in sql
    assert "'bundesagentur_fuer_arbeit'" in sql
    assert "CREATE TABLE" not in sql
    assert "INSERT INTO raw_jobs" not in sql


def test_market_discovery_config_loads_broad_profiles_and_sensor_sources():
    config = load_market_discovery_config()

    assert 4 <= len(config.profiles) <= 6
    assert {source.source_name for source in config.active_sources} == {
        "stepstone",
        "bundesagentur_fuer_arbeit",
    }
    assert all(source.source_role == "discovery" for source in config.sources)
    assert all(profile.preferred_evidence_type == "discovery_signal" for profile in config.profiles)
    assert "lingjia_market_stepstone_autonomy_robotics" in config.configured_profile_names()
    assert "lingjia_market_ba_ai_data_transformation" in config.configured_profile_names()


def test_market_discovery_source_priority_order_and_blockers_are_preserved():
    config = load_market_discovery_config()

    assert [source.display_name for source in config.sources] == [
        "LinkedIn Jobs",
        "StepStone",
        "Indeed Germany",
        "XING Jobs",
        "Wellfound",
        "Welcome to the Jungle",
        "Bundesagentur fuer Arbeit",
        "Niche robotics / autonomy / mobility / AI boards",
    ]
    by_name = {source.source_name: source for source in config.sources}
    assert by_name["linkedin_jobs"].implementation_status == (
        "BLOCKED_NO_SUPPORTED_CONNECTOR"
    )
    assert by_name["indeed_germany"].implementation_status == "CONNECTOR_GAP"
    assert by_name["stepstone"].career_priority == 2
    assert by_name["bundesagentur_fuer_arbeit"].career_priority == 7
    assert by_name["stepstone"].implementation_status == "SUPPORTED_UNCONFIGURED"
    assert by_name["bundesagentur_fuer_arbeit"].implementation_status == (
        "SUPPORTED_UNCONFIGURED"
    )
    assert by_name["wellfound"].active is False


def test_market_discovery_config_validation_rejects_employer_origin_source(tmp_path):
    path = tmp_path / "market.yaml"
    path.write_text(
        """
schema_version: career_intelligence.market_discovery.v1
source_policy:
  sources:
    - source_name: greenhouse:moia
      source_role: employer_origin
      strategy_tier: A
      active: true
      profile_prefix: lingjia_market_moia
profiles:
  - key: one
    label: One
    career_lanes: [autonomous_mobility]
    preferred_evidence_type: discovery_signal
    search_terms: [autonomous mobility]
  - key: two
    label: Two
    career_lanes: [ai_data_transformation]
    preferred_evidence_type: discovery_signal
    search_terms: [AI]
  - key: three
    label: Three
    career_lanes: [strategy_operations]
    preferred_evidence_type: discovery_signal
    search_terms: [strategy]
  - key: four
    label: Four
    career_lanes: [mobility_ecosystems]
    preferred_evidence_type: discovery_signal
    search_terms: [mobility]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be discovery"):
        load_market_discovery_config(path)


def test_broad_market_sources_remain_registered_sensors():
    assert source_role("stepstone") == SourceRole.SENSOR
    assert source_role("bundesagentur_fuer_arbeit") == SourceRole.SENSOR


def test_discovery_source_without_description_does_not_receive_ats_relaxation():
    raw_job = {
        "id": 1,
        "source_name": "stepstone",
        "source_url": "https://www.stepstone.de/jobs/autonomous",
        "external_job_id": "123",
        "raw_data": {
            "result_card": {
                "title": "Product Owner Data Platform",
                "company_name": "Unknown Mobility GmbH",
                "location": "Berlin",
                "raw_card_text": "Product Owner Data Platform in Berlin",
            }
        },
    }

    assert is_relevant_for_silver(raw_job) is True
    inputs, errors = adapt_silver_rows(
        [
            {
                "silver_job_id": 1,
                "raw_job_id": 1,
                "source_name": "stepstone",
                "external_job_id": "123",
                "source_url": "https://www.stepstone.de/jobs/autonomous",
                "title": "Product Owner Data Platform",
                "company_name": "Unknown Mobility GmbH",
                "city": "Berlin",
                "postal_code": None,
                "country": "DE",
                "publication_date": None,
                "first_seen_at": None,
                "last_seen_at": None,
                "canonical_source_type": "unknown",
                "canonical_key_candidate": (
                    "unknown mobility :: product owner data platform :: berlin"
                ),
                "raw_data": {"result_card": raw_job["raw_data"]["result_card"]},
            }
        ]
    )

    assert inputs == []
    assert errors[0]["error"] == "missing or empty required fields: description"


def ci_input(source_file, *, source_name, canonical_type, canonical_key):
    return SilverCareerInput(
        company="Example Mobility GmbH",
        title="Senior Mobility Platform Manager",
        description="Lead mobility platform delivery with AI and data teams in Berlin.",
        description_quality="strong",
        freshness=None,  # type: ignore[arg-type]
        source_file=source_file,
        provenance={
            "source_file": source_file,
            "source_name": source_name,
            "canonical_source_type": canonical_type,
            "canonical_key_candidate": canonical_key,
        },
    )


def test_cross_source_dedup_prefers_employer_origin_over_discovery():
    discovery = ci_input(
        "silver-stepstone.json",
        source_name="stepstone",
        canonical_type="unknown",
        canonical_key="example mobility :: senior mobility platform manager :: berlin",
    )
    employer = ci_input(
        "silver-greenhouse-example.json",
        source_name="greenhouse:example",
        canonical_type="employer_origin_ats_backed_career_site",
        canonical_key="example mobility :: senior mobility platform manager :: berlin",
    )

    kept, skipped = deduplicate_silver_inputs([discovery, employer])

    assert [item.source_file for item in kept] == ["silver-greenhouse-example.json"]
    assert skipped == [
        {
            "source_file": "silver-stepstone.json",
            "source_name": "stepstone",
            "canonical_source_type": "unknown",
            "canonical_key_candidate": (
                "example mobility :: senior mobility platform manager :: berlin"
            ),
            "ingestion_status": "skipped",
            "duplicate_of_source_file": "silver-greenhouse-example.json",
            "duplicate_reason": "same_silver_canonical_key",
        }
    ]


class FakeOperations:
    def __init__(self, *, fail_profile=None, doctor_ready=True, fail_enrichment=False):
        self.fail_profile = fail_profile
        self.doctor_ready = doctor_ready
        self.fail_enrichment = fail_enrichment
        self.ingested = []
        self.silver_sources = []
        self.enriched_sources = []
        self.ci_sources = []

    def doctor(self, config):
        if not self.doctor_ready:
            return False, ["BLOCKED: missing schema"], "apply migrations"
        return True, ["PASS"], "run-daily"

    def run_ingestion_profile(self, profile_name):
        self.ingested.append(profile_name)
        source_name = "stepstone" if "stepstone" in profile_name else "bundesagentur_fuer_arbeit"
        if profile_name == self.fail_profile:
            return IngestionProfileResult(
                profile_name=profile_name,
                source_name=source_name,
                loaded=0,
                inserted=0,
                duplicate=0,
                status="failed",
                error="source timeout",
            )
        return IngestionProfileResult(
            profile_name=profile_name,
            source_name=source_name,
            loaded=2,
            inserted=1,
            duplicate=1,
            status="finished",
        )

    def run_silver(self, source_name, *, limit):
        self.silver_sources.append((source_name, limit))
        return 0

    def enrich_details(self, source_name, *, limit):
        self.enriched_sources.append((source_name, limit))
        if self.fail_enrichment:
            raise RuntimeError("detail fetch blocked")
        return {"enriched": 1, "needs_detail": 2, "failed": 0}

    def run_career_intelligence(self, source_name, *, limit):
        self.ci_sources.append((source_name, limit))
        return 0, [
            "Silver jobs loaded: 2",
            "Converted: 1",
            "Newly assessed: 1",
            "Already known/skipped: 0",
            "APPLY_NOW: 0",
            "NETWORK_FIRST: 1",
            "EXPLORE: 0",
            "WATCH: 0",
            "SKIP: 0",
            "NEW: 1",
            "INTERESTED: 0",
            "REVIEWED: 0",
            "DISMISSED: 0",
        ]

    def adaptive_summary(self):
        return {"candidate_count": 1}


def test_doctor_reports_blocker_and_next_command():
    exit_status, lines = run_doctor(operations=FakeOperations(doctor_ready=False))

    assert exit_status == 2
    assert "BLOCKED: missing schema" in lines
    assert "Next: apply migrations" in lines


def test_run_daily_isolates_profile_failure_and_continues():
    failing = "lingjia_market_stepstone_autonomy_robotics"
    operations = FakeOperations(fail_profile=failing)

    exit_status, lines = run_market_discovery(operations=operations, limit=7)

    assert exit_status == 1
    assert failing in operations.ingested
    assert ("bundesagentur_fuer_arbeit", 7) in operations.silver_sources
    assert ("stepstone", 7) in operations.enriched_sources
    assert ("stepstone", 7) in operations.ci_sources
    assert "Ingestion profile errors: 1" in lines
    assert any("source timeout" in line for line in lines)


def test_run_daily_summary_is_deterministic_and_records_adaptive_candidates():
    operations = FakeOperations()

    exit_status, lines = run_market_discovery(operations=operations, limit=5)

    assert exit_status == 0
    assert lines[0] == "Career Intelligence broad market discovery"
    assert "Sources attempted: 2" in lines
    assert "Profiles attempted: 10" in lines
    assert "Bronze jobs loaded: 20" in lines
    assert "Bronze jobs inserted: 10" in lines
    assert "Bronze duplicates/skipped existing: 10" in lines
    assert "Discovery detail enriched: 2" in lines
    assert "Discovery detail needs detail: 4" in lines
    assert "Adaptive source candidates: 1" in lines
    assert operations.silver_sources == [
        ("bundesagentur_fuer_arbeit", 5),
        ("stepstone", 5),
    ]
    assert operations.ci_sources == [
        ("bundesagentur_fuer_arbeit", 5),
        ("stepstone", 5),
    ]


def test_run_daily_isolates_detail_enrichment_failure():
    operations = FakeOperations(fail_enrichment=True)

    exit_status, lines = run_market_discovery(operations=operations, limit=5)

    assert exit_status == 1
    assert "Discovery detail errors: 2" in lines
    assert ("stepstone", 5) in operations.ci_sources
    assert any("detail fetch blocked" in line for line in lines)
