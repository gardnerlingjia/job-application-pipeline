"""Approval retains declared scope and makes existing CV context available to matching."""
import json

from src.career_intelligence.competency_qualification import (
    load_candidate_context, load_strategy, match_candidate_context,
)


def test_approved_context_exposes_languages_knowledge_and_old_employment(tmp_path):
    config = load_strategy()
    path = tmp_path / 'review.json'
    path.write_text(json.dumps({
        'approval': {'approved_by': 'Synthetic candidate', 'approved_at': '2026-11-25T00:00:00Z'},
        'languages': {'source': 'Synthetic CV Languages',
                      'text': 'Mandarin Chinese — Native | German — Near-native | English — Fluent'},
        'technology_working_knowledge': {'source': 'Synthetic CV Knowledge',
                                         'text': 'Working knowledge: Python, PyTorch'},
        'facts': [{'fact_key': 'synthetic.old.china', 'evidence_class': 'professional_employment',
                   'employer_or_context': 'Synthetic Employer', 'role_or_activity': 'Regional Manager',
                   'period': '05/2010–04/2012', 'paragraphs': ['P001']},
                  {'fact_key': 'synthetic.old.market', 'evidence_class': 'professional_employment',
                   'employer_or_context': 'Synthetic Employer', 'role_or_activity': 'Regional Manager',
                   'period': '05/2010–04/2012', 'paragraphs': ['P002']}]}))
    config['candidate_evidence'].update(preview_review_enabled=True,
                                         supplementary_review_file=str(path))
    context = load_candidate_context(config)
    assert len(context['employment_history']) == 1
    employment = context['employment_history'][0]
    assert employment['documented_month_interval'] == 23
    assert employment['older_competence_expired'] is False
    assert set(employment['cv_fact_keys']) == {'synthetic.old.china', 'synthetic.old.market'}
    result = match_candidate_context({'role': 'German, English and Python required.'}, context)
    assert {r['language'] for r in result['languages']} == {'German', 'English'}
    assert result['languages'][0]['cefr_or_professional_achievement_inferred'] is False
    assert result['technology_working_knowledge'] == ['Python']
    assert 'professional tenure not established' in result['technology_scope']
    assert 'not a measure of specialist tenure' in employment['date_precision']


def test_disabled_context_does_not_load_private_review(tmp_path):
    config = load_strategy()
    config['candidate_evidence']['preview_review_enabled'] = False
    config['candidate_evidence']['supplementary_review_file'] = str(tmp_path / 'missing.json')
    context = load_candidate_context(config)
    assert context['employment_history'] == []
    assert context['languages'] == {}
