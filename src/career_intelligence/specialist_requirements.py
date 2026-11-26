"""Separate delivery leadership from explicit specialist qualification requirements."""
import re

from src.career_intelligence.capability_matcher import load_capability_profile
from src.career_intelligence.role_text import description_sections

# Requirement phrases, not technology mentions or descriptions of other teams.
RULES = {
    'platform_architecture_tenure': (
        r'(?:mindestens drei jahre|at least three years|at least 3 years).{0,100}'
        r'(?:verantwortung für datenplattformen|platform architecture responsibility)',
        'cloud_architecture', 'Professional platform/architecture tenure is not documented.'),
    'cloud_architecture': (
        r'expertise in der architektur cloudbasierter datenplattformen|'
        r'(?:required|mandatory) expertise in cloud data architecture',
        'cloud_architecture', 'Required cloud data architecture expertise is not documented.'),
    'programming': (
        r'programmierkenntnisse|(?:required|mandatory) programming skills',
        'hands_on_software_engineering',
        'Project-based coding evidence does not establish professional programming proficiency.'),
    'poc_implementation': (
        r'fähigkeit zur erstellung von pocs|(?:required|mandatory) ability to implement pocs',
        'ai_data_transformation',
        'Prototype evidence exists; required cloud-platform PoC implementation remains unverified.'),
    'financial_services_consulting': (
        r'beratungskompetenz und projektmanagement-erfahrung im finanzsektor|'
        r'(?:required|mandatory) financial.services consulting experience',
        'financial_services_consulting', 'Financial-sector consulting experience is not documented.'),
    'procurement_domain': (
        r'erfahrung im strategischen einkauf|(?:required|mandatory) strategic procurement experience',
        'procurement_domain', 'Strategic procurement/Source-to-Pay experience is not documented.'),
    'power_bi_modelling': (
        r'erfahrung mit bi- und analysetools.{0,90}power bi.{0,90}semantikmodellen|'
        r'(?:required|mandatory) power bi semantic model(?:ling|ing)',
        'power_bi_modelling', 'Power BI semantic-model implementation is not documented.'),
}

# Only evaluated in mandatory qualification sections or explicitly required clauses.
# These are specialist practices, not mentions of collaborating engineering teams.
SPECIALIST_RULES = {
    'regulatory_legal_programs': (
        r'experience (?:in )?(?:leading|managing).{0,35}regulatory[/ -]+legal programs|'
        r'(?:regulatory|legal)[/ -]*(?:legal|regulatory)? program leadership experience|'
        r'erfahrung.{0,40}leitung.{0,40}(?:regulatorisch|rechtlich)',
        'regulatory_legal_program_leadership',
        'Required regulatory/legal program leadership is not documented.'),
    'emergency_services_tenure': (
        r'\d+\+? years (?:of )?(?:service|experience) in (?:german )?emergency services|'
        r'\d+\+? jahre.{0,35}(?:rettungsdienst|feuerwehr|polizei)',
        'emergency_services', 'Required emergency-services tenure is not documented.'),
    'emergency_services_practice': (
        r'(?:deep understanding of .{0,80}emergency protocols|'
        r'proven experience in emergency response)',
        'emergency_services', 'Required emergency-response practice/domain expertise is not documented.'),
    'automotive_technician_tenure': (
        r'\d+\+? years (?:of )?experience in an? automotive technician'
        r'(?: or automotive engineering)? role',
        'automotive_diagnostics', 'Required automotive technician/engineering practice is not documented.'),
    'automotive_diagnostics': (
        r'mastery of automotive diagnostic strategies and tools|'
        r'experience servicing and diagnosing (?:electric|hybrid).{0,25}vehicles|'
        r'(?:expertise|professional experience) in automotive diagnostics',
        'automotive_diagnostics', 'Required hands-on automotive diagnostics is not documented.'),
    'licensed_specialist_practice': (
        r'(?:active|valid|current) (?:medical|nursing|legal|aviation) licen[sc]e|'
        r'\d+\+? years (?:of )?(?:clinical|surgical|legal|aircraft maintenance) practice',
        'licensed_specialist_practice', 'Required specialist licence/practice needs direct evidence.'),
}


def evaluate_specialist_requirements(description):
    sections = description_sections(description)
    text = '\n'.join(sections[key] for key in ('required', 'duties', 'unstructured'))
    capabilities = load_capability_profile()['capabilities']
    result = {}
    for name, (pattern, capability, reason) in {**RULES, **SPECIALIST_RULES}.items():
        matches = []
        scope = text
        if name in SPECIALIST_RULES:
            explicit = [clause for clause in re.split(r'[;\n]|\.\s+', sections['unstructured'])
                        if re.search(r'\brequired\b|\bmandatory\b|\bmust have\b|'
                                     r'erforderlich|voraussetzung', clause, re.I)]
            scope = sections['required'] + '\n' + '\n'.join(explicit)
        for clause in re.split(r'[;\n]|\.\s+', scope):
            # A preferred certificate in parentheses does not make the enclosing
            # required professional practice optional.
            clause = re.sub(r'\([^)]*\b(?:preferred|optional)\b[^)]*\)', '', clause, flags=re.I)
            if re.search(r'\b(?:nicht erforderlich|keine|optional|not required|nice to have|'
                         r'preferred|idealerweise|wünschenswert)\b',
                         clause, re.I):
                continue
            matches.extend(m.group(0) for m in re.finditer(pattern, clause, re.I))
        if not matches:
            continue
        candidate = capabilities.get(capability, {})
        evidence = candidate.get('evidence', [])
        supported = bool(evidence) and candidate.get('category') in {'core', 'domain'}
        if candidate.get('evidence_status') in {'unknown', 'in_development'}:
            supported = False
        if name in SPECIALIST_RULES:
            years = [int(n) for match in matches for n in re.findall(r'(\d+)\+? (?:years|jahre)', match, re.I)]
            if years and candidate.get('professional_years', 0) < max(years):
                supported = False
            # A generic licence capability cannot establish a particular professional licence.
            if name == 'licensed_specialist_practice':
                supported = supported and all(
                    match.lower() in str(evidence).lower() for match in matches)
        result[name] = {
            'requirement_matches': matches, 'candidate_capability': capability,
            'candidate_evidence': evidence, 'status': 'supported' if supported else
            'partial' if evidence else 'not_documented', 'reason': reason,
            'blocking': not supported,
        }
    return result
