"""Local scheduled operation of the existing discovery and qualification components.

No scoring, historical reassessment, operator transitions or source activation.
Outputs are private operational reports, never authoritative pipeline inputs.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import time

import psycopg
from psycopg.rows import dict_row

from src.career_intelligence.daily import DailyRunLock
from src.career_intelligence.discovery_v3 import run, V34_CONFIG, V34_EMPLOYERS
from src.career_intelligence.market_intelligence import load_market_intelligence, production_strategy
from src.config import get_database_config

RUNTIME = Path('.runtime/career_intelligence/operations')


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, default=str) + '\n')
    temporary.replace(path)


def main() -> int:
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    output = RUNTIME / 'logs' / f'daily_{stamp}.json'
    report = {'started_at': datetime.now(UTC).isoformat(), 'status': 'running',
              'production_strategy': production_strategy(), 'manual_review_minutes': None,
              'manual_quality_review': 'not_recorded',
              'availability_limit': 'Board presence is not independently verified employer availability.'}
    try:
        with DailyRunLock(RUNTIME / 'daily.lock'):
            if production_strategy() != 'v3.4':
                raise ValueError('V3.4 scheduled job disabled by deployment selection')
            from src.career_intelligence.competency_qualification import (
                load_strategy, load_candidate_evidence,
            )
            candidate = load_candidate_evidence(load_strategy())
            if not candidate['verified_professional_facts'] or not candidate['candidate_context'].get('approval'):
                raise ValueError('Approved candidate evidence is required before discovery')
            # Docker/PostgreSQL can take time to start after login. Never fabricate a successful run.
            database = get_database_config()
            for attempt in range(12):
                try:
                    with psycopg.connect(**database, connect_timeout=5) as conn:
                        conn.execute('SELECT 1')
                    break
                except psycopg.OperationalError:
                    if attempt == 11:
                        raise
                    time.sleep(5)
            backup = RUNTIME / 'backups' / f'postgres_{stamp}.dump'
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open('wb') as handle:
                subprocess.run(['docker', 'exec', 'job_pipeline_postgres', 'pg_dump',
                                '-U', database['user'], '-d', database['dbname'], '-Fc'],
                               stdout=handle, check=True, timeout=180)
            report['database_backup'] = str(backup)
            retrieval = run(config_path=V34_CONFIG, employers_path=V34_EMPLOYERS,
                            results_dir=RUNTIME,
                            query_offset=datetime.now(UTC).date().toordinal())
            report['run_group_id'] = retrieval['run_group_id']
            report['http_requests'] = retrieval['http_requests']
            report['runs'] = retrieval['runs']
            with psycopg.connect(**database, options='-c default_transaction_read_only=on') as conn:
                market = load_market_intelligence(conn)
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute('''SELECT e.event_type, count(*) AS count
                        FROM career_discovery_events e JOIN career_discovery_runs r ON r.id=e.run_id
                        WHERE r.run_group_id=%s GROUP BY e.event_type''', (retrieval['run_group_id'],))
                    report['vacancy_events'] = cur.fetchall()
            write_report(RUNTIME / 'market_intelligence.v34.json', market)
            qualifications = [v['qualification'] for v in market['vacancies'] if v.get('qualification')]
            report['qualification_counts'] = dict(Counter(q['status'] for q in qualifications))
            report['review_judgments'] = dict(Counter(q['opportunity_review']['judgment'] for q in qualifications))
            report['posting_activity'] = dict(Counter(q['opportunity_review']['posting_activity'] for q in qualifications))
            report['active_actual_vacancies'] = len(market['vacancies'])
            report['change_evidence_limit'] = 'BA source timestamp changes are not verified description changes.'
            report['source_failures'] = [r for r in retrieval['runs'] if r.get('status') != 'succeeded']
            report['status'] = 'degraded' if report['source_failures'] else 'succeeded'
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    report['finished_at'] = datetime.now(UTC).isoformat()
    write_report(output, report)
    write_report(RUNTIME / 'latest.json', report)
    print(json.dumps({k: report.get(k) for k in ('status', 'run_group_id', 'started_at', 'finished_at', 'error')}), flush=True)
    return 0 if report['status'] == 'succeeded' else 1


if __name__ == '__main__':
    raise SystemExit(main())
