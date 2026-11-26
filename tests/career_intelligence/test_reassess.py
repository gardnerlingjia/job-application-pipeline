"""No live database/provider calls: exact selection and real atomic-directory publication."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from src.career_intelligence import reassess
from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.batch import _result_record
from src.career_intelligence.daily import DailyRunAlreadyActive, DailyRunLock
from src.career_intelligence.ingest_silver import PROVENANCE_FILE
from src.career_intelligence.reassessment_evidence import recover_evidence
from src.career_intelligence.reassessment_publication import tree_digest, file_digest
from src.career_intelligence.silver_adapter import adapt_silver_row, SilverJobReadRepository


class Repository:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def load_silver_jobs(self, *, silver_job_ids):
        self.calls.append(silver_job_ids)
        return deepcopy([r for r in self.rows if r['silver_job_id'] in silver_job_ids])


@pytest.fixture
def corpus(tmp_path):
    results = tmp_path / 'results'
    results.mkdir()
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    rows, old, provenance = [], [], []
    for sid in (9, 45001):
        row = dict(silver_job_id=sid, raw_job_id=sid + 100,
                   source_name='personio:example', external_job_id=str(sid),
                   source_url=f'https://example.test/{sid}', company_name=f'Example {sid}',
                   title='Vehicle Software Delivery Lead', city='Berlin',
                   canonical_source_type='employer_origin', canonical_key_candidate=f'key-{sid}',
                   raw_data={'job': {'description': 'Berlin. Vehicle software delivery. No travel required.'}})
        item = adapt_silver_row(row)
        assessment = assess_opportunity(item.company, item.title, item.description)
        assessment['explanation']['input_evidence'] = {
            'schema_version': 1, 'role_evidence': {}, 'market_evidence': {}}
        record = _result_record(assessment, item.source_file)
        record['opportunity_score'] = 12  # a deliberately old assessment
        record['recommendation'] = 'WATCH'
        record['explanation']['semantics_version'] = 3
        prov = item.provenance
        prov['ingestion_status'] = 'assessed'
        rows.append(row)
        old.append(record)
        provenance.append(prov)
    (results / 'opportunities.json').write_text(json.dumps(old))
    (results / PROVENANCE_FILE).write_text(json.dumps(provenance))
    (results / 'opportunity_radar.md').write_text('old radar\n')
    (results / 'extra.txt').write_text('preserve this too')
    return dict(results=results, runtime=runtime, state_path=runtime / 'operator_state.json',
                processed=tmp_path / 'processed', output=tmp_path / 'preview',
                repository=Repository(rows))


def write_state(corpus, source):
    corpus['state_path'].write_text(json.dumps({'schema_version': 1, 'states': {
        source: {'state': 'DISMISSED', 'updated_at_utc': '2026-09-22T00:00:00Z'}}}))


def plan_path(corpus):
    return corpus['output'] / 'plan.json'


def test_exact_selection_preview_is_non_mutating_and_unselected_unchanged(corpus):
    before = tree_digest(corpus['results'])
    saved = json.loads((corpus['results'] / 'opportunities.json').read_text())
    selected = saved[1]['source_file']
    plan = reassess.preview(**corpus, selected=[selected])
    assert corpus['repository'].calls == [[45001]]
    assert plan['selected'] == plan['reassessed'] == 1
    assert plan['unselected'] == 1 and plan['safe_to_publish']
    assert plan['candidates'][0] == saved[0]
    assert plan['candidates'][1]['source_file'] == selected
    assert tree_digest(corpus['results']) == before
    assert not corpus['state_path'].exists()
    assert (corpus['output'] / 'candidate' / PROVENANCE_FILE).read_bytes() == (
        corpus['results'] / PROVENANCE_FILE).read_bytes()


def test_apply_archives_everything_preserves_decisions_and_rollback(corpus):
    saved = json.loads((corpus['results'] / 'opportunities.json').read_text())
    write_state(corpus, saved[0]['source_file'])
    state_hash = file_digest(corpus['state_path'])
    before = tree_digest(corpus['results'])
    plan = reassess.preview(**corpus)
    result = reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])
    archive = Path(result['archive'])
    assert tree_digest(archive / 'results') == before
    assert file_digest(archive / 'operator_state.json') == state_hash
    assert file_digest(corpus['state_path']) == state_hash
    assert tree_digest(corpus['results']) == plan['candidate_tree']
    assert 'DISMISSED' in (corpus['results'] / 'opportunity_radar.md').read_text()
    reassess.rollback(archive, result['rollback_confirmation'])
    assert tree_digest(corpus['results']) == before
    assert file_digest(corpus['state_path']) == state_hash


def test_full_optional_evidence_is_preserved(corpus):
    path = corpus['results'] / 'opportunities.json'
    records = json.loads(path.read_text())
    snapshot = {'schema_version': 1, 'role_evidence': {
        'network': {'relationship_level': 'employee_referral', 'status': 'confirmed',
                    'evidence_source': 'documented referral'},
        'requirements': {'technical_core': {'value': True, 'status': 'confirmed',
                                            'evidence_source': 'hiring manager'}}},
        'market_evidence': {'funding_or_budget_signal': {
            'value': 'budget freeze', 'status': 'confirmed', 'evidence_source': 'company notice'}},
    }
    records[0]['explanation']['input_evidence'] = snapshot
    path.write_text(json.dumps(records))
    plan = reassess.preview(**corpus)
    new = plan['candidates'][0]
    assert new['explanation']['input_evidence'] == {
        **snapshot, 'structured_location': {'name': 'Berlin', 'source': 'silver.city'}}
    assert new['explanation']['access'] == 'referral-based'
    assert new['recommendation'] == 'WATCH'
    assert 'core_technical_gap' in new['explanation']['candidate_strength']['blocking_gaps']


def test_reassessment_preserves_saved_location_instead_of_replacing_it(corpus):
    path = corpus['results'] / 'opportunities.json'
    records = json.loads(path.read_text())
    location = {'name': 'Munich, Germany', 'source': 'original.job.location'}
    records[0]['explanation']['input_evidence']['structured_location'] = location
    path.write_text(json.dumps(records))
    corpus['repository'].rows[0]['raw_data']['job']['description'] = (
        'Vehicle software delivery. This role follows a hybrid work schedule. '
        'Work with Berlin stakeholders. No travel required.')
    before = tree_digest(corpus['results'])
    plan = reassess.preview(**corpus)
    result = plan['candidates'][0]
    assert result['explanation']['input_evidence']['structured_location'] == location
    assert result['explanation']['location']['workplace']['base'] == 'munich'
    assert result['explanation']['location']['hard_conflict']
    assert result['explanation']['location']['berlin_preference'] == 0
    assert tree_digest(corpus['results']) == before


def test_invalid_saved_location_blocks_reassessment(corpus):
    path = corpus['results'] / 'opportunities.json'
    records = json.loads(path.read_text())
    records[0]['explanation']['input_evidence']['structured_location'] = 'Berlin'
    path.write_text(json.dumps(records))
    plan = reassess.preview(**corpus)
    assert plan['blocked'] == 1
    assert plan['candidates'][0] == records[0]


@pytest.mark.parametrize('mutation,reason', [
    ('no_provenance', 'incomplete_provenance'),
    ('no_raw_id', 'missing fields: raw_job_id'),
    ('wrong_identity', 'identity_mismatch: stable_identity_sha256'),
    ('changed_title', 'identity_mismatch: company/title'),
    ('missing_silver', 'missing_silver_identity'),
    ('ambiguous', 'ambiguous_silver_identity'),
    ('missing_evidence', 'missing_evidence_snapshot'),
    ('warm_unrecoverable', 'network_evidence_not_recoverable'),
    ('market_unrecoverable', 'market_evidence_not_recoverable'),
])
def test_unsafe_records_block_without_replacement(corpus, mutation, reason):
    path = corpus['results'] / 'opportunities.json'
    records = json.loads(path.read_text())
    prov_path = corpus['results'] / PROVENANCE_FILE
    prov = json.loads(prov_path.read_text())
    if mutation == 'no_provenance':
        prov.pop(0)
    elif mutation == 'no_raw_id':
        prov[0].pop('raw_job_id')
    elif mutation == 'wrong_identity':
        prov[0]['stable_identity_sha256'] = 'changed'
    elif mutation == 'changed_title':
        corpus['repository'].rows[0]['title'] = 'Different Job'
    elif mutation == 'missing_silver':
        corpus['repository'].rows.pop(0)
    elif mutation == 'ambiguous':
        corpus['repository'].rows.append(deepcopy(corpus['repository'].rows[0]))
    else:
        records[0]['explanation'].pop('input_evidence')
        if mutation == 'missing_evidence':
            records[0].pop('explanation')
        elif mutation == 'warm_unrecoverable':
            records[0]['explanation']['access'] = 'warm'
        else:
            records[0]['explanation']['missing_market_evidence'].remove('hiring_intent_strength')
    path.write_text(json.dumps(records))
    prov_path.write_text(json.dumps(prov))
    before = tree_digest(corpus['results'])
    plan = reassess.preview(**corpus)
    assert plan['blocked'] + plan['missing'] == 1
    assert plan['candidates'][0] == records[0]
    assert any(reason in r for r in plan['records'][0]['reasons'])
    assert not plan['safe_to_publish']
    with pytest.raises(ValueError, match='Blocked'):
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])
    assert tree_digest(corpus['results']) == before


def test_reconstructed_v3_retains_confirmed_requirements(corpus):
    record = json.loads((corpus['results'] / 'opportunities.json').read_text())[0]
    record['explanation'].pop('input_evidence')
    record['explanation']['role_requirements']['facts']['commercial_core'] = {
        'value': True, 'status': 'confirmed', 'evidence_source': 'real commercial feedback'}
    snapshot, origin = recover_evidence(record, corpus['processed'])
    assert origin.startswith('reconstructed')
    assert snapshot['role_evidence']['requirements']['commercial_core']['value'] is True


@pytest.mark.parametrize('changed', ['production', 'state', 'calibration', 'silver', 'preview'])
def test_apply_rejects_stale_review(corpus, monkeypatch, changed):
    plan = reassess.preview(**corpus)
    if changed == 'production':
        (corpus['results'] / 'extra.txt').write_text('daily changed this')
    elif changed == 'state':
        write_state(corpus, plan['candidates'][0]['source_file'])
    elif changed == 'calibration':
        monkeypatch.setattr(reassess, 'calibration_snapshot', lambda: {'changed': True})
    elif changed == 'silver':
        corpus['repository'].rows[0]['raw_data']['job']['description'] += ' Updated requirement.'
    else:
        (corpus['output'] / 'candidate/opportunity_radar.md').write_text('tampered')
    before = tree_digest(corpus['results'])
    with pytest.raises(ValueError, match='changed'):
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])
    assert tree_digest(corpus['results']) == before


def test_confirmation_required(corpus):
    plan = reassess.preview(**corpus)
    with pytest.raises(ValueError, match='Confirmation'):
        reassess.apply(plan_path(corpus), 'yes', repository=corpus['repository'])
    with pytest.raises(SystemExit):
        reassess.main(['apply', '--plan', str(plan_path(corpus))])
    assert plan['safe_to_publish']


def test_interrupted_publication_rolls_back_complete_set(corpus):
    plan = reassess.preview(**corpus)
    before = tree_digest(corpus['results'])
    def interrupt():
        raise KeyboardInterrupt('simulated interruption after exchange')
    with pytest.raises(KeyboardInterrupt):
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'],
                       after_exchange=interrupt)
    assert tree_digest(corpus['results']) == before
    assert len(list((corpus['runtime'] / 'reassessments/archives').iterdir())) == 1


def test_exchange_failure_leaves_production_untouched(corpus, monkeypatch):
    plan = reassess.preview(**corpus)
    before = tree_digest(corpus['results'])
    def fail(*args):
        raise OSError('simulated unsupported exchange/filesystem error')
    monkeypatch.setattr('src.career_intelligence.reassessment_publication.exchange_directories', fail)
    with pytest.raises(OSError):
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])
    assert tree_digest(corpus['results']) == before


def test_hard_process_exit_keeps_complete_generation_and_prepared_archive(corpus):
    plan = reassess.preview(**corpus)
    before = tree_digest(corpus['results'])
    def child():
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'],
                       after_exchange=lambda: os._exit(75))
    process = multiprocessing.get_context('fork').Process(target=child)
    process.start()
    process.join(10)
    assert process.exitcode == 75
    assert tree_digest(corpus['results']) == plan['candidate_tree']
    archive = next((corpus['runtime'] / 'reassessments/archives').iterdir())
    manifest = json.loads((archive / 'manifest.json').read_text())
    assert not (archive / 'published.json').exists()
    reassess.rollback(archive, manifest['rollback_token'])
    assert tree_digest(corpus['results']) == before


def test_daily_and_reassessment_exclude_each_other(corpus):
    with DailyRunLock(corpus['runtime'] / 'daily.lock'):
        with pytest.raises(DailyRunAlreadyActive):
            reassess.preview(**corpus)
    plan = reassess.preview(**corpus)
    with DailyRunLock(corpus['runtime'] / 'daily.lock'):
        with pytest.raises(DailyRunAlreadyActive):
            reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])


def test_old_live_pid_lock_and_malformed_lock_are_never_stolen(tmp_path):
    path = tmp_path / 'daily.lock'
    path.write_text(json.dumps({'pid': os.getpid(), 'created_at_utc':
                              (datetime.now(UTC) - timedelta(days=10)).isoformat()}))
    with pytest.raises(DailyRunAlreadyActive):
        with DailyRunLock(path):
            pytest.fail('stole active lock')
    path.write_text('incomplete metadata')
    with pytest.raises(DailyRunAlreadyActive):
        with DailyRunLock(path):
            pytest.fail('stole malformed lock')
    assert path.read_text() == 'incomplete metadata'


def test_repository_queries_exact_ids_without_limit(monkeypatch):
    from contextlib import contextmanager
    calls = []
    class Cursor:
        def execute(self, sql, parameters):
            calls.append((sql, parameters))
        def fetchall(self):
            return []
    class Connection:
        def execute(self, sql):
            calls.append((sql, ()))
        @contextmanager
        def cursor(self):
            yield Cursor()
    @contextmanager
    def connection():
        yield Connection()
    repository = SilverJobReadRepository()
    monkeypatch.setattr(repository, 'get_connection', connection)
    repository.load_silver_jobs(silver_job_ids=[9, 45001])
    assert calls[0][0] == 'SET TRANSACTION READ ONLY'
    sql, parameters = calls[1]
    assert 's.id = ANY(%s)' in sql and 'LIMIT' not in sql
    assert parameters == ([9, 45001],)


def test_failed_reversal_still_has_complete_results_and_recoverable_archive(corpus, monkeypatch):
    from src.career_intelligence import reassessment_publication as publication
    plan = reassess.preview(**corpus)
    before = tree_digest(corpus['results'])
    real_exchange = publication.exchange_directories
    calls = []
    def exchange(left, right):
        calls.append(1)
        if len(calls) == 2:
            raise OSError('simulated reversal failure')
        real_exchange(left, right)
    monkeypatch.setattr(publication, 'exchange_directories', exchange)
    def fail():
        raise OSError('simulated receipt failure')
    with pytest.raises(OSError, match='reversal'):
        reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'],
                       after_exchange=fail)
    assert tree_digest(corpus['results']) == plan['candidate_tree']
    archive = next((corpus['runtime'] / 'reassessments/archives').iterdir())
    assert tree_digest(archive / 'results') == before
    monkeypatch.setattr(publication, 'exchange_directories', real_exchange)
    manifest = json.loads((archive / 'manifest.json').read_text())
    reassess.rollback(archive, manifest['rollback_token'])
    assert tree_digest(corpus['results']) == before


def test_rollback_refuses_to_erase_new_operator_decisions(corpus):
    plan = reassess.preview(**corpus)
    result = reassess.apply(plan_path(corpus), plan['confirmation'], repository=corpus['repository'])
    write_state(corpus, plan['candidates'][0]['source_file'])
    state_hash = file_digest(corpus['state_path'])
    with pytest.raises(ValueError, match='Operator decisions changed'):
        reassess.rollback(Path(result['archive']), result['rollback_confirmation'])
    assert file_digest(corpus['state_path']) == state_hash
    assert tree_digest(corpus['results']) == plan['candidate_tree']


def test_archived_original_optional_evidence_is_recoverable(corpus):
    record = json.loads((corpus['results'] / 'opportunities.json').read_text())[0]
    record.pop('explanation')
    corpus['processed'].mkdir()
    original = {'company': record['company'], 'title': record['title'], 'description': 'Archived input',
                'role_evidence': {'network': {'relationship_level': 'hiring_manager_access',
                                              'status': 'confirmed', 'evidence_source': 'direct contact'}},
                'market_evidence': {}}
    (corpus['processed'] / record['source_file']).write_text(json.dumps(original))
    snapshot, origin = recover_evidence(record, corpus['processed'])
    assert origin == 'archived_original_input'
    assert snapshot['role_evidence'] == original['role_evidence']


def test_cli_defaults_to_preview(monkeypatch, tmp_path):
    calls = []
    def preview(**kwargs):
        calls.append(kwargs)
        return {key: 0 for key in ('selected', 'reassessed', 'preserved_unchanged', 'blocked', 'missing', 'unselected',
                                   'unchanged_decisions', 'old_distribution', 'new_distribution',
                                   'safe_to_publish', 'confirmation')}
    monkeypatch.setattr(reassess, 'preview', preview)
    monkeypatch.setattr(reassess, 'apply', lambda *args: pytest.fail('default must not apply'))
    assert reassess.main(['--output-dir', str(tmp_path / 'review')]) == 0
    assert len(calls) == 1


def test_preview_cannot_write_into_production(corpus):
    before = tree_digest(corpus['results'])
    corpus['output'] = corpus['results'] / 'preview'
    with pytest.raises(ValueError, match='outside production'):
        reassess.preview(**corpus)
    assert tree_digest(corpus['results']) == before


@pytest.fixture
def legacy_corpus(corpus):
    from src.career_intelligence.legacy_recovery import (
        BINDINGS, CONTRACT, LIMITATION, NOT_SUPPLIED, description_hash,
    )
    from src.career_intelligence.reassessment_publication import digest
    rows = corpus['repository'].rows
    row = rows[0]
    row['source_name'] = 'stepstone'
    row['raw_data'] = {'detail_evidence': {
        'text': 'Berlin. Vehicle software delivery. No travel required.',
        'description_quality': 'strong', 'source_url': row['source_url']}}
    rows[1]['source_name'] = 'greenhouse:moia'
    old, provenance = [], []
    for item_row in rows:
        item = adapt_silver_row(item_row)
        record = _result_record(assess_opportunity(item.company, item.title, item.description),
                                item.source_file)
        record.pop('explanation', None)
        old.append(record)
        provenance.append(item.provenance)
    (corpus['results'] / 'opportunities.json').write_text(json.dumps(old))
    (corpus['results'] / PROVENANCE_FILE).write_text(json.dumps(provenance))
    entry = {key: provenance[0][key] for key in BINDINGS}
    entry.update(source_file=old[0]['source_file'], description_sha256=description_hash(row),
                 historical_contract=CONTRACT, limitation=LIMITATION,
                 optional_evidence=deepcopy(NOT_SUPPLIED))
    manifest = {'schema_version': 1, 'review_reference': 'Synthetic regression review',
                'records': [entry]}
    corpus.update(selected=[old[0]['source_file']], recovery_manifest=manifest,
                  recovery_confirmation=digest(manifest))
    return corpus


@pytest.mark.parametrize('failure', ['identity', 'hash', 'missing', 'optional', 'confirmation'])
def test_legacy_recovery_fails_closed(legacy_corpus, failure):
    c = legacy_corpus
    row = c['repository'].rows[0]
    if failure == 'identity':
        row['raw_job_id'] += 1
    elif failure == 'hash':
        row['raw_data']['detail_evidence']['text'] += ' changed'
    elif failure == 'missing':
        c['repository'].rows = []
    elif failure == 'optional':
        row['raw_data']['role_evidence'] = {'network': {'referral': True}}
    else:
        c['recovery_confirmation'] = 'wrong'
        with pytest.raises(ValueError, match='reviewed SHA-256'):
            reassess.preview(**c)
        return
    plan = reassess.preview(**c)
    assert not plan['safe_to_publish']
    assert plan['reassessed'] == 0
    assert plan['blocked'] + plan['missing'] == 1


def test_legacy_subset_preserves_moia_state_and_atomic_rollback(legacy_corpus):
    c = legacy_corpus
    original = json.loads((c['results'] / 'opportunities.json').read_text())
    write_state(c, original[1]['source_file'])
    state_hash = file_digest(c['state_path'])
    before = tree_digest(c['results'])
    plan = reassess.preview(**c)
    assert plan['safe_to_publish'] and plan['reassessed'] == 1 and plan['preserved'] == 1
    assert plan['candidates'][1] == original[1]
    assert plan['records'][0]['recovery_provenance']['limitation']
    assert plan['candidates'][0]['explanation']['semantics_version'] == 4
    assert tree_digest(c['results']) == before
    def interrupted():
        raise KeyboardInterrupt('simulated interruption')
    with pytest.raises(KeyboardInterrupt):
        reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'],
                       after_exchange=interrupted)
    assert tree_digest(c['results']) == before
    result = reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'])
    assert json.loads((c['results'] / 'opportunities.json').read_text())[1] == original[1]
    assert file_digest(c['state_path']) == state_hash
    reassess.rollback(Path(result['archive']), result['rollback_confirmation'])
    assert tree_digest(c['results']) == before
    assert file_digest(c['state_path']) == state_hash


@pytest.fixture
def preservation_corpus(corpus):
    path = corpus['results'] / 'opportunities.json'
    records = json.loads(path.read_text())
    records[0].pop('explanation')
    # Deliberately unusual formatting: object bytes, not just semantic equality, must survive.
    path.write_text('[\n' + json.dumps(records[0], ensure_ascii=True, indent=3) + ',\n'
                    + json.dumps(records[1]) + '\n]')
    source = records[0]['source_file']
    prov = json.loads((corpus['results'] / PROVENANCE_FILE).read_text())[0]
    corpus['preservation_manifest'] = {'schema_version': 1, 'records': [{
        'source_file': source,
        'record_sha256': reassess.byte_hash(reassess.record_bytes(path)[source]),
        'provenance_sha256': reassess.digest(prov),
        'evidence_reason': 'missing_evidence_snapshot: legacy assessment has no reconstructable evidence contract',
    }]}
    return corpus


def test_explicit_preservation_atomic_apply_and_rollback(preservation_corpus):
    c = preservation_corpus
    source = c['preservation_manifest']['records'][0]['source_file']
    write_state(c, source)
    before = tree_digest(c['results'])
    state_hash = file_digest(c['state_path'])
    original = reassess.record_bytes(c['results'] / 'opportunities.json')[source]
    plan = reassess.preview(**c)
    assert plan['safe_to_publish'] and plan['reassessed'] == 1
    assert plan['preserved_unchanged'] == 1 and plan['blocked'] == plan['missing'] == 0
    assert plan['records'][0]['state'] == 'PRESERVED_UNCHANGED'
    assert 'evidence' not in plan['records'][0]
    def interrupt():
        raise KeyboardInterrupt('interrupted preservation publication')
    with pytest.raises(KeyboardInterrupt):
        reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'],
                       after_exchange=interrupt)
    assert tree_digest(c['results']) == before
    result = reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'])
    assert reassess.record_bytes(c['results'] / 'opportunities.json')[source] == original
    assert file_digest(c['state_path']) == state_hash
    reassess.rollback(Path(result['archive']), result['rollback_confirmation'])
    assert tree_digest(c['results']) == before
    assert file_digest(c['state_path']) == state_hash


@pytest.mark.parametrize('failure', ['hash', 'missing', 'identity', 'provenance', 'assessment'])
def test_explicit_preservation_fails_closed(preservation_corpus, monkeypatch, failure):
    c = preservation_corpus
    entry = c['preservation_manifest']['records'][0]
    if failure == 'hash':
        entry['record_sha256'] = 'wrong'
    elif failure == 'missing':
        path = c['results'] / 'opportunities.json'
        records = json.loads(path.read_text())
        c['selected'] = [r['source_file'] for r in records]
        path.write_text(json.dumps(records[1:]))
    elif failure == 'identity':
        c['repository'].rows[0]['title'] = 'changed'
    elif failure == 'provenance':
        entry['provenance_sha256'] = 'wrong'
    else:
        def fail(*args, **kwargs):
            raise ValueError('assessment failure')
        monkeypatch.setattr(reassess, 'assess_opportunity', fail)
    plan = reassess.preview(**c)
    assert not plan['safe_to_publish']
    assert plan['blocked'] + plan['missing'] >= 1
    with pytest.raises(ValueError, match='Blocked'):
        reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'])


def test_preserved_candidate_byte_tampering_rejected(preservation_corpus):
    c = preservation_corpus
    plan = reassess.preview(**c)
    path = c['output'] / 'candidate/opportunities.json'
    path.write_text(json.dumps(json.loads(path.read_text())))
    with pytest.raises(ValueError, match='hash mismatch'):
        reassess.verify_preserved(plan, c['results'], c['output'] / 'candidate')
    with pytest.raises(ValueError, match='candidate files changed'):
        reassess.apply(plan_path(c), plan['confirmation'], repository=c['repository'])
