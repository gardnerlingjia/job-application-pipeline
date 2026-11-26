from datetime import UTC, datetime, timedelta
import json

from src.career_intelligence import ingest_silver
from src.career_intelligence.retrieval import (
    build_report, identity, initialize_state, observe_rows,
)
from src.career_intelligence.role_relevance import RoleRelevanceGate
from src.career_intelligence.silver_adapter import adapt_silver_row
from tests.career_intelligence.test_ingest_silver import (
    FakeRepository, fake_assessment, silver_row,
)


def recent_row(**kwargs):
    return silver_row(first_seen_at=datetime.now(UTC).isoformat(), **kwargs)


def test_gate_stops_before_assessor_and_keeps_every_provenance(tmp_path, monkeypatch):
    calls = []

    def assess(*args, **kwargs):
        calls.append(args[1])
        return fake_assessment(*args, **kwargs)

    monkeypatch.setattr(ingest_silver, 'assess_opportunity', assess)
    initialize_state(tmp_path)
    rows = [recent_row(title=title, external_job_id=str(i), canonical_key_candidate=str(i))
            for i, title in enumerate(['AI Engineer', 'Product Manager', 'Deployment Lead'])]
    summary = ingest_silver.process_silver(repository=FakeRepository(rows), results=tmp_path)
    assert calls == ['Deployment Lead']
    assert len(summary['provenance']) == 3
    assert summary['retrieval']['metrics']['new_jobs_seen'] == 3
    assert summary['retrieval']['metrics']['new_excluded_jobs'] == 1
    assert summary['retrieval']['metrics']['new_ambiguous_jobs'] == 1
    second = ingest_silver.process_silver(repository=FakeRepository(rows), results=tmp_path)
    assert second['retrieval']['metrics']['new_jobs_seen'] == 0
    assert calls == ['Deployment Lead']


def test_direct_assessment_boundary_also_gates(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Assessor must not be called')
    monkeypatch.setattr(ingest_silver, 'assess_opportunity', forbidden)
    result = ingest_silver.assess_silver_inputs(
        [adapt_silver_row(silver_row(title='Software Engineer'))], results=tmp_path,
    )
    assert result['processed'] == 0
    assert result['errors'] == []
    assert result['provenance'][0]['role_gate']['reason'] == 'EXCLUDED_ENGINEERING'


def test_new_employer_role_assessed_without_score_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_silver, 'assess_opportunity', fake_assessment)
    initialize_state(tmp_path)
    row = recent_row(title='Deployment Lead', source_name='greenhouse:waymo',
                     canonical_source_type='employer_origin_ats_backed_career_site')
    summary = ingest_silver.process_silver(repository=FakeRepository([row]), results=tmp_path)
    assert summary['processed'] == 1
    assert summary['opportunities'][0]['opportunity_score'] == 80
    assert summary['retrieval']['metrics']['employer_origin_jobs'] == 1
    assert summary['retrieval']['needs_employer_enrichment'] == []


def test_bootstrap_old_records_are_not_new_and_identity_survives_title_edits(tmp_path):
    old = silver_row(first_seen_at=(datetime.now(UTC) - timedelta(days=20)).isoformat())
    gate = RoleRelevanceGate()
    report = observe_rows([old], results=tmp_path, gate=gate)
    assert report['metrics']['new_jobs_seen'] == 0
    assert report['records'][0]['novelty_reason'] == 'BASELINE_OR_KNOWN_VACANCY'
    changed = {**old, 'title': 'Deployment Lead', 'silver_job_id': 999}
    assert identity(changed) == identity(old)
    assert observe_rows([changed], results=tmp_path, gate=gate)['metrics']['new_jobs_seen'] == 0


def test_url_identity_ignores_tracking_and_new_database_ids():
    row = silver_row(external_job_id=None, source_url='https://example.org/job/1?utm_source=a')
    changed = {**row, 'source_url': 'https://example.org/job/1?utm_source=b', 'raw_job_id': 99}
    assert identity(row) == identity(changed)


def test_origin_wins_same_run_and_company_metrics(tmp_path):
    initialize_state(tmp_path)
    sensor = recent_row(source_name='stepstone')
    origin = {**sensor, 'source_name': 'greenhouse:moia',
              'canonical_source_type': 'employer_origin_ats_backed_career_site'}
    report = observe_rows([sensor, origin], results=tmp_path, gate=RoleRelevanceGate())
    assert report['metrics']['new_jobs_seen'] == 1
    assert report['metrics']['employer_origin_jobs'] == 1
    assert len(json.loads((tmp_path / 'retrieval_state.json').read_text())['identities']) == 2
    report = build_report(report['records'], [dict(company_name='MOIA', checked=True,
                                                 source_name='greenhouse:moia')])
    assert report['metrics']['target_companies_checked'] == 1
    assert report['metrics']['target_companies_with_new_jobs'] == 1
