from scripts import run_product_v1_control_center as server
from tests.test_product_v1_career_intelligence_control_center import _handler, _EmptyConnection


def test_preview_endpoint_is_explicit_read_only_and_not_the_default(monkeypatch):
    connections = []
    versions = []

    def connect(**kwargs):
        connections.append(kwargs)
        return _EmptyConnection()

    def market(conn, **kwargs):
        versions.append(kwargs["strategy_version"])
        return {"status": "ready", "strategy_version": kwargs["strategy_version"]}

    monkeypatch.setattr(server.psycopg, "connect", connect)
    monkeypatch.setattr(server, "get_database_config", lambda: {})
    monkeypatch.setattr(server, "load_market_intelligence", market)
    handler, responses = _handler("/api/v1/career-intelligence/market?strategy=v3.4")
    handler.do_GET()
    assert responses[0][0]["strategy_version"] == "v3.4"
    assert "default_transaction_read_only=on" in connections[0]["options"]
    handler, responses = _handler("/api/v1/career-intelligence/market")
    handler.do_GET()
    assert responses[0][0]["strategy_version"] == "v3.3"
    assert versions == ["v3.4", "v3.3"]


def test_unknown_strategy_fails_without_opening_database(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("Invalid preview query must not access database")

    monkeypatch.setattr(server.psycopg, "connect", forbidden)
    handler, responses = _handler("/api/v1/career-intelligence/market?strategy=v9")
    handler.do_GET()
    assert int(responses[0][1]) == 400


def test_native_monitoring_is_json_safe_and_geography_reconciles():
    from datetime import UTC, datetime
    import json
    from src.career_intelligence.discovery_store import load_monitoring_summary

    now = datetime(2026, 11, 19, tzinfo=UTC)

    class Cursor:
        def __init__(self):
            self.answers = iter([
                [], [],
                [("greenhouse:test", None, "DE", "succeeded", 1, 1, 1, 1, 1, 0, 0,
                  True, now, now, [])],
                [(1, ["Berlin, Germany"], "")], [],
            ])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            pass

        def fetchall(self):
            return next(self.answers)

    class Conn:
        def cursor(self, **kwargs):
            assert "row_factory" in kwargs
            return Cursor()

    payload = load_monitoring_summary(Conn())
    assert payload["last_run_at"] == now.isoformat()
    assert payload["geographic_distribution"]["overall_vacancy_count"] == 1
    assert payload["http_requests"] is None  # Request totals are not persisted per run.
    json.dumps(payload)  # The product API intentionally has no permissive default serializer.


def test_deployment_can_select_v34_and_explicit_v33_rollback(monkeypatch):
    from src.career_intelligence.market_intelligence import production_strategy

    monkeypatch.setenv('CAREER_INTELLIGENCE_STRATEGY', 'v3.4')
    monkeypatch.setattr(server, 'get_database_config', lambda: {})
    monkeypatch.setattr(server.psycopg, 'connect', lambda **kwargs: _EmptyConnection())
    monkeypatch.setattr(server, 'load_market_intelligence',
                        lambda conn, **kwargs: {'status': 'ready', **kwargs})
    assert production_strategy() == 'v3.4'
    handler, responses = _handler('/api/v1/career-intelligence/market')
    handler.do_GET()
    assert responses[0][0]['strategy_version'] == 'v3.4'
    handler, responses = _handler('/api/v1/career-intelligence/market?strategy=v3.3')
    handler.do_GET()
    assert responses[0][0]['strategy_version'] == 'v3.3'
    monkeypatch.setenv('CAREER_INTELLIGENCE_STRATEGY', 'invalid')
    import pytest
    with pytest.raises(ValueError):
        production_strategy()
