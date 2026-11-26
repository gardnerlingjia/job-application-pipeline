from pathlib import Path
import requests

import pytest

from src.career_intelligence.discovery_store import (
    change_event, cautious_alias, content_hash, parse_source_time, vacancy_keys,
)
from src.career_intelligence.source_adapters import (
    RetrievalLimits, fetch_ashby, fetch_ba, fetch_greenhouse, fetch_lever,
    fetch_smartrecruiters,
)
from src.career_intelligence.discovery_v3 import _load


class Response:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


class Session:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.values.pop(0))


def test_ba_paginates_and_stops_at_empty_page():
    session = Session([
        {"maxErgebnisse": 3, "stellenangebote": [
            {"refnr": str(i), "titel": f"Role {i}", "arbeitgeber": "Acme"}
            for i in range(2)]},
        {"maxErgebnisse": 3, "stellenangebote": [
            {"refnr": "2", "titel": "Role 2", "arbeitgeber": "Acme"}]},
    ])
    result = fetch_ba(query="robotics", location="Berlin", api_key="key",
                      limits=RetrievalLimits(page_size=2, max_pages=4), session=session)
    assert len(session.calls) == 2
    assert [record["external_job_id"] for record in result["records"]] == ["0", "1", "2"]
    assert result["pages_requested"] == 2
    assert result["snapshot_complete"] is False


def test_empty_provider_result_terminates_without_extra_pages():
    session = Session([{"maxErgebnisse": 0, "stellenangebote": []}])
    result = fetch_ba(query="robotics", location="Berlin", api_key="key",
                      limits=RetrievalLimits(page_size=2, max_pages=4), session=session)
    assert result["records"] == []
    assert len(session.calls) == 1
    assert result["snapshot_complete"] is False


def test_ba_v6_zero_match_response_may_omit_ergebnisliste():
    session = Session([{"maxErgebnisse": 0, "page": 1, "size": 25}])
    result = fetch_ba(query="autonomous mobility", location="Berlin", api_key="key",
                      limits=RetrievalLimits(page_size=25, max_pages=3), session=session)
    assert result["records"] == []
    assert len(result["pages"]) == 1


def test_ba_v6_ergebnisliste_fields_are_normalized():
    session = Session([{"maxErgebnisse": 1, "ergebnisliste": [{
        "referenznummer": "BA-1", "stellenangebotsTitel": "Robotik Programmleitung",
        "firma": "Mobility GmbH", "externeURL": "https://jobs.test/ba-1",
        "datumErsteVeroeffentlichung": "2026-11-01",
        "aenderungsdatum": "2026-11-02T10:00:00",
        "stellenlokationen": [{"adresse": {"ort": "Berlin", "land": "Deutschland"}}],
    }]}])
    result = fetch_ba(query="robotics", location="Berlin", api_key="key",
                      limits=RetrievalLimits(page_size=10), session=session)
    row = result["records"][0]
    assert row["title"] == "Robotik Programmleitung"
    assert row["company_name"] == "Mobility GmbH"
    assert row["location"] == "Berlin, Deutschland"
    assert row["publication_date"] == "2026-11-01"
    assert row["source_updated_at"] == "2026-11-02T10:00:00"


def test_provider_errors_retry_are_bounded():
    class RecoveringSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise requests.ConnectionError("temporary")
            return Response({"jobs": []})

    from src.career_intelligence.source_adapters import _get_json
    session = RecoveringSession()
    payload = _get_json(session, "https://example.test", limits=RetrievalLimits(
        max_retries=2, retry_backoff_seconds=0))
    assert payload == {"jobs": []}
    assert session.calls == 3


@pytest.mark.parametrize("fetch,kwargs,response,count", [
    (fetch_greenhouse, {"board_id": "moia", "employer": "MOIA"},
     {"jobs": [{"id": 1, "title": "Lead", "absolute_url": "https://jobs/1",
                "updated_at": "2026-01-01"}]}, 1),
    (fetch_lever, {"board_id": "acme", "employer": "Acme"},
     [{"id": "x", "text": "Lead", "hostedUrl": "https://jobs/x",
       "createdAt": 1_760_000_000_000, "updatedAt": 1_760_000_100_000}], 1),
    (fetch_ashby, {"board_id": "acme", "employer": "Acme"},
     {"jobs": [{"title": "Lead", "jobUrl": "https://jobs/x", "isListed": True,
       "publishedAt": "2026-11-01T00:00:00Z"}]}, 1),
    (fetch_smartrecruiters, {"board_id": "acme", "employer": "Acme"},
     {"totalFound": 1, "content": [{"id": "x", "name": "Lead",
       "ref": "https://jobs/x"}]}, 1),
])
def test_ats_adapters_normalize_public_listings(fetch, kwargs, response, count):
    session = Session([response])
    result = fetch(**kwargs, limits=RetrievalLimits(), session=session,
                   **({"location": "Germany"} if fetch is fetch_lever else
                      {"country": "DE"} if fetch is fetch_smartrecruiters else {}))
    assert len(result["records"]) == count
    assert result["records"][0]["title"] == "Lead"
    assert result["pages_requested"] == 1
    assert result["snapshot_complete"] is True
    if fetch is fetch_lever:
        assert session.calls[0][1]["params"]["location"] == "Germany"
        assert result["records"][0]["publication_date"] == 1_760_000_000_000
        assert result["records"][0]["source_updated_at"] == 1_760_000_100_000
    if fetch is fetch_ashby:
        assert result["records"][0]["publication_date"] == "2026-11-01T00:00:00Z"
        assert result["records"][0]["source_updated_at"] is None
    if fetch is fetch_smartrecruiters:
        assert session.calls[0][1]["params"]["country"] == "de"


def test_identity_prefers_source_id_then_canonical_url_and_conservative_alias():
    record = {"source_name": "lever:acme", "external_job_id": "123",
              "source_url": "https://jobs.test/a?utm_source=x", "company_name": "Acme",
              "title": "Senior Lead", "location": "Berlin"}
    changed_url = {**record, "source_url": "https://jobs.test/a?utm_source=y"}
    assert vacancy_keys(record) == vacancy_keys(changed_url)
    assert cautious_alias(record) == cautious_alias(changed_url)
    assert content_hash(record) != content_hash(changed_url)
    assert cautious_alias({"company_name": "Acme", "title": "Lead", "location": ""}) is None


def test_repeated_and_changed_observations_have_distinct_event_semantics():
    record = {"title": "Lead", "company_name": "Acme", "location": "Berlin"}
    original = content_hash(record)
    assert change_event(original, original) is None
    assert change_event(original, content_hash({**record, "title": "Director"})) == "changed"
    assert change_event(original, original, lifecycle="removed") == "reappeared"
    assert parse_source_time(1_700_000_000_000) is not None
    assert parse_source_time("not-a-date") is None


def test_ba_query_location_variants_do_not_change_stable_content_hash():
    row = {"source_name": "bundesagentur_fuer_arbeit", "title": "Lead",
           "company_name": "Acme", "location": "Berlin", "source_url": "ba://123"}
    assert content_hash(row) == content_hash({**row, "location": "Berlin, Hamburg"})


def test_greenhouse_adapter_marks_moia_unsolicited_application_entries():
    session = Session([{"jobs": [{"id": "1", "title": "Unsolicited Application – Business",
        "absolute_url": "https://jobs.test/1"}]}])
    result = fetch_greenhouse(board_id="moia", employer="MOIA",
        limits=RetrievalLimits(), session=session)
    assert result["records"][0]["vacancy_type"] == "unsolicited_application"


def test_v31_migration_is_additive_and_auditable():
    sql = Path("db/migrations/113_career_intelligence_v31_remediation.sql").read_text()
    for table in ("career_discovery_source_identities", "career_operator_state_transitions"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "consecutive_complete_absences, removed_at" in sql
    assert "MAX(observed_at), 0, NULL" in sql
    assert "split_from_legacy" in sql and "needs_review" in sql
    assert "DELETE FROM career_discovery_observations" not in sql
    snapshot_sql = Path("db/migrations/114_persist_discovery_snapshot_completeness.sql").read_text()
    assert "snapshot_complete BOOLEAN NOT NULL DEFAULT FALSE" in snapshot_sql


def test_v3_request_budget_and_scope_are_bounded():
    config = _load(Path("config/career_discovery_v3.yaml"))
    plan_size = sum(len(terms) for terms in config["profiles"].values()) * len(
        config["geographic_scopes"]["bundesagentur_fuer_arbeit"])
    assert plan_size * config["request_budget"]["max_pages_per_query"] <= config[
        "request_budget"]["max_requests_per_run"]
    assert config["geographic_scopes"]["bundesagentur_fuer_arbeit"] == ["Berlin", "Deutschland"]
    assert {"NL", "AT", "CH"}.issubset(config["geographic_scopes"]["employer_boards"])


def test_v3_migration_keeps_observations_separate_from_assessments():
    sql = Path("db/migrations/110_career_intelligence_v3_discovery.sql").read_text()
    for table in ("career_discovery_sources", "career_discovery_runs",
                  "career_discovery_vacancies", "career_discovery_observations",
                  "career_discovery_events", "career_discovery_vacancy_aliases"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "job_product_assessments" not in sql
    assert "operator_state" not in sql
    sql2 = Path("db/migrations/111_career_discovery_run_groups_and_presence.sql").read_text()
    assert "run_group_id UUID" in sql2
    assert "consecutive_complete_absences" in sql2
    sql3 = Path("db/migrations/112_allow_repeated_vacancy_observations.sql").read_text()
    assert "DROP CONSTRAINT IF EXISTS" in sql3
    assert "source_job_id, observed_at DESC" in sql3
