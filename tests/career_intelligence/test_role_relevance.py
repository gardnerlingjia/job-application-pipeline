from pathlib import Path

import pytest
import yaml

from src.career_intelligence.role_relevance import DEFAULT_CONFIG, RoleRelevanceGate


@pytest.mark.parametrize('title', [
    'Technical Program Manager', 'Senior Program Manager, Software Engineering',
    'Program Lead', 'Delivery Lead', 'Deployment Manager', 'Deployment Lead',
    'Launch Manager', 'Launch Readiness', 'Operations Lead', 'Market Operations',
    'Business Operations', 'Fleet Operations', 'Service Operations',
    'Vehicle Integration Manager', 'Release Manager', 'Release Lead',
    'Implementation Lead', 'Ecosystem Operations', 'Partner Operations',
    'Senior Product Manager – Autonomous Mobility', 'Head of Product, Automotive',
    'AI Transformation Lead', 'AI Adoption Program Manager', 'Data Product Lead',
    'Technical Program Manager, Computer Vision Engineer Enablement',
])
def test_relevant(title):
    assert RoleRelevanceGate().decide(title).reason == 'RELEVANT_ROLE'


@pytest.mark.parametrize('title', [
    'Software Engineer', 'Senior ML Engineer', 'AI Engineer', 'Data Engineer',
    'Backend Engineer', 'Frontend Engineer', 'Research Engineer',
    'Computer Vision Engineer', 'Robotics Engineer', 'Embedded Engineer',
    'Developer', 'Programmer', 'Data Scientist', 'Lead Software Engineer',
])
def test_engineering(title):
    assert RoleRelevanceGate().decide(title).reason == 'EXCLUDED_ENGINEERING'


@pytest.mark.parametrize('title,reason', [
    ('Working Student Program Manager', 'EXCLUDED_JUNIOR'),
    ('Intern, Deployment Lead', 'EXCLUDED_JUNIOR'),
    ('Werkstudent Software', 'EXCLUDED_JUNIOR'),
    ('Praktikant Operations', 'EXCLUDED_JUNIOR'),
    ('Technician', 'EXCLUDED_TECHNICIAN'), ('Test Driver', 'EXCLUDED_TECHNICIAN'),
    ('Product Manager', 'AMBIGUOUS_REVIEW'), ('AI Strategist', 'AMBIGUOUS_REVIEW'),
    ('Engineering Manager', 'AMBIGUOUS_REVIEW'), ('', 'AMBIGUOUS_REVIEW'),
    ('Unsolicited Application – Business', 'AMBIGUOUS_REVIEW'),
    ('International Partnerships', 'AMBIGUOUS_REVIEW'),
])
def test_junior_technician_ambiguous(title, reason):
    assert RoleRelevanceGate().decide(title).reason == reason


def test_configurable_without_source_specific_code(tmp_path):
    config = yaml.safe_load(DEFAULT_CONFIG.read_text())
    config['leadership'].append(r'\bportfolio captain\b')
    path = tmp_path / 'gate.yaml'
    path.write_text(yaml.safe_dump(config))
    assert RoleRelevanceGate(path).decide('Portfolio Captain').relevant
    assert not RoleRelevanceGate().decide('Portfolio Captain').relevant


def test_invalid_rules_fail_closed(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('schema_version: invalid')
    with pytest.raises(ValueError):
        RoleRelevanceGate(Path(path))
