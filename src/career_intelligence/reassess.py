"""Controlled reassessment of saved identities: preview by default, confirmed apply/rollback."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import json
import hashlib
from pathlib import Path
import shutil
import uuid

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.batch import _load_existing_results, _result_record
from src.career_intelligence.daily import DailyRunLock, DEFAULT_RUNTIME_DIR
from src.career_intelligence.ingest_silver import (
    PROVENANCE_FILE, _load_existing_provenance, _validate_provenance_record,
    _apply_freshness_to_assessment,
    _remove_missing_description_evidence,
)
from src.career_intelligence.operator_state import (
    DEFAULT_STATE_PATH, load_state_payload, render_operator_radar,
)
from src.career_intelligence.reassessment_evidence import recover_evidence
from src.career_intelligence.legacy_recovery import validate_manifest, recover_legacy
from src.career_intelligence.reassessment_publication import (
    digest, file_digest, tree_digest, publish,
)
from src.career_intelligence.silver_adapter import SilverJobReadRepository, adapt_silver_row


ROOT = Path(__file__).resolve().parents[2]


def calibration_snapshot() -> dict:
    paths = [ROOT / 'config' / name for name in (
        'career_profile.yaml', 'capability_profile.yaml', 'constraints.yaml', 'network_profile.yaml')]
    paths += sorted((ROOT / 'src/career_intelligence').glob('*.py'))
    return {str(path.relative_to(ROOT)): file_digest(path) for path in paths}


def run_name() -> str:
    return datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]


def constraints(record: dict) -> list:
    return sorted({(r.get('constraint', ''), r.get('action', ''), r.get('severity', ''))
                   for r in record.get('risks', [])})


def version(record: dict):
    return record.get('explanation', {}).get('semantics_version')


def summary_value(record: dict) -> dict:
    return {'score': record['opportunity_score'], 'recommendation': record['recommendation'],
            'semantics_version': version(record), 'constraint_action': record['constraint_action'],
            'constraints': constraints(record)}


def validate_identity(old: dict, provenance: dict, item) -> None:
    _validate_provenance_record(provenance)
    for key in ('silver_job_id', 'raw_job_id', 'source_name', 'external_job_id',
                'stable_identity_type', 'stable_identity_sha256'):
        if key not in provenance or provenance[key] != item.provenance.get(key):
            raise ValueError(f'identity_mismatch: {key}')
    if provenance.get('ingestion_status') != 'assessed':
        raise ValueError('provenance_not_assessed')
    if old['source_file'] != item.source_file or old['source_file'] != provenance.get('source_file'):
        raise ValueError('identity_mismatch: source_file')
    if old['company'] != item.company or old['title'] != item.title:
        raise ValueError('identity_mismatch: company/title changed; manual review required')


def record_bytes(path: Path) -> dict[str, str]:
    """Retain exact JSON object lexemes, including whitespace and escape spelling."""
    text = path.read_bytes().decode('utf-8')
    decoder = json.JSONDecoder()
    offset = text.index('[') + 1
    records = {}
    while True:
        while offset < len(text) and text[offset] in ' \r\n\t,':
            offset += 1
        if text[offset] == ']':
            break
        start = offset
        value, offset = decoder.raw_decode(text, offset)
        source = value['source_file']
        if source in records:
            raise ValueError('Duplicate saved identities')
        records[source] = text[start:offset]
    return records


def byte_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def verify_preserved(plan: dict, results: Path, candidate: Path) -> None:
    originals = record_bytes(results / 'opportunities.json')
    proposed = record_bytes(candidate / 'opportunities.json')
    if set(originals) != set(proposed):
        raise ValueError('Incomplete publication identity set')
    if (results / PROVENANCE_FILE).read_bytes() != (candidate / PROVENANCE_FILE).read_bytes():
        raise ValueError('Publication provenance mismatch')
    accounted = [r['source_file'] for r in plan['records'] if r['source_file'] in originals]
    if len(accounted) != len(originals) or set(accounted) != set(originals):
        raise ValueError('Incomplete or duplicate publication accounting')
    for record in plan['records']:
        if record['status'] == 'preserved':
            if originals[record['source_file']] != proposed[record['source_file']]:
                raise ValueError('Unselected record changed')
        if record['status'] == 'preserved_unchanged':
            source = record['source_file']
            expected = record['preservation']['record_sha256']
            if (source not in originals or source not in proposed
                    or byte_hash(originals[source]) != expected
                    or byte_hash(proposed[source]) != expected):
                raise ValueError('Preserved record hash mismatch')


def build_preview(opportunities: list, provenance: list, rows: list, selected: list[str],
                  *, processed: Path, recovery_entries=None, preservation_entries=None, raw_records=None) -> dict:
    originals = {r['source_file']: r for r in opportunities}
    if len(originals) != len(opportunities):
        raise ValueError('Duplicate saved identities; repair before reassessment')
    by_id = {}
    for row in rows:
        by_id.setdefault(row['silver_job_id'], []).append(row)
    candidate = deepcopy(opportunities)
    positions = {r['source_file']: i for i, r in enumerate(candidate)}
    outcomes, inputs = [], {}
    for source in selected:
        old = originals.get(source)
        if old is None:
            outcomes.append({'source_file': source, 'status': 'missing',
                             'reasons': ['selected_identity_not_saved']})
            continue
        outcome = {'source_file': source, 'company': old['company'], 'title': old['title'],
                   'old': summary_value(old), 'new': None, 'reasons': []}
        records = [r for r in provenance if r.get('source_file') == source]
        item, evidence = None, None
        if len(records) != 1:
            outcome['reasons'].append('incomplete_provenance: expected exactly one provenance record')
        else:
            prov = records[0]
            sid = prov.get('silver_job_id')
            if type(sid) is not int or sid <= 0:
                outcome['reasons'].append('incomplete_provenance: valid silver_job_id required')
            else:
                matches = by_id.get(sid, [])
                if not matches:
                    outcome['reasons'].append('missing_silver_identity')
                elif len(matches) != 1:
                    outcome['reasons'].append('ambiguous_silver_identity')
                else:
                    inputs[source] = deepcopy(matches[0])
                    try:
                        item = adapt_silver_row(matches[0])
                        validate_identity(old, prov, item)
                        # Calibration-only: retain the published freshness policy/penalty.
                        penalty = prov.get('freshness_ranking_penalty')
                        if type(penalty) is not int or penalty not in {0, 8, 15}:
                            raise ValueError('incomplete_provenance: unsupported freshness penalty')
                        item = replace(item, freshness=replace(item.freshness, ranking_penalty=penalty))
                    except ValueError as exc:
                        outcome['reasons'].append(str(exc))
        try:
            entry = (recovery_entries or {}).get(source)
            if entry is not None:
                if (processed / source).exists():
                    raise ValueError('legacy_recovery_original_input_present: review original evidence')
                if outcome['reasons'] or item is None:
                    raise ValueError('legacy_recovery_identity_chain_unavailable')
                evidence = recover_legacy(old, matches[0], prov, entry)
                origin = 'reviewed_legacy_three_argument_contract'
                outcome['recovery_provenance'] = deepcopy(entry)
            else:
                evidence, origin = recover_evidence(old, processed)
            outcome['evidence_origin'] = origin
        except (ValueError, OSError, TypeError) as exc:
            outcome['reasons'].append(str(exc))
        if not outcome['reasons']:
            try:
                assessment = assess_opportunity(
                    item.company, item.title, item.description,
                    role_evidence=deepcopy(evidence['role_evidence']),
                    market_evidence=deepcopy(evidence['market_evidence']),
                    structured_location=deepcopy(evidence.get(
                        'structured_location', item.structured_location)),
                )
                evidence = {**evidence, 'structured_location': deepcopy(evidence.get(
                    'structured_location', item.structured_location))}
                assessment['explanation']['input_evidence'] = evidence
                assessment = _remove_missing_description_evidence(assessment, item)
                assessment = _apply_freshness_to_assessment(assessment, item)
                new = _result_record(assessment, source)
                candidate[positions[source]] = new
                outcome.update(status='reassessed', new=summary_value(new),
                               input_sha256=digest(inputs[source]), evidence=deepcopy(evidence))
                before_constraints, after_constraints = set(constraints(old)), set(constraints(new))
                outcome['constraints_added'] = sorted(after_constraints - before_constraints)
                outcome['constraints_removed'] = sorted(before_constraints - after_constraints)
                outcome['decision_unchanged'] = (
                    old['opportunity_score'] == new['opportunity_score']
                    and old['recommendation'] == new['recommendation']
                    and before_constraints == after_constraints
                    and old['constraint_action'] == new['constraint_action'])
                # Original source provenance remains untouched; new derived values live in the revision.
                outcome['reassessment_provenance'] = deepcopy(item.provenance)
            except Exception as exc:
                outcome['reasons'].append(f'assessment_failed: {type(exc).__name__}: {exc}')
        preservation = (preservation_entries or {}).get(source)
        if preservation is not None:
            candidate[positions[source]] = deepcopy(old)
            reason = preservation.get('evidence_reason')
            # Only a validated identity with this exact evidence-only failure is eligible.
            if (outcome['reasons'] == [reason] and isinstance(reason, str)
                    and reason.startswith('missing_evidence_snapshot:')
                    and item is not None and evidence is None
                    and preservation.get('record_sha256') == byte_hash((raw_records or {}).get(source, ''))
                    and preservation.get('provenance_sha256') == digest(records[0])):
                outcome.update(status='preserved_unchanged', new=summary_value(old),
                               preservation=deepcopy(preservation))
            else:
                outcome['reasons'].append('preservation_validation_failed: hash, provenance or evidence reason')
        if outcome['reasons'] and outcome.get('status') != 'preserved_unchanged':
            outcome['status'] = 'missing' if 'missing_silver_identity' in outcome['reasons'] else 'blocked'
        outcomes.append(outcome)
    for source, old in originals.items():
        if source not in selected:
            outcomes.append({'source_file': source, 'company': old['company'], 'title': old['title'],
                             'status': 'preserved', 'old': summary_value(old),
                             'new': summary_value(old),
                             'reasons': ['Explicitly unselected; preserved unchanged']})
    for outcome in outcomes:
        outcome['state'] = outcome['status'].upper()
    counts = Counter(r['status'] for r in outcomes)
    return {
        'records': outcomes, 'candidates': candidate, 'inputs': inputs,
        'total': len(opportunities), 'preserved': counts['preserved'],
        'preserved_unchanged': counts['preserved_unchanged'],
        'selected': len(selected), 'reassessed': counts['reassessed'],
        'blocked': counts['blocked'], 'missing': counts['missing'],
        'unselected': len(set(originals) - set(selected)),
        'unchanged_decisions': sum(r.get('decision_unchanged', False) for r in outcomes),
        'old_distribution': dict(Counter(r['recommendation'] for r in opportunities)),
        'new_distribution': dict(Counter(r['recommendation'] for r in candidate)),
        'safe_to_publish': not counts['blocked'] and not counts['missing'] and counts['reassessed'] > 0,
    }


def render_report(plan: dict) -> str:
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Career Intelligence reassessment preview', '',
             f"Total: {plan['total']}; preserved unchanged: {plan.get('preserved_unchanged', 0)}; preserved: {plan['preserved']}; selected: {plan['selected']}; reassessed: {plan['reassessed']}; "
             f"blocked: {plan['blocked']}; missing: {plan['missing']}; unselected: {plan['unselected']}.",
             f"Unchanged decisions: {plan['unchanged_decisions']}.",
             f"Publication eligible: {plan['safe_to_publish']} (apply revalidates all fingerprints).", '',
             f"Old distribution: {plan['old_distribution']}",
             f"Proposed complete-set distribution: {plan['new_distribution']}", '',
             'Blocked/missing records retain their existing result. No production files changed.', '',
             '| Company / title | Identity | Status | Score | Recommendation | Semantics | Details |',
             '|---|---|---|---|---|---|---|']
    for record in plan['records']:
        old, new = record.get('old', {}), record.get('new') or {}
        details = '; '.join(record['reasons']) or (
            f"Added: {record['constraints_added']}; removed: {record['constraints_removed']}"
            + ('; decision unchanged' if record['decision_unchanged'] else ''))
        if record.get('recovery_provenance'):
            details += '; Recovery: ' + json.dumps(record['recovery_provenance'], sort_keys=True)
        values = [f"{record.get('company', '')} / {record.get('title', '')}", record['source_file'],
                  record['status'], f"{old.get('score')} → {new.get('score', 'unchanged')}",
                  f"{old.get('recommendation')} → {new.get('recommendation', 'unchanged')}",
                  f"{old.get('semantics_version')} → {new.get('semantics_version', 'unchanged')}", details]
        lines.append('| ' + ' | '.join(map(cell, values)) + ' |')
    lines += ['', 'Original provenance is copied unchanged. Derived reassessment provenance and exact '
              'evidence are stored in plan.json. Freshness penalty is held at the published value.', '',
              f"Confirmation fingerprint: `{plan['confirmation']}`", '']
    return '\n'.join(lines)


def selected_ids(provenance: list, selected: list) -> list[int]:
    return sorted({r['silver_job_id'] for r in provenance if r.get('source_file') in selected
                   and type(r.get('silver_job_id')) is int and r['silver_job_id'] > 0})


def preview(*, results: Path, state_path: Path, runtime: Path, processed: Path,
            output: Path, selected=None, repository=None, recovery_manifest=None,
            recovery_confirmation=None, preservation_manifest=None) -> dict:
    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run reassessment from the repository root so calibration paths are exact")
    if results.is_symlink():
        raise ValueError('Production results must be a real directory')
    results, output, runtime = results.resolve(), output.resolve(), runtime.resolve()
    if (output.is_relative_to(results) or results.is_relative_to(output)
            or runtime.is_relative_to(results) or state_path.resolve().is_relative_to(results)):
        raise ValueError('Preview must be outside production results')
    recovery_entries = {}
    if recovery_manifest is not None:
        recovery_entries = validate_manifest(recovery_manifest, recovery_confirmation)
    repository = repository or SilverJobReadRepository()
    with DailyRunLock(runtime / 'daily.lock'):
        before, state_hash = tree_digest(results), file_digest(state_path)
        state = load_state_payload(state_path)
        calibration = calibration_snapshot()
        opportunities = _load_existing_results(results / 'opportunities.json')
        provenance = _load_existing_provenance(results / PROVENANCE_FILE)
        selected = sorted(set(selected)) if selected else [r['source_file'] for r in opportunities]
        if not set(recovery_entries) <= set(selected):
            raise ValueError('Recovery manifest includes unselected identities')
        if preservation_manifest is not None:
            if (preservation_manifest.get('schema_version') != 1
                    or not isinstance(preservation_manifest.get('records'), list)):
                raise ValueError('Invalid preservation manifest')
        preservation_entries = {}
        for entry in (preservation_manifest or {}).get('records', []):
            source = entry['source_file']
            if source in preservation_entries:
                raise ValueError('Duplicate preservation identity')
            preservation_entries[source] = entry
        if not set(preservation_entries) <= set(selected):
            raise ValueError('Preservation requires explicit selected identities')
        raw_records = record_bytes(results / 'opportunities.json')
        ids = selected_ids(provenance, selected)
        rows = repository.load_silver_jobs(silver_job_ids=ids)
        plan = build_preview(opportunities, provenance, rows, selected, processed=processed,
                             recovery_entries=recovery_entries, preservation_entries=preservation_entries,
                             raw_records=raw_records)
        plan['preservation_manifest'] = deepcopy(preservation_manifest)
        plan['legacy_recovery_manifest'] = deepcopy(recovery_manifest)
        plan['legacy_recovery_confirmation'] = recovery_confirmation
        plan.update(schema_version=1, created_at=datetime.now(UTC).isoformat(),
                    results=str(results.resolve()), state_path=str(state_path.resolve()),
                    runtime=str(runtime.resolve()), before=before, state_hash=state_hash,
                    calibration=calibration, selected_identities=selected,
                    silver_ids=ids, input_rows_sha256=digest(rows))
        if (tree_digest(results) != before or file_digest(state_path) != state_hash
                or calibration_snapshot() != calibration):
            raise ValueError('Inputs changed during preview; retry')
        output.mkdir(parents=True, exist_ok=False)
        shutil.copytree(results, output / 'candidate')
        (output / 'candidate/opportunities.json').write_text(
            '[\n' + ',\n'.join(
                raw_records[r['source_file']] if r['source_file'] in {
                    o['source_file'] for o in plan['records']
                    if o['status'] != 'reassessed'}
                else json.dumps(r, indent=2, ensure_ascii=False)
                for r in plan['candidates']) + '\n]\n')
        (output / 'candidate/opportunity_radar.md').write_text(
            render_operator_radar(plan['candidates'], state, include_dismissed=True))
        verify_preserved(plan, results, output / 'candidate')
        plan['candidate_tree'] = tree_digest(output / 'candidate')
        plan['confirmation'] = digest(plan)
        (output / 'plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False, default=str) + '\n')
        (output / 'report.md').write_text(render_report(plan))
        return plan


def read_plan(path: Path, confirmation: str) -> dict:
    plan = json.loads(path.read_text())
    expected = plan.pop('confirmation')
    if digest(plan) != expected or confirmation != expected:
        raise ValueError('Confirmation does not match the reviewed preview')
    plan['confirmation'] = expected
    return plan


def apply(path: Path, confirmation: str, *, repository=None, after_exchange=None) -> dict:
    plan = read_plan(path, confirmation)
    if (not plan['safe_to_publish'] or any(
            r['status'] not in {'reassessed', 'preserved_unchanged', 'preserved'}
            for r in plan['records'])):
        raise ValueError('Blocked/missing records: resolve them or preview an explicit eligible subset')
    results, state_path = Path(plan['results']), Path(plan['state_path'])
    runtime = Path(plan['runtime'])
    with DailyRunLock(runtime / 'daily.lock'):
        if tree_digest(results) != plan['before'] or file_digest(state_path) != plan['state_hash']:
            raise ValueError('Production results/operator states changed; generate a new preview')
        if calibration_snapshot() != plan['calibration']:
            raise ValueError('Calibration changed; generate a new preview')
        if tree_digest(path.parent / 'candidate') != plan['candidate_tree']:
            raise ValueError('Preview candidate files changed')
        repository = repository or SilverJobReadRepository()
        if digest(repository.load_silver_jobs(silver_job_ids=plan['silver_ids'])) != plan['input_rows_sha256']:
            raise ValueError('Silver evidence changed; generate a new preview')
        verify_preserved(plan, results, path.parent / 'candidate')
        archive = runtime / 'reassessments/archives' / run_name()
        manifest = publish(results, path.parent / 'candidate', archive, state_path,
                           metadata={'preview': plan}, after_exchange=after_exchange)
        return {'archive': str(archive), 'rollback_confirmation': manifest['rollback_token']}


def rollback(archive: Path, confirmation: str) -> dict:
    manifest = json.loads((archive / 'manifest.json').read_text())
    expected = manifest.pop('rollback_token')
    if digest(manifest) != expected or confirmation != expected:
        raise ValueError('Rollback confirmation mismatch')
    metadata = manifest['metadata']
    runtime = Path(metadata['preview']['runtime'])
    results, state_path = Path(manifest['results']), Path(manifest['state_path'])
    with DailyRunLock(runtime / 'daily.lock'):
        if tree_digest(results) != manifest['after']:
            raise ValueError('Current results differ from the published generation; refusing rollback')
        if tree_digest(archive / 'results') != manifest['before']:
            raise ValueError('Archive integrity check failed')
        if file_digest(state_path) != manifest['state_hash']:
            raise ValueError('Operator decisions changed; refusing to restore a stale radar')
        undo = runtime / 'reassessments/archives' / run_name()
        restored = publish(results, archive / 'results', undo, state_path, metadata=metadata)
        return {'archive': str(undo), 'rollback_confirmation': restored['rollback_token']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=['preview', 'apply', 'rollback'], default='preview')
    parser.add_argument('--results', type=Path, default=Path('jobs/results'))
    parser.add_argument('--state-file', type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument('--runtime-dir', type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument('--processed', type=Path, default=Path('jobs/processed'))
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--source-file', action='append')
    parser.add_argument('--preservation-manifest', type=Path)
    parser.add_argument('--recovery-manifest', type=Path)
    parser.add_argument('--recovery-confirm', help='Reviewed recovery manifest SHA-256')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--confirm', help='Exact fingerprint printed by the reviewed preview/archive')
    args = parser.parse_args(argv)
    if args.mode != 'preview' and (
        args.results != Path('jobs/results') or args.state_file != DEFAULT_STATE_PATH
        or args.runtime_dir != DEFAULT_RUNTIME_DIR or args.processed != Path('jobs/processed')
        or args.output_dir is not None or args.source_file
        or args.recovery_manifest or args.recovery_confirm or args.preservation_manifest
    ):
        parser.error('Apply/rollback use the paths and scope frozen in the reviewed plan/archive')
    try:
        if args.mode == 'preview':
            output = args.output_dir or args.runtime_dir / 'reassessments/previews' / run_name()
            plan = preview(results=args.results, state_path=args.state_file, runtime=args.runtime_dir,
                           processed=args.processed, output=output, selected=args.source_file,
                           recovery_manifest=(json.loads(args.recovery_manifest.read_text())
                                              if args.recovery_manifest else None),
                           recovery_confirmation=args.recovery_confirm,
                           preservation_manifest=(json.loads(args.preservation_manifest.read_text())
                                                  if args.preservation_manifest else None))
            print(json.dumps({k: plan[k] for k in (
                'selected', 'reassessed', 'preserved_unchanged', 'blocked', 'missing', 'unselected', 'unchanged_decisions',
                'old_distribution', 'new_distribution', 'safe_to_publish', 'confirmation')}, indent=2))
            print(f'Report: {output / "report.md"}\nPlan: {output / "plan.json"}')
            return 0
        if not args.confirm:
            parser.error('apply/rollback require --confirm with an exact reviewed fingerprint')
        if args.mode == 'apply':
            if not args.plan:
                parser.error('apply requires --plan')
            print(json.dumps(apply(args.plan, args.confirm), indent=2))
        else:
            if not args.archive:
                parser.error('rollback requires --archive')
            print(json.dumps(rollback(args.archive, args.confirm), indent=2))
        return 0
    except Exception as exc:
        print(f'BLOCKED: {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
