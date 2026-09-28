"""Role evidence, specialist practice and practical constraints are independent."""
import hashlib
import json
from pathlib import Path

import pytest

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.capability_matcher import match_capabilities
from src.career_intelligence.classifier import classify_job, strategy_context
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.role_text import description_sections
from src.career_intelligence.specialist_requirements import evaluate_specialist_requirements


INTRO = ('Example is an autonomous driving technology company. Our products include '
         'vehicle platforms and product use cases. Our cross-functional team leads delivery.')
FIXTURE = Path('tests/fixtures/career_intelligence/waymo_evidence_interpretation_v1.json')
WAYMO = json.loads(FIXTURE.read_text())


@pytest.mark.parametrize('description', [INTRO, INTRO + ' You will: Maintain office supplies.',
    'Example is a technology company. The platform provides autonomous driving and product use cases.',
    '<h2>About us</h2><p>' + INTRO + '</p><h2>Responsibilities</h2><p>Maintain office supplies.</p>'])
def test_employer_context_cannot_establish_candidate_or_delivery_evidence(description):
    result = match_capabilities('Office Coordinator', description)
    assert result['matched_capabilities'] == []
    context = strategy_context('Office Coordinator', description)
    assert context['autonomy_matches']
    assert not context['delivery_matches']
    assert classify_job('Office Coordinator', description)['career_lane'] == 'autonomy_robotics'


@pytest.mark.parametrize('heading', ['You will:', 'Responsibilities:', '<h2>Responsibilities</h2>',
                                    'Deine Aufgaben:'])
def test_real_role_responsibilities_remain_direct(heading):
    result = match_capabilities('Delivery Lead', INTRO + ' ' + heading +
        ' Lead vehicle software delivery programs. Own the product backlog and user stories.')
    matches = {m['capability']: m for m in result['matched_capabilities']}
    assert matches['technical_program_leadership']['match_basis'] == 'direct_terms'
    assert matches['automotive_mobility']['match_basis'] == 'direct_terms'
    assert matches['product_owner']['match_basis'] == 'direct_terms'


def test_core_responsibilities_in_sentence_is_not_a_section_heading():
    text = 'Automotive program delivery and risk management are the core responsibilities.'
    assert 'Automotive' in description_sections(text)['role']


def test_german_international_duties_are_recognized_but_company_scope_is_not():
    duties = match_capabilities('Lead',
        'Aufgaben: Sie steuern internationale Daten- und IT-Vorhaben.')
    assert 'international_cross_border' in {m['capability'] for m in duties['matched_capabilities']}
    intro = match_capabilities('Lead',
        'Über uns: Eine internationale Unternehmensgruppe. Aufgaben: Lokale Büroorganisation.')
    assert not intro['matched_capabilities']


@pytest.mark.parametrize('text', ['Berlin/hybrid.', 'Berlin-based. No travel required.'])
def test_explicit_berlin_workplace_notation_is_preserved(text):
    assert match_location('Lead', text)['berlin_preference'] == 1


@pytest.mark.parametrize('requirement,key', [
    ('Experience leading large Regulatory/Legal programs', 'regulatory_legal_programs'),
    ('15+ years of service in German emergency services', 'emergency_services_tenure'),
    ('Proven experience in emergency response', 'emergency_services_practice'),
    ('5+ years experience in an automotive technician or automotive engineering role',
     'automotive_technician_tenure'),
    ('Mastery of automotive diagnostic strategies and tools', 'automotive_diagnostics'),
    ('Experience servicing and diagnosing electric or hybrid vehicles '
     '(high voltage qualification preferred)', 'automotive_diagnostics'),
    ('Valid medical licence', 'licensed_specialist_practice'),
])
def test_mandatory_specialist_practice_is_not_transferable_leadership(requirement, key):
    result = evaluate_specialist_requirements('You have: ' + requirement)
    assert result[key]['blocking']
    assert result[key]['status'] == 'not_documented'
    assert result[key]['requirement_matches']


@pytest.mark.parametrize('heading', ['We prefer:', 'Preferred qualifications:', 'Nice to have:'])
def test_preferred_tenure_never_becomes_mandatory(heading):
    text = 'You have: Program delivery experience. ' + heading + \
           ' 15+ years of service in German emergency services.'
    assert not evaluate_specialist_requirements(text)


@pytest.mark.parametrize('description', [
    'Experience leading large Regulatory/Legal programs is not required.',
    'Optional mastery of automotive diagnostic strategies and tools.',
    'You will: Coordinate emergency services and automotive engineering teams.',
    'You have: Experience coordinating software engineering teams.',
    'Our company employs experts with 15+ years of service in German emergency services.',
])
def test_mentions_optional_exposure_and_other_teams_are_not_specialist_gaps(description):
    assert not evaluate_specialist_requirements(description)


def test_explicit_required_specialism_without_heading():
    assert evaluate_specialist_requirements(
        'Required: Experience leading large Regulatory/Legal programs.')


def test_preferred_core_engineering_and_tenure_are_not_mandatory_gaps():
    result = assess_opportunity('Example', 'Technical Program Manager',
        'You will: Lead vehicle programs. We prefer: Several years of robotics experience '
        'and hands-on robotics engineering.')
    assert not result['explanation']['role_requirements']['blocking_gaps']


def test_documented_specialist_tenure_is_accepted_but_short_tenure_is_not(monkeypatch):
    candidate = {'category': 'domain', 'evidence': ['Documented emergency response career'],
                 'professional_years': 16}
    monkeypatch.setattr('src.career_intelligence.specialist_requirements.load_capability_profile',
                        lambda: {'capabilities': {'emergency_services': candidate}})
    text = 'You have: 15+ years of service in German emergency services'
    assert not evaluate_specialist_requirements(text)['emergency_services_tenure']['blocking']
    candidate['professional_years'] = 4
    assert evaluate_specialist_requirements(text)['emergency_services_tenure']['blocking']
    candidate['professional_years'] = 20
    candidate['evidence_status'] = 'in_development'
    assert evaluate_specialist_requirements(text)['emergency_services_tenure']['blocking']


@pytest.mark.parametrize('location,description,base,mode,berlin,conflict', [
    ('Munich, Germany', 'This role follows a hybrid work schedule. Liaise with Polizei Berlin.',
     'munich', 'hybrid', 0, True),
    ('Munich, Germany', 'In this in person role, diagnose hybrid vehicles.',
     'munich', 'in_person', 0, True),
    ('Berlin, Germany', 'Work with Munich emergency services.', 'berlin', 'unknown', 1, False),
    ('Germany-wide', 'Occasional domestic travel.', 'germany_wide', 'unknown', 0, False),
    ('Remote Germany', 'No travel required.', 'remote_germany', 'remote', 0, False),
    ('Germany', 'Travel details to be confirmed.', 'germany', 'unknown', 0, False),
    ('Munich, Germany', 'Workplace attendance to be confirmed.', 'munich', 'unknown', 0, False),
])
def test_structured_workplace_is_authoritative(location, description, base, mode, berlin, conflict):
    result = match_location('Lead', description,
                            structured_location={'name': location, 'source': 'fixture'})
    assert result['workplace']['base'] == base
    assert result['workplace']['work_mode'] == mode
    assert result['berlin_preference'] == berlin
    assert bool(result.get('hard_conflict')) == conflict
    assert not result['relocation_evidence']


@pytest.mark.parametrize('description', [
    'Build relationships with Polizei Berlin and the Berliner Feuerwehr.',
    'Our headquarters is in Berlin. Work with Berlin stakeholders.',
    'Collaborate with engineering teams in Berlin.',
    'Collaborate with engineering teams based in Berlin.',
    'Our headquarters is based in Berlin.',
    'Based in Munich and report to our Berlin stakeholder. Hybrid work schedule.',
])
def test_incidental_city_never_establishes_berlin_preference(description):
    assert match_location('Lead', description)['berlin_preference'] == 0


def test_no_travel_does_not_establish_remote_work_from_a_non_berlin_base():
    result = match_location('Lead', 'No travel required.',
                            structured_location={'name': 'Munich, Germany'})
    assert result['compatibility'] == 'unknown'
    assert result['travel_status'] == 'none_required'
    assert not result.get('hard_conflict')


def test_batch_input_location_is_saved_for_future_reassessment(tmp_path):
    from src.career_intelligence.batch import process_batch

    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    location = {'name': 'Munich, Germany', 'source': 'captured.fixture'}
    (inbox / 'role.json').write_text(json.dumps({
        'company': 'Example', 'title': 'Technical Program Manager',
        'description': 'Lead vehicle programs. This is a hybrid role. No travel required.',
        'structured_location': location,
    }))
    result = process_batch(inbox, tmp_path / 'processed', tmp_path / 'results')['opportunities'][0]
    assert result['explanation']['input_evidence']['structured_location'] == location
    assert result['explanation']['location']['hard_conflict']


@pytest.mark.parametrize('text,qualifier,frequent,scope', [
    ('up to 20% travel within Germany', 'ceiling', False, 'domestic'),
    ('approximately 20% travel across Europe', 'approximate', True, 'european'),
    ('20%+ travel internationally', 'minimum', True, 'international'),
    ('frequent travel across Europe', 'frequent', True, 'european'),
    ('travel up to 10 days per month', 'ceiling', False, 'unknown'),
    ('Travel Requirements: Up to 20% Some travel to the US and UK and EU',
     'ceiling', False, 'international'),
    ('frequent travel up to 20%', 'frequent', True, 'unknown'),
])
def test_travel_qualifiers_are_preserved(text, qualifier, frequent, scope):
    result = match_location('Lead', 'Berlin. ' + text)
    detail = result['travel_details'][0]
    assert detail['qualifier'] == qualifier
    assert detail['established_frequent'] == frequent
    assert detail['scope'] == scope
    assert (result['compatibility'] == 'incompatible') == frequent
    if not frequent:
        assert result['travel_status'] == 'unknown'
        assert result['compatibility'] == 'unknown'


def test_travel_percentage_unrelated_to_travel_is_not_promoted():
    result = match_location('Lead', 'Berlin. Improve uptime by 30%. Travel: occasionally.')
    assert result['travel_status'] == 'unknown'
    assert result['travel_details'][0]['percentages'] == []


@pytest.mark.parametrize('row', WAYMO, ids=lambda r: r['title'])
def test_captured_waymo_roles_without_fixed_scores(row):
    assert hashlib.sha256(row['description'].encode()).hexdigest() == row['description_sha256']
    result = assess_opportunity(row['company'], row['title'], row['description'],
                                structured_location=row['structured_location'])
    exp = result['explanation']
    assert exp['location']['workplace']['base'] == 'munich'
    assert exp['location']['hard_conflict']
    assert not exp['location']['berlin_preference']
    assert not exp['location']['relocation_evidence']
    assert exp['candidate_strength']['blocking_gaps']
    assert not exp['fit_signals']['engineering_mismatch']  # working with engineers is not exclusion
    requirements = exp['role_requirements']['specialist_requirements']
    if row['external_job_id'] == '8063637':
        assert requirements['regulatory_legal_programs']['blocking']
        assert 'technical_program_leadership' in exp['candidate_strength']['anchors']['direct_role_evidence']
        assert exp['location']['workplace']['work_mode'] == 'hybrid'
    elif row['external_job_id'] == '8109449':
        assert requirements['emergency_services_tenure']['blocking']
        assert exp['location']['travel_details'][0]['qualifier'] == 'approximate'
        assert exp['location']['travel_details'][0]['scopes'] == ['domestic', 'international']
    else:
        assert requirements['automotive_technician_tenure']['blocking']
        assert requirements['automotive_diagnostics']['blocking']
        assert exp['location']['workplace']['work_mode'] == 'in_person'
        assert exp['location']['travel_details'][0]['qualifier'] == 'ceiling'
        assert exp['location']['travel_status'] == 'unknown'
        assert not exp['candidate_strength']['anchors']['direct_role_evidence']


@pytest.mark.parametrize('title', ['Staff Software Engineer', 'Senior AI Engineer',
                                  'Robotics Engineer'])
def test_genuine_engineering_exclusions_survive_role_sections(title):
    result = assess_opportunity('Example', title,
                                INTRO + ' You will: Build production perception software.')
    assert result['explanation']['fit_signals']['engineering_mismatch']
    assert result['recommendation'] == 'SKIP'
