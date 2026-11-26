from src.career_intelligence import target_company_monitor as monitor


class Cursor:
    def __init__(self, candidate, profile):
        self.rows = iter([candidate, profile])
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql, params):
        assert 'SELECT' in sql
        assert not any(word in sql for word in ['UPDATE', 'INSERT', 'DELETE'])
    def fetchone(self):
        return next(self.rows)


class Connection:
    def __init__(self, candidate=None, profile=None):
        self.candidate, self.profile = candidate, profile
    def cursor(self, **kwargs):
        return Cursor(self.candidate, self.profile)


def test_all_requested_watchlist_groups_and_truthful_gaps():
    companies = monitor.load_watchlist()
    assert len(companies) == 27
    assert len({c['group'] for c in companies}) == 3
    configured = [c for c in companies if c.get('profile_name')]
    assert {c['company_key'] for c in configured} == {'waymo', 'moia'}
    assert all(c['status'] in monitor.STATUSES for c in companies)


def test_registered_family_does_not_imply_verified_company_binding():
    company = dict(company_key='uber', company_name='Uber', source_name='greenhouse:uber',
                   status='not_evaluated')
    result = monitor.company_coverage(Connection(), company)
    assert result['status'] == 'candidate_source_gap'
    assert result['eligible'] is False


def test_controlled_profiles_require_active_profile_and_current_gates(monkeypatch):
    company = monitor.load_watchlist()[0]
    conn = Connection({'id': 42, 'status': 'active_controlled'}, {'profile_name': 'existing'})
    monkeypatch.setattr(monitor, '_gate_passed', lambda *a, **k: True)
    assert monitor.company_coverage(conn, company)['eligible'] is True
    monkeypatch.setattr(monitor, '_gate_passed', lambda *a, **k: False)
    assert monitor.company_coverage(conn, company)['status'] == 'blocked'
    assert monitor.company_coverage(Connection(), company)['eligible'] is False


def test_monitor_isolates_failure_and_never_runs_gaps(monkeypatch):
    companies = [dict(company_name='Waymo', eligible=True, profile_name='w', source_name='w'),
                 dict(company_name='MOIA', eligible=True, profile_name='m', source_name='m'),
                 dict(company_name='Gap', eligible=False)]
    monkeypatch.setattr(monitor, 'inspect_watchlist', lambda: companies)
    calls = []
    class Operations:
        def run_ingestion_profile(self, name):
            calls.append(name)
            if name == 'w':
                raise RuntimeError('network failure')
            return type('Result', (), dict(error=None, status='success'))()
        def run_silver(self, *a, **k):
            return 0
        def run_career_intelligence(self, *a, **k):
            return 0, []
        def latest_retrieval(self):
            return {'records': [{'identity': 'new'}]}
    coverage, errors, records = monitor.run_target_monitor(Operations(), limit=10)
    assert calls == ['w', 'm']
    assert len(errors) == 1
    assert coverage[0]['status'] == 'blocked'
    assert coverage[1]['checked'] is True
    assert records == [{'identity': 'new'}]
