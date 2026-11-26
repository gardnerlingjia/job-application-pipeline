"""Exercise real runtime profiles through the shared ingestion entry point."""
from unittest.mock import Mock

import pytest

from src import ingest_jobs
from src.connectors.base import SearchProfile, SearchTerm
from src.career_intelligence.discovery_profile_sync import (
    assert_profile_intent, desired_profiles, build_plan,
)
from src.career_intelligence.market_discovery import load_market_discovery_config

TARGETS = desired_profiles(load_market_discovery_config())


@pytest.mark.parametrize('name,target', TARGETS.items())
def test_all_broad_themes_reach_ingestion(monkeypatch, name, target):
    profile = SearchProfile(1, name, target['source_name'], 'Berlin', 100, 1, 50)
    repository = Mock()
    repository.load_active_search_terms.return_value = [
        (profile, SearchTerm(term, i)) for i, term in enumerate(target['terms'])]
    connector = Mock()
    runner = Mock()
    monkeypatch.setattr(ingest_jobs, 'create_connector', Mock(return_value=connector))
    monkeypatch.setattr(ingest_jobs, 'JobIngestionRunner', Mock(return_value=runner))
    assert not hasattr(profile, 'search_term')
    ingest_jobs.run_profile(repository=repository, profile=profile)
    runner.run.assert_called_once_with(profile_name=name)
    repository.load_active_search_terms.return_value = [(profile, SearchTerm('obsolete intent'))]
    with pytest.raises(ValueError, match='intent drift'):
        ingest_jobs.run_profile(repository=repository, profile=profile)
    assert runner.run.call_count == 1


@pytest.mark.parametrize('source', ['greenhouse:waymo', 'greenhouse:moia'])
def test_controlled_employer_profiles_keep_existing_contract(source):
    repository = Mock()
    assert_profile_intent(repository, SearchProfile(2, 'controlled_employer', source,
                                                  'Germany', None, None, 50))
    repository.load_active_search_terms.assert_not_called()


def test_doctor_still_blocks_legacy_database_term():
    name, target = next(iter(TARGETS.items()))
    row = dict(id=1, profile_name=name, source_name=target['source_name'],
               search_term='legacy query', terms=[dict(search_term=t, is_active=True)
                                                for t in target['terms']])
    plan = build_plan(load_market_discovery_config(), [row])
    assert any(name in reason and 'legacy search_term' in reason for reason in plan['blockers'])
