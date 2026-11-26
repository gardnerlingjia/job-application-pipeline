"""Synthetic controls for the role strategy and independent preview judgments."""
import copy
import json
from collections import Counter
from pathlib import Path

from src.career_intelligence.competency_qualification import (
    load_candidate_evidence, load_strategy, qualify_vacancy,
)
from src.career_intelligence.discovery_v3 import _load, build_query_plan


def context():
    config = load_strategy()
    config["candidate_evidence"].pop("approved_facts_file", None)
    config['candidate_evidence']['preview_review_enabled'] = False
    candidate = load_candidate_evidence(config)
    return config, candidate


def role(**overrides):
    return {'company_name': 'Synthetic Employer', 'title': 'Technical Program Manager',
            'locations': ['Berlin, Germany'], 'description': (
                'Responsibilities:\nLead technical programs and deliver software integration. '
                'Own roadmap milestones, dependencies and risks across cross-functional teams. '
                'Translate business requirements into technical requirements. '
                'Implement process improvement and measure tangible outcomes.\n'
                'Requirements:\nProgram management and stakeholder communication.\n'
                'Benefits:\nBerlin-based employment. No travel required.'), **overrides}


def test_role_attention_replaces_industry_quotas_without_result_quotas():
    config = _load(Path('config/career_discovery_v34.yaml'))
    strategy = load_strategy()
    assert config['role_attention_percent'] == strategy['role_attention_percent'] == {
        'A': 50, 'B': 35, 'C': 15}
    assert 'industry_attention_percent' not in config
    assert 'industry_attention_percent' not in strategy
    assert Counter(group for group, _, _ in build_query_plan(config)) == {
        'A': 20, 'B': 14, 'C': 6}
    assert strategy['working_preferences']['minimum_independent_work_orientation_percent'] == 50
    assert strategy['working_preferences']['hard_percentage_gate'] is False
    assert strategy['production_default'] is False
    assert strategy['assessment']['weights'] == 'unchanged'


def test_six_dimensions_do_not_infer_work_percentages_or_employer_health():
    config, candidate = context()
    q = qualify_vacancy(role(), config=config, candidate=candidate)
    review = q['opportunity_review']
    assert set(review['dimensions']) == {'professional_fit', 'company_outlook', 'work_content',
                                        'working_style', 'development_potential', 'life_compatibility'}
    assert review['dimensions']['company_outlook']['status'] == 'UNKNOWN'
    assert review['dimensions']['working_style']['independent_work_percent'] is None
    assert review['dimensions']['work_content']['status'] == 'IMPLEMENTATION_EVIDENCED'
    assert review['judgment'] == 'CLARIFY'
    assert 'opportunity_score' not in q


def test_meetings_do_not_veto_meaningful_delivery_but_explicit_dominance_is_visible():
    config, candidate = context()
    job = role()
    job['description'] += '\nResponsibilities:\nCoordinate stakeholders in workshops to deliver releases.'
    review = qualify_vacancy(job, config=config, candidate=candidate)['opportunity_review']
    assert review['dimensions']['working_style']['status'] != 'RISK'
    job['description'] = ('Responsibilities:\nPrimarily facilitate workshops, presentations and '
                          'reporting for stakeholder alignment. Provide meeting summaries and '
                          'maintenance-only reporting. No implementation ownership.\n'
                          'Requirements:\nStrong communication and facilitation experience.')
    review = qualify_vacancy(job, config=config, candidate=candidate)['opportunity_review']
    assert review['dimensions']['working_style']['status'] == 'RISK'
    assert review['judgment'] == 'NOT SUITABLE'


def test_cariad_exclusion_keeps_original_record_and_does_not_exclude_partners():
    config, candidate = context()
    job = role(company_name='CARIAD SE')
    original = copy.deepcopy(job)
    review = qualify_vacancy(job, config=config, candidate=candidate)['opportunity_review']
    assert review['discovery_eligible'] is False
    assert review['judgment'] == 'NOT SUITABLE'
    assert job == original
    partner = qualify_vacancy(role(company_name='Supplier to CARIAD'), config=config,
                               candidate=candidate)['opportunity_review']
    assert partner['discovery_eligible'] is True


def test_remote_and_hybrid_are_not_automatic_berlin_compatibility():
    config, candidate = context()
    review = qualify_vacancy(role(), config=config, candidate=candidate)['opportunity_review']
    # An explicit Berlin base and no travel support compatibility; hybrid alone does not.
    assert review['dimensions']['life_compatibility']['status'] == 'CONFIRMED_COMPATIBLE'
    job = role(locations=['London, United Kingdom'])
    job['description'] = job['description'].replace('Berlin-based employment', 'Hybrid role in London')
    review = qualify_vacancy(job, config=config, candidate=candidate)['opportunity_review']
    assert review['dimensions']['life_compatibility']['status'] == 'INCOMPATIBLE'
    assert review['judgment'] == 'NOT SUITABLE'


def test_expiry_and_confirmed_requirement_gap_override_attractive_role():
    config, candidate = context()
    expired = qualify_vacancy(role(review_active_status='EXPIRED'), config=config,
                              candidate=candidate)['opportunity_review']
    assert expired['judgment'] == 'NOT SUITABLE'
    gap = qualify_vacancy(role(review_confirmed_requirement_gap='Mandatory professional AI production '
                             'experience is not established by prototypes.'), config=config,
                         candidate=candidate)['opportunity_review']
    assert gap['judgment'] == 'NOT SUITABLE'


def test_company_claims_without_dated_sources_stay_unknown():
    config, candidate = context()
    job = role(employer_review={'status': 'SUPPORTED', 'evidence': [{'finding': 'Great company'}]})
    review = qualify_vacancy(job, config=config, candidate=candidate)['opportunity_review']
    assert review['dimensions']['company_outlook']['status'] == 'UNKNOWN'
    assert review['judgment'] != 'PURSUE'


def test_draft_cv_cannot_become_verified_or_unlock_assessment(tmp_path):
    config, _ = context()
    template = json.loads(Path('config/examples/private_candidate_fact_profile.template.json').read_text())
    fact = template['facts'][0]
    fact.update({'fact_key': 'synthetic.delivery', 'category': 'employment',
                 'evidence_class': 'professional_employment',
                 'statement': 'Led international software delivery programs in China and Germany.',
                 'capability_tags': ['technical_program_leadership', 'international_cross_border'],
                 'provenance': [{'source_type': 'canonical_cv', 'reference': 'Synthetic CV section',
                                 'observed_at': '2026-11-24T00:00:00Z'}]})
    template['facts'] = [fact]
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(template))
    config['candidate_evidence'].update({'preview_review_enabled': True,
                                         'preview_review_file': str(path)})
    candidate = load_candidate_evidence(config)
    assert candidate['verified_professional_facts'] == []
    assert len(candidate['review_professional_facts']) == 1
    q = qualify_vacancy(role(), config=config, candidate=candidate)
    assert any(m['evidence_status'] == 'cv_supported_pending_profile_approval'
               for m in q['competency_evidence'])
    assert q['assessment_eligible'] is False
    assert q['opportunity_review']['judgment'] != 'PURSUE'


def test_internal_employer_policy_retains_original_observations_and_legacy_defaults():
    from src.career_intelligence.discovery_v3 import discovery_candidate_summary
    rows = [{'company_name': 'CARIAD SE', 'external_job_id': 'internal'},
            {'company_name': 'External Employer', 'external_job_id': 'external'}]
    original = copy.deepcopy(rows)
    result = discovery_candidate_summary(rows, {'excluded_internal_employers': ['CARIAD']})
    assert result['active_candidate_records'] == 1
    assert result['policy_excluded_records'] == 1
    assert rows == original
    assert discovery_candidate_summary(rows, {})['active_candidate_records'] == 2
    config, candidate = context()
    q = qualify_vacancy(role(company_name='CARIAD SE'), config=config, candidate=candidate)
    assert q['opportunity_review']['discovery_eligible'] is False
    assert q['opportunity_review']['judgment'] == 'NOT SUITABLE'


def test_internal_vacancy_cannot_enter_preview_assessment():
    config, candidate = context()
    q = qualify_vacancy(role(company_name='CARIAD SE'), config=config, candidate=candidate)
    assert q['opportunity_review']['discovery_eligible'] is False
    assert q['opportunity_review']['judgment'] == 'NOT SUITABLE'
    assert q['assessment_eligible'] is False
    assert q['assessment_reason'] == 'Internal employer excluded by external-transition strategy.'


def test_mandarin_for_regional_work_does_not_establish_china_professional_requirement():
    from src.career_intelligence.competency_qualification import classify_china_europe_requirements
    config, _ = context()
    sections = {'duties': '', 'required': '', 'unstructured': '',
                'preferred': 'Mandarin or Malay to collaborate with regional stakeholders and partners.'}
    result = classify_china_europe_requirements(sections, config)
    assert result['relevance'] == 'Additional advantage'
    assert result['job_evidence'][0]['basis'] == 'language_signal'
