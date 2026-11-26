import json
from pathlib import Path

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.specialist_requirements import evaluate_specialist_requirements

FIXTURES = json.loads(Path('tests/fixtures/career_intelligence/leadership_requirements_v1.json').read_text())


@pytest.mark.parametrize('job', FIXTURES, ids=lambda job: job['company'])
def test_delivery_recognized_without_converting_it_to_specialist_evidence(job):
    result = assess_opportunity(job['company'], job['title'], job['description'])
    exp = result['explanation']
    assert exp['fit'] == 'bridge'
    assert exp['fit_signals']['delivery_matches']
    assert not exp['fit_signals']['engineering_mismatch']
    req = exp['role_requirements']['specialist_requirements']
    if job['company'].startswith('IRS'):
        assert req['platform_architecture_tenure']['status'] == 'not_documented'
        assert req['platform_architecture_tenure']['blocking']
    elif job['company'].startswith('EY'):
        assert {'cloud_architecture', 'programming', 'poc_implementation',
                'financial_services_consulting'} <= req.keys()
        assert req['programming']['status'] == 'partial'
        assert req['poc_implementation']['status'] == 'partial'
        assert exp['location']['berlin_preference'] == 1
    else:
        assert {'procurement_domain', 'power_bi_modelling'} <= req.keys()
        assert exp['location']['hard_conflict']
        assert exp['location']['category'] == 'non_berlin_partial_mobile_work'
    assert result['recommendation'] in {'WATCH', 'SKIP'}
    assert exp['candidate_strength']['blocking_gaps']
    assert exp['location']['travel_status'] == 'unknown'


@pytest.mark.parametrize('title', ['Senior AI Engineer', 'Staff Software Engineer',
                                   'Principal Software Engineer'])
def test_leadership_words_do_not_override_hands_on_exclusion(title):
    result = assess_opportunity('Generic', title,
        'Berlin. Roadmap ownership and operational handover. Build production AI services in Python. '
        'No travel required.')
    assert result['recommendation'] == 'SKIP'
    assert result['explanation']['fit_signals']['engineering_mismatch']


def test_optional_specialist_exposure_does_not_create_mandatory_gap():
    assert not evaluate_specialist_requirements(
        'Programmierkenntnisse nicht erforderlich. Optional strategic procurement experience.')


@pytest.mark.parametrize('base,percent,conflict', [
    ('Norderstedt bei Hamburg', 50, True), ('Berlin, Hamburg', 50, False),
    ('Potsdam', 50, False), ('Norderstedt', 100, False)])
def test_partial_mobile_work_is_not_fully_remote(base, percent, conflict):
    result = match_location('Transformation Lead',
                           f'Job in {base} Jobs finden. Bis zu {percent} % mobil arbeiten.')
    assert bool(result.get('hard_conflict')) == conflict


def test_company_name_cannot_change_specialist_evidence():
    job = FIXTURES[0]
    first = assess_opportunity('Unknown employer A', job['title'], job['description'])
    second = assess_opportunity('Unknown employer B', job['title'], job['description'])
    assert first['explanation']['role_requirements'] == second['explanation']['role_requirements']


def test_generic_dependencies_alone_do_not_establish_transformation_bridge():
    from src.career_intelligence.classifier import strategy_context
    context = strategy_context('Product Owner', 'Data platform. Technische Abhängigkeiten managen.')
    assert context['transition'] != 'bridge'
