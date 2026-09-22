"""Practical constraints, specialist exclusions and controlled search intent updates."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.batch import _sort_opportunities
from src.career_intelligence.classifier import strategy_context
from src.career_intelligence.constraints import evaluate_constraints
from src.career_intelligence.discovery_profile_sync import (
    apply_plan, assert_profile_intent, build_plan, desired_profiles,
)
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.market_discovery import load_market_discovery_config


@pytest.mark.parametrize('text,category,travel,compatibility', [
    ('Based in Berlin.', 'berlin_based', 'unknown', 'unknown'),
    ('Germany. Occasional domestic travel.', 'germany_occasional_domestic',
     'occasional_domestic', 'confirmed'),
    ('Remote Germany.', 'germany_unspecified_travel', 'unknown', 'unknown'),
    ('Berlin. Frequent European travel required.', 'frequent_european_travel',
     'frequent_european', 'incompatible'),
    ('Berlin. Travel across Europe 50% of the time.', 'frequent_european_travel',
     'frequent_european', 'incompatible'),
    ('Berlin. Regelmäßige Reisen innerhalb Europas.', 'frequent_european_travel',
     'frequent_european', 'incompatible'),
    ('Berlin. Relocation required.', 'relocation_required', 'unknown', 'incompatible'),
    ('Berlin. No relocation required. No frequent European travel required.',
     'berlin_based', 'unknown', 'unknown'),
    ('Berlin. No travel required.', 'berlin_based', 'none_required', 'confirmed'),
    ('Standort Berlin. Reisebereitschaft von etwa vier bis fünf Tagen pro Monat.',
     'frequent_travel', 'frequent_unspecified', 'incompatible'),
    ('Berlin. Occasional international travel.', 'berlin_based', 'unknown', 'unknown'),
])
def test_practical_evidence(text, category, travel, compatibility):
    result = match_location('Program Manager', text)
    assert result['category'] == category
    assert result['travel_status'] == travel
    assert result['compatibility'] == compatibility


@pytest.mark.parametrize('prefix', ['', 'Senior ', 'Staff ', 'Principal '])
@pytest.mark.parametrize('title', ['AI Engineer', 'Software Engineer', 'ML Engineer',
                                  'Robotics Engineer'])
def test_engineer_variants(prefix, title):
    result = assess_opportunity('Example', prefix + title,
                                'Berlin. Autonomous mobility deployment. No travel required.')
    assert result['recommendation'] == 'SKIP'
    assert result['candidate_strength']['score'] <= 25


@pytest.mark.parametrize('title', ['Technical Program Manager', 'Solution Delivery Lead',
                                  'Autonomous Mobility Deployment Lead'])
def test_adjacent_leaders_can_work_with_engineers(title):
    description = ('Berlin. No travel required. Coordinate senior software engineers, '
                   'staff software engineers and machine learning engineers for autonomous '
                   'mobility deployment and vehicle software delivery.')
    context = strategy_context(title, description)
    assert not context['engineering_mismatch']
    assert evaluate_constraints(title, description)['overall_action'] != 'HIGH_RISK'
    assert assess_opportunity('Example', title, description)['recommendation'] in {
        'APPLY_NOW', 'NETWORK_FIRST'}


def test_research_lead_requires_specialist_evidence():
    # Minimal observed requirement excerpt, not a generic ban on Data Science leadership.
    result = assess_opportunity('Example', 'Teamlead Data Science - Data & AI Research',
        'Standort Berlin. AI adoption. Mehrjährige Berufserfahrung in den Bereichen '
        'Data Science, Machine Learning und KI-Modellentwicklung. '
        'Sehr gute Programmierkenntnisse in Python und SQL. No travel required.')
    assert result['recommendation'] == 'SKIP'
    assert 'specialist_ml_research_requirements' in result['explanation']['fit_signals'][
        'engineering_mismatch']


def test_travel_never_changes_candidacy_but_gates_action():
    args = ('Example', 'Vehicle Software Delivery Lead')
    unknown = assess_opportunity(*args, 'Berlin. Automotive software delivery.')
    confirmed = assess_opportunity(*args, 'Berlin. Automotive software delivery. No travel required.')
    frequent = assess_opportunity(*args, 'Berlin. Automotive software delivery. Frequent European travel.')
    assert unknown['opportunity_score'] == confirmed['opportunity_score'] == frequent['opportunity_score']
    assert unknown['recommendation'] == 'WATCH'
    assert confirmed['recommendation'] == 'APPLY_NOW'
    assert frequent['recommendation'] == 'SKIP'
    assert 'frequent_travel_conflict' in frequent['explanation']['gaps']
    assert 'relocation_conflict' not in frequent['explanation']['gaps']
    assert any(r['constraint'] == 'frequent_travel_required' for r in frequent['hard_skips'])


def test_berlin_is_separate_tie_breaker():
    rows = [dict(company='A', title='Lead', opportunity_score=75,
                 explanation={'location': {'berlin_preference': 0}}),
            dict(company='B', title='Lead', opportunity_score=75,
                 explanation={'location': {'berlin_preference': 1}}),
            dict(company='C', title='Lead', opportunity_score=85)]
    _sort_opportunities(rows)
    assert [r['company'] for r in rows] == ['C', 'B', 'A']


def config_and_rows():
    config = load_market_discovery_config()
    rows = [dict(id=i, profile_name=name, source_name=target['source_name'],
                 search_term=None, search_location='CUSTOM BERLIN', search_radius_km=5,
                 offer_type=1, page_size=15, is_active=False, recurring_ingestion_enabled=False,
                 terms=[dict(search_term=t, is_active=True) for t in target['terms']])
            for i, (name, target) in enumerate(desired_profiles(config).items(), 1)]
    return config, rows


def test_sync_diff_preserves_customization_and_operational_state():
    config, rows = config_and_rows()
    rows[0]['terms'].append(dict(search_term='my customized search', is_active=True))
    plan = build_plan(config, rows)
    assert plan['differences'][0]['deactivate'] == ['my customized search']
    assert plan['current'][0]['search_location'] == 'CUSTOM BERLIN'
    assert not plan['current'][0]['is_active']
    changed = deepcopy(rows)
    changed[0]['page_size'] = 20
    assert build_plan(config, changed)['approval_digest'] != plan['approval_digest']
    assert not build_plan(config, config_and_rows()[1])['differences']
    assert build_plan(config, rows[1:])['blockers']
    changed[0]['source_name'] = 'unapproved-provider'
    assert build_plan(config, changed)['blockers']


def test_apply_requires_exact_review_and_writes_only_terms(monkeypatch):
    config, rows = config_and_rows()
    rows[0]['terms'] = [dict(search_term='my customized search', is_active=True)]
    monkeypatch.setattr('src.career_intelligence.discovery_profile_sync.read_profiles',
                        lambda *args: rows)
    conn = Mock()
    from contextlib import nullcontext
    conn.transaction.side_effect = nullcontext
    with pytest.raises(ValueError, match='changed'):
        apply_plan(conn, config, 'stale-digest')
    assert len(conn.execute.call_args_list) == 1  # lock only; no mutation
    conn.reset_mock()
    apply_plan(conn, config, build_plan(config, rows)['approval_digest'])
    statements = [call.args[0] for call in conn.execute.call_args_list]
    assert any('UPDATE search_terms' in sql for sql in statements)
    assert not any('UPDATE search_profiles' in sql or 'INSERT INTO search_profiles' in sql
                   for sql in statements)
    assert all('search_terms' in sql for sql in statements)


def test_generic_ingestion_rejects_stale_terms_before_connector(monkeypatch):
    from src.ingest_jobs import run_profile
    config, rows = config_and_rows()
    row = rows[0]
    profile = SimpleNamespace(**{k: v for k, v in row.items() if k != 'terms'})
    repository = Mock()
    repository.load_active_search_terms.return_value = [(profile, SimpleNamespace(search_term='AI engineer'))]
    connector = Mock()
    monkeypatch.setattr('src.ingest_jobs.create_connector', connector)
    with pytest.raises(ValueError, match='drift'):
        run_profile(repository, profile)
    connector.assert_not_called()
    target = desired_profiles(config)[profile.profile_name]
    repository.load_active_search_terms.return_value = [
        (profile, SimpleNamespace(search_term=t)) for t in target['terms']]
    assert_profile_intent(repository, profile)


@pytest.mark.parametrize('description', [
    'Berlin. Regular European travel required.',
    'Berlin. Travel two days per week across Europe.',
    'Berlin. 30% travel within Germany required.',
])
def test_explicit_frequent_travel_forms(description):
    result = match_location('Program Manager', description)
    assert result['compatibility'] == 'incompatible'


def test_control_center_uses_berlin_signal_without_reassessment():
    from src.career_intelligence.control_center import _record_sort_key
    rows = [dict(company='A', opportunity_score=75, berlin_preference=0),
            dict(company='B', opportunity_score=75, berlin_preference=1)]
    assert sorted(rows, key=_record_sort_key)[0]['company'] == 'B'


def test_v3_historical_artifacts_remain_exact():
    import hashlib
    import json
    from pathlib import Path
    root = Path('tests/fixtures/career_intelligence')
    manifest = json.loads((root / 'strategy_calibration.v3.manifest.json').read_text())
    for suffix in ('json', 'results.json', 'config.json'):
        path = root / f'strategy_calibration.v3.{suffix}'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest['sha256'][str(path)]


def test_seed_contract_is_frozen_and_customizations_are_not_seed(monkeypatch):
    import hashlib
    import json
    from pathlib import Path
    from contextlib import nullcontext
    from src.career_intelligence.discovery_profile_sync import matches_original_seed
    baseline = json.loads(Path('config/career_discovery_profile_seed.v1.json').read_text())
    assert hashlib.sha256(Path(baseline['migration']).read_bytes()).hexdigest() == baseline['migration_sha256']
    name, row = next(iter(baseline['profiles'].items()))
    assert matches_original_seed(name, row)
    row['terms'].append(dict(search_term='my customized term', is_active=True))
    assert not matches_original_seed(name, row)
    config, rows = config_and_rows()
    rows[0]['terms'] = row['terms']
    monkeypatch.setattr('src.career_intelligence.discovery_profile_sync.read_profiles',
                        lambda *args: rows)
    conn = Mock()
    conn.transaction.side_effect = nullcontext
    with pytest.raises(ValueError, match='Customized'):
        apply_plan(conn, config, build_plan(config, rows)['approval_digest'], seed_only=True)
    assert len(conn.execute.call_args_list) == 1


@pytest.mark.parametrize('text,status', [
    ('Berlin. No relocation required and frequent European travel required.', 'incompatible'),
    ('Berlin. No frequent travel required, but weekly European travel required.', 'incompatible'),
    ('Berlin. Occasional domestic travel. Not required to relocate to Munich.', 'confirmed'),
    ('Berlin. Optional frequent European travel.', 'unknown'),
    ('Germany. Travel up to 10 days per month.', 'incompatible'),
])
def test_negation_and_optional_scope(text, status):
    assert match_location('Program Lead', text)['compatibility'] == status


def test_germany_occasional_domestic_is_eligible():
    result = assess_opportunity('Example', 'Vehicle Software Delivery Lead',
                                'Germany. Automotive software delivery. Occasional domestic travel.')
    assert result['recommendation'] == 'APPLY_NOW'


def test_berlin_headquarters_is_not_role_base():
    result = match_location('Program Lead', 'Remote Germany. Headquarters Berlin. No travel required.')
    assert result['berlin_preference'] == 0


def test_optional_research_exposure_is_not_specialist_requirement():
    context = strategy_context('Data Science Transformation Program Lead',
                               'Berlin. No strong Python programming required. AI adoption.')
    assert not context['engineering_mismatch']


def test_infrequent_domestic_travel_is_not_frequent():
    result = match_location('Program Lead', 'Germany. Infrequent domestic travel.')
    assert result['travel_status'] == 'occasional_domestic'
    assert result['compatibility'] == 'confirmed'


def test_doctor_distinguishes_successful_nonempty_ingestion_from_zero_results():
    import sqlite3
    from contextlib import contextmanager
    from src.career_intelligence.market_discovery import DatabaseMarketDiscoveryOperations
    database = sqlite3.connect(':memory:')
    database.execute('CREATE TABLE ingestion_runs (source_name TEXT, status TEXT, total_loaded INT)')
    database.executemany('INSERT INTO ingestion_runs VALUES (?, ?, ?)', [
        ('stepstone', 'success', 15), ('bundesagentur_fuer_arbeit', 'success', 0),
        ('bundesagentur_fuer_arbeit', 'failed', 15),
    ])

    class Connection:
        @contextmanager
        def cursor(self, **kwargs):
            class Cursor:
                def execute(self, sql, parameters):
                    self.result = database.execute(sql.replace('%s', '?'), parameters)

                def fetchone(self):
                    return self.result.fetchone()
            yield Cursor()

    config = load_market_discovery_config()
    lines = DatabaseMarketDiscoveryOperations()._source_status_lines(
        Connection(), config, active_profiles=set(config.configured_profile_names()))
    stepstone = next(line for line in lines if '- StepStone:' in line)
    ba = next(line for line in lines if '- Bundesagentur' in line)
    assert 'implementation_status=LIVE' in stepstone
    assert 'live_fetch_verified=true' in stepstone
    assert 'live_fetch_verified=false' in ba
    database.close()


def test_v4_archive_integrity_and_identical_historical_inputs():
    import hashlib
    import json
    from pathlib import Path
    root = Path('tests/fixtures/career_intelligence')
    manifest = json.loads((root / 'strategy_calibration.v4.manifest.json').read_text())
    for suffix in ('json', 'results.json', 'config.json'):
        path = root / f'strategy_calibration.v4.{suffix}'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest['sha256'][str(path)]
    before = json.loads((root / 'strategy_calibration.v3.json').read_text())
    after = json.loads((root / 'strategy_calibration.v4.json').read_text())
    for old, new in zip(before, after, strict=True):
        for field in ('key', 'company', 'title', 'description', 'role_evidence', 'market_evidence'):
            assert old.get(field) == new.get(field)
