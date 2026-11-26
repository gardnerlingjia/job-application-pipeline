"""Public CI never fabricates the private candidate inputs used by deployment tests."""
from pathlib import Path

import pytest


_PRIVATE = ('career_profile.yaml', 'capability_profile.yaml', 'constraints.yaml',
            'network_profile.yaml')
_INDEPENDENT = {
    'test_discovery_v3.py', 'test_role_relevance.py', 'test_market_intelligence.py',
    'test_v34_preview_api.py', 'test_v34_approved_context.py', 'test_v34_corrections.py',
}


def pytest_collection_modifyitems(items):
    if all((Path('config') / name).is_file() for name in _PRIVATE):
        return
    marker = pytest.mark.skip(reason='Requires separately retained private candidate configuration')
    for item in items:
        path = Path(str(item.fspath))
        dependent = (path.parent.name == 'career_intelligence' and path.name not in _INDEPENDENT)
        if (dependent or path.name == 'test_waymo_controlled_preparation.py'
                or item.name == 'test_acceptance_report_does_not_confuse_discovery_and_candidate_evidence'):
            item.add_marker(marker)
