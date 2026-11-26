"""Declared CV projects inform preview literacy without becoming professional facts."""
import copy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.career_intelligence.competency_qualification import (
    load_candidate_evidence, load_strategy, qualify_vacancy,
)
from src.search_intelligence.candidate_fact_profile import load_candidate_fact_profile_json


@pytest.fixture
def evidence(tmp_path):
    config = load_strategy()
    config["candidate_evidence"].pop("approved_facts_file", None)
    source = tmp_path / 'synthetic-cv.txt'
    source.write_text('Ran and tested a prototype agent with tool calls. Completed ML coursework.')
    profile = json.loads(Path('config/examples/private_candidate_fact_profile.template.json').read_text())
    fact = copy.deepcopy(profile['facts'][0])
    fact.update({'fact_key': 'synthetic.training', 'category': 'certification',
                 'evidence_class': 'training_certification',
                 'capability_tags': ['machine_learning'], 'statement': 'Completed ML coursework.',
                 'valid_until': '2020-01-01',
                 'provenance': [{'source_type': 'canonical_cv', 'reference': 'Synthetic training section',
                                 'observed_at': '2026-11-25T00:00:00Z'}]})
    profile['facts'] = [fact]
    native = tmp_path / 'native.json'
    native.write_text(json.dumps(profile))
    review = {'schema_version': 'career_intelligence.cv_reconciliation_review.v1',
              'source': {'path': str(source), 'sha256': sha256(source.read_bytes()).hexdigest()},
              'facts': [{'fact_key': 'synthetic.agent', 'evidence_class': 'candidate_declared_portfolio',
                         'competencies': ['agent_tool_calling', 'ai_workflow_design'],
                         'paragraphs': ['P001'], 'source_text': ['Ran and tested a prototype agent with tool calls.'],
                         'maturity': 'prototype', 'limits': ['No professional production deployment.'],
                         'additional_verification_needed': 'Agent code and tool execution trace.'}]}
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(review))
    config['candidate_evidence'].update({'preview_review_enabled': True,
        'preview_review_file': str(native), 'supplementary_review_file': str(path)})
    return config, native, source


def row():
    return {'title': 'AI Workflow Designer', 'company_name': 'Synthetic Employer',
            'locations': ['Berlin, Germany'], 'description': (
                'Responsibilities:\nLead delivery programs, software integration and process transformation. '
                'Coordinate cross-functional stakeholders and manage milestones, risks and dependencies. '
                'Own the roadmap and translate business requirements into technical requirements.\n'
                'Preferred qualifications:\nPrototype agent tool calling and machine learning model evaluation.\n'
                'Benefits:\nBerlin-based employment. No travel required.')}


def test_declared_projects_and_training_are_loaded_without_repository_fabrication(evidence):
    config, _, _ = evidence
    candidate = load_candidate_evidence(config)
    assert len(candidate['supplementary_evidence']) == 2
    assert candidate['verified_professional_facts'] == []
    project = candidate['supplementary_evidence'][0]
    assert project['repository_verification'] == 'not_verified'
    assert project['evidence_class'] == 'candidate_declared_portfolio'
    assert project['provenance'][0]['source_type'] == 'canonical_cv'
    assert candidate['supplementary_evidence'][1]['credential_status'] == 'expired'


def test_distinct_capability_matches_keep_maturity_and_provenance(evidence):
    config, _, _ = evidence
    q = qualify_vacancy(row(), config=config, candidate=load_candidate_evidence(config))
    matches = {m['competency']: m for m in q['supplementary_competency_evidence']}
    assert {'agent_tool_calling', 'machine_learning'} <= matches.keys()
    assert matches['agent_tool_calling']['candidate_evidence'][0]['maturity'] == 'prototype'
    assert matches['machine_learning']['candidate_evidence'][0]['evidence_class'] == 'training_certification'
    assert not any(m['professional_requirement_established'] for m in matches.values())
    assert q['assessment_eligible'] is False


def test_supplementary_matches_cannot_erase_production_requirements_or_inflate_core_counts(evidence):
    config, _, _ = evidence
    candidate = load_candidate_evidence(config)
    job = row()
    job['description'] += '\nRequirements:\nFive years of production AI engineering and machine learning required.'
    stripped = copy.deepcopy(candidate)
    stripped['supplementary_evidence'] = []
    before = qualify_vacancy(job, config=config, candidate=stripped)
    after = qualify_vacancy(job, config=config, candidate=candidate)
    assert after['supplementary_competency_evidence']
    assert after['specialist_gaps'] == before['specialist_gaps']
    assert any(g['requirement'] == 'production_ai' for g in after['specialist_gaps'])
    assert after['competency_evidence'] == before['competency_evidence']
    assert after['status'] == before['status']
    assert not after['assessment_eligible']


def test_native_repository_gate_is_not_relaxed(evidence):
    _, native, _ = evidence
    payload = json.loads(native.read_text())
    payload['facts'][0].update({'evidence_class': 'portfolio_implementation', 'category': 'project'})
    with pytest.raises(ValueError, match='repository provenance'):
        load_candidate_fact_profile_json(json.dumps(payload))


def test_title_only_and_negated_requirements_do_not_match(evidence):
    config, _, _ = evidence
    candidate = load_candidate_evidence(config)
    for description in ['', 'Requirements:\nNo agent tool calling or machine learning required.']:
        q = qualify_vacancy({**row(), 'description': description}, config=config, candidate=candidate)
        assert not q['supplementary_competency_evidence']


def test_disabled_review_and_changed_cv_fail_closed(evidence):
    config, _, source = evidence
    disabled = copy.deepcopy(config)
    disabled['candidate_evidence']['preview_review_enabled'] = False
    assert not load_candidate_evidence(disabled)['supplementary_evidence']
    source.write_text('Changed source evidence.')
    with pytest.raises(ValueError, match='hash mismatch'):
        load_candidate_evidence(config)


@pytest.mark.parametrize('same_source', [True, False])
def test_declared_evidence_survives_later_approval_only_for_same_cv(evidence, tmp_path, same_source):
    config, native, _ = evidence
    source = tmp_path / 'synthetic-cv.txt'
    source.write_text('Synthetic candidate-declared project description.')
    sidecar = tmp_path / 'declared.json'
    sidecar.write_text(json.dumps({
        'schema_version': 'career_intelligence.cv_reconciliation_review.v1',
        'source': {'path': str(source), 'sha256': sha256(source.read_bytes()).hexdigest()},
        'facts': [{'fact_key': 'synthetic.agent', 'evidence_class': 'candidate_declared_portfolio',
                   'competencies': ['agent_tool_calling'], 'source_text': ['Ran a tool-using prototype.'],
                   'paragraphs': ['P001'], 'maturity': 'prototype',
                   'limits': ['Not professional production experience.'],
                   'additional_verification_needed': 'Source/configuration and tool-call trace.'}]}))
    config['candidate_evidence']['supplementary_review_file'] = str(sidecar)
    payload = json.loads(native.read_text())
    payload.update(status='approved', approved_by='Synthetic reviewer',
                   approved_at='2026-11-25T00:00:00Z')
    fact = payload['facts'][0]
    fact.update(approval_status='approved', approved_by='Synthetic reviewer',
                approved_at='2026-11-25T00:00:00Z')
    fact['provenance'][0]['reference'] = source.name if same_source else 'Different CV'
    native.write_text(json.dumps(payload))
    candidate = load_candidate_evidence(config, native)
    projects = [f for f in candidate['supplementary_evidence']
                if f['evidence_class'] == 'candidate_declared_portfolio']
    assert len(projects) == int(same_source)
    assert not candidate['verified_professional_facts']
