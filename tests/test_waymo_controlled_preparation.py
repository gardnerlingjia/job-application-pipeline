from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json

import pytest

from src.connectors.base import SearchProfile, SearchTerm
from src.connectors.greenhouse import GreenhouseConnector
from src.connectors.greenhouse_location import germany_location_decision
from src.search_intelligence.controlled_profile import load_controlled_profile
from src.silver.transformer import transform_greenhouse_raw_job
from src.career_intelligence.silver_adapter import adapt_silver_row
from src.career_intelligence.assessor import assess_opportunity
from scripts import run_validated_connector_controlled_activation as activation

PROFILE = SearchProfile(0, 'waymo_controlled_germany_mobility', 'greenhouse:waymo',
                        'Germany', None, None, 25)
EXAMPLES = [(8063637, 'Program Manager, Germany Regulatory'),
            (8108104, 'Strategy & BizOps Lead, Germany'),
            (8109449, 'Emergency Services Liaison, Germany'),
            (7922569, 'Lead Diagnostic Technician')]


def test_complete_description_bronze_silver_assessor_and_filter(monkeypatch):
    content = '&lt;p&gt;Lead regulatory deployment programs in Munich, Germany.&lt;/p&gt;' + (
        '&lt;p&gt;Coordinate delivery and partners.&lt;/p&gt;' * 500)
    jobs = [{'id': i, 'title': title, 'content': content,
             'absolute_url': f'https://careers.withwaymo.com/jobs?gh_jid={i}',
             'location': {'name': 'Munich, Bavaria, Germany'}} for i, title in EXAMPLES]
    jobs += [{'id': 1, 'location': {'name': 'San Francisco, United States'}},
             {'id': 2, 'location': {'name': 'Remote Europe'}}, {'id': 3}]
    original = deepcopy(jobs)
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'jobs': jobs}
    def get(url, **kwargs):
        assert url.endswith('/waymo/jobs?content=true')
        return Response()
    monkeypatch.setattr('src.connectors.greenhouse.requests.get', get)
    connector = GreenhouseConnector('waymo')
    records, _ = connector.fetch_jobs(PROFILE, SearchTerm('*'))
    assert jobs == original
    assert len(records) == 4
    assert [r['reason'] for r in connector.last_location_filter_report[-3:]] == [
        'verified_outside_germany', 'ambiguous_location', 'missing_location']
    raw = {'id': 1, 'source_name': records[0].source_name, 'source_url': records[0].source_url,
           'external_job_id': records[0].external_job_id, 'raw_data': records[0].raw_data}
    silver = transform_greenhouse_raw_job(raw)
    item = adapt_silver_row({**silver, 'silver_job_id': 1, 'raw_data': raw['raw_data']})
    assert len(item.description) > 12000
    assert item.description.count('Coordinate delivery and partners.') == 500
    assert raw['raw_data']['job']['content'] == content
    assert silver['city'] == 'Munich, Bavaria, Germany'
    assert item.description_quality == 'strong'
    result = assess_opportunity(item.company, item.title, item.description)
    assert result['explanation']['semantics_version'] == 4
    assert result['explanation']['location']['berlin_preference'] == 0
    # Existing city-specific profiles retain full board acquisition behavior.
    all_records, _ = connector.fetch_jobs(replace(PROFILE, search_location='Hannover'), SearchTerm('*'))
    assert len(all_records) == 7


@pytest.mark.parametrize('location,reason', [
    ('Berlin, Germany', 'verified_germany'), ('Munich, Germany', 'verified_germany'),
    ('Berlin', 'ambiguous_location'), ('Germany / United Kingdom', 'mixed_country_location'),
    ('Remote', 'ambiguous_location'), ('Paris, France', 'verified_outside_germany'),
    ('Deutschland', 'verified_germany'), ('DE', 'ambiguous_location')])
def test_country_decisions(location, reason):
    assert germany_location_decision({'location': {'name': location}})['reason'] == reason


def test_waymo_requires_explicit_scope_before_database_access():
    with pytest.raises(ValueError, match='explicit'):
        activation.build_preflight(conn=None, company_key='waymo')


@pytest.mark.parametrize('change', [{'recurring_ingestion_enabled': True},
                                  {'search_terms': ['*']}, {'search_location': 'Hannover'},
                                  {'company_key': 'other'}])
def test_profile_fails_closed(tmp_path, change):
    value = json.loads(Path('config/waymo_controlled_profile.json').read_text())
    value.update(change)
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_controlled_profile(path, 'waymo')


def test_profile_preserves_explicit_scope_and_disabled_recurring():
    value = load_controlled_profile(Path('config/waymo_controlled_profile.json'), 'waymo')
    assert value['source_name'] == 'greenhouse:waymo'
    assert value['recurring_ingestion_enabled'] is False
    assert 'regulatory' in value['search_terms']


def test_explicit_profile_does_not_bypass_gates(monkeypatch):
    scope = load_controlled_profile(Path('config/waymo_controlled_profile.json'), 'waymo')
    def readiness(**kwargs):
        assert kwargs['profile_config'] == scope
        return {'candidate': {'candidate_id': 1, 'status': 'candidate'},
                'active_search_profile_count': 0, 'overall_readiness': 'activation_readiness_supported'}
    monkeypatch.setattr(activation, 'run_activation_readiness', readiness)
    monkeypatch.setattr(activation, 'gate_passed', lambda *a, **kw: False)
    monkeypatch.setattr(activation, 'load_a1_policy', lambda *a: None)
    _, decision, _ = activation.build_preflight(conn=None, company_key='waymo', profile_config=scope)
    assert not decision.allowed


def test_apply_uses_reviewed_scope_and_all_terms_without_recurring():
    from types import SimpleNamespace
    scope = load_controlled_profile(Path('config/waymo_controlled_profile.json'), 'waymo')
    class Connection:
        def __init__(self):
            self.calls = []
            self.answers = iter([None, {'id': 7, 'profile_name': scope['profile_name']}, {'id': 8}])
        def cursor(self, **kwargs):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, sql, params):
            self.calls.append((sql, params))
        def fetchone(self):
            return next(self.answers)
    conn = Connection()
    readiness = {'candidate': {'candidate_id': 1, 'company_key': 'waymo',
                              'source_name_candidate': 'greenhouse:waymo'},
                 'controlled_profile': scope, 'overall_readiness': 'activation_readiness_supported',
                 'candidate_count': 3, 'evaluable_candidate_count': 3, 'non_job_preview_count': 0}
    activation.apply_activation(conn=conn, readiness=readiness,
                                decision=SimpleNamespace(allowed=True),
                                policy=SimpleNamespace(policy_key='test', policy_version='1'))
    sql, params = next(x for x in conn.calls if 'INSERT INTO search_profiles' in x[0])
    assert params[0] == scope['profile_name'] and params[3] == 'Germany' and params[4] is None
    assert 'TRUE, FALSE' in sql
    assert [args[1] for sql, args in conn.calls if 'INSERT INTO search_terms' in sql] == scope['search_terms']
