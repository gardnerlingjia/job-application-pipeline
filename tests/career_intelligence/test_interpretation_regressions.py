"""Captured full-job regressions; expected evidence rather than fixed scores."""
import hashlib
import json
from pathlib import Path

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.capability_matcher import match_capabilities
from src.career_intelligence.classifier import strategy_context
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.role_text import description_sections

ROWS = json.loads(Path(
    'tests/fixtures/career_intelligence/role_interpretation_regressions_v1.json').read_text())


@pytest.mark.parametrize('row', ROWS, ids=lambda r: r['company'])
def test_six_captured_roles(row):
    assert hashlib.sha256(row['description'].encode()).hexdigest() == row['description_sha256']
    result = assess_opportunity(row['company'], row['title'], row['description'],
                                structured_location=row['structured_location'])
    exp = result['explanation']
    sections = description_sections(row['description'])
    if 'Atlantic' in row['company']:
        assert 'Drive the adoption of Microsoft Copilot' in sections['duties']
        assert 'adoption' in exp['fit_signals']['delivery_matches']
        assert result['recommendation'] == 'WATCH'
    elif 'Oldendorff' in row['company']:
        assert 'Own the roadmap and prioritization' in sections['duties']
        assert 'Coordinate testing, rollout, adoption' in sections['duties']
        assert exp['fit_signals']['delivery_matches']
    elif 'Valora' in row['company']:
        assert 'steuerung eines portfolios' in exp['fit_signals']['delivery_matches']
        matches = {m['capability']: m for m in result['matched_capabilities']}
        assert matches['program_governance']['match_basis'] == 'transfer_context'
        assert not exp['fit_signals']['engineering_mismatch']
        assert result['recommendation'] == 'WATCH'
    elif 'suena' in row['company']:
        assert 'Design and build scalable, reliable APIs' in sections['duties']
        assert '5+ years of backend engineering' in sections['required']
        assert exp['location']['workplace']['attendance_evidence'] == ['2–3 days/week onsite']
        assert exp['location']['hard_conflict']
        assert exp['location']['compatibility'] == 'incompatible'
        assert exp['location']['travel_status'] == 'unknown'
    elif 'Cofinpro' in row['company']:
        assert exp['location']['travel_status'] == 'unknown'
        assert not exp['location']['travel_details']
        assert exp['location']['workplace']['attendance_evidence'] == ['50% remote arbeiten']
        assert exp['location']['compatibility'] == 'incompatible'
        assert exp['location']['hard_conflict']
        assert 'frequent_travel_required' not in {r['constraint'] for r in result['hard_skips']}
    else:
        assert exp['location']['travel_status'] == 'unknown'
        assert all(d['qualifier'] == 'unspecified' for d in exp['location']['travel_details'])
        assert all(not d['percentages'] for d in exp['location']['travel_details'])


@pytest.mark.parametrize('heading', ['Tasks Identify', 'Job Responsibilities Own',
                                   'Your mission Lead', 'Your tasks Lead'])
def test_responsibility_headings_preserve_employer_boundary(heading):
    text = ('About us Our products cover autonomous driving and product use cases. '
            f'{heading} data adoption and rollout. Your profile Experience in analytics.')
    parts = description_sections(text)
    assert 'autonomous driving' not in parts['role']
    assert 'data adoption' in parts['duties']
    assert 'Experience in analytics' in parts['required']
    matches = match_capabilities('Analyst', text)['matched_capabilities']
    assert 'adas_autonomous_driving' not in {m['capability'] for m in matches}
    assert 'product_owner' not in {m['capability'] for m in matches}


@pytest.mark.parametrize('text', ['Steuerung eines Portfolios von Datenprojekten.',
    'Erstellung von Projektplänen und Ressourcenplanung.',
    'Leitung von Transformationsprogrammen.', 'Koordination von Rollouts.'])
def test_german_delivery_is_transferable_not_implementation(text):
    result = match_capabilities('Lead', 'Aufgaben: ' + text)
    assert result['matched_capabilities']
    assert all(m['match_basis'] == 'transfer_context' for m in result['matched_capabilities'])
    context = strategy_context('Data Lead', 'Aufgaben: ' + text)
    assert context['delivery_matches']
    assert not context['engineering_mismatch']


def test_german_delivery_in_employer_context_does_not_match():
    result = match_capabilities('Coordinator',
        'Über uns Wir bieten Steuerung eines Portfolios und Ressourcenplanung. '
        'Aufgaben: Empfang und Postbearbeitung.')
    assert not result['matched_capabilities']


@pytest.mark.parametrize('text', ['2–3 days/week onsite', '2-3 days per week onsite',
                                 'onsite 3 days/week', '3 Tage pro Woche vor Ort'])
def test_attendance_is_not_travel(text):
    result = match_location('Lead', text, structured_location={'name': 'Hamburg'})
    assert result['hard_conflict']
    assert result['compatibility'] == 'incompatible'
    assert result['travel_status'] == 'unknown'
    assert not result['travel_details']


def test_berlin_attendance_is_compatible_with_base_but_travel_stays_unknown():
    result = match_location('Lead', '2–3 days/week onsite',
                            structured_location={'name': 'Berlin'})
    assert not result.get('hard_conflict')
    assert result['travel_status'] == 'unknown'


@pytest.mark.parametrize('text', ['Optional 2 days/week onsite.',
                                 '2 days/week onsite is not required.'])
def test_optional_attendance_does_not_create_presence_gate(text):
    result = match_location('Lead', text, structured_location={'name': 'Hamburg'})
    assert not result.get('hard_conflict')


@pytest.mark.parametrize('text', [
    'Work with the team around the product owner. Willingness to travel.',
    'Work around the product owner and willingness to travel.',
    'Drive growth around 30% and willingness to travel.',
    '50% remote arbeiten. Kfz-/Reisezulage.',
    '50% remote arbeiten mit Kfz-/Reisezulage.',
])
def test_unrelated_quantities_and_words_are_not_travel_qualifiers(text):
    result = match_location('Lead', text, structured_location={'name': 'Berlin'})
    assert result['travel_status'] == 'unknown'
    assert all(d['qualifier'] == 'unspecified' for d in result['travel_details'])
    assert all(not d['percentages'] for d in result['travel_details'])


@pytest.mark.parametrize('text,qualifier,conflict', [
    ('Travel: up to 20% domestically and internationally.', 'ceiling', False),
    ('Travel: approximately 20% domestic & international.', 'approximate', True),
    ('Around 20% travel across Europe.', 'approximate', True),
    ('Internationale Reisebereitschaft (ca. 20 %) sind für dich selbstverständlich.',
     'approximate', True),
    ('20%+ travel within Germany.', 'minimum', True),
    ('Frequent travel across Europe.', 'frequent', True),
])
def test_real_travel_quantities_remain_effective(text, qualifier, conflict):
    result = match_location('Lead', text, structured_location={'name': 'Hamburg'})
    assert result['travel_details'][0]['qualifier'] == qualifier
    assert bool(result.get('hard_conflict')) == conflict
    if conflict:
        assert result['compatibility'] == 'incompatible'
