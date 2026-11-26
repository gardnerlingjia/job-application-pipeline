"""Explicit, identity-bound recovery of reviewed legacy StepStone inputs only."""
from hashlib import sha256

from src.career_intelligence.reassessment_publication import digest

CONTRACT = '3d2bf7e:src/career_intelligence/ingest_silver.py:359;src/career_intelligence/assessor.py:14'
LIMITATION = ('Retained captured description is available, but historical assessment-time '
              'byte-for-byte equivalence cannot be proven.')
NOT_SUPPLIED = {'role_evidence': 'not_supplied', 'market_evidence': 'not_supplied'}
BINDINGS = ('silver_job_id', 'raw_job_id', 'source_name', 'external_job_id',
            'stable_identity_type', 'stable_identity_sha256')


def description_hash(row):
    text = row.get('raw_data', {}).get('detail_evidence', {}).get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('legacy_recovery_missing_description')
    return sha256(text.encode('utf-8')).hexdigest()


def validate_manifest(manifest, confirmation):
    if digest(manifest) != confirmation:
        raise ValueError('Legacy recovery manifest requires its exact reviewed SHA-256')
    if manifest.get('schema_version') != 1 or not manifest.get('review_reference'):
        raise ValueError('Invalid legacy recovery review')
    records = manifest.get('records', [])
    identities = [r['source_file'] for r in records]
    if not records or len(set(identities)) != len(identities):
        raise ValueError('Legacy recovery identities must be explicit and unique')
    return {r['source_file']: r for r in records}


def recover_legacy(old, row, provenance, entry):
    if old.get('explanation') or row['source_name'] != 'stepstone':
        raise ValueError('legacy_recovery_not_eligible')
    for key in BINDINGS:
        if entry.get(key) != provenance.get(key):
            raise ValueError(f'legacy_recovery_identity_mismatch: {key}')
    if entry.get('source_file') != old['source_file']:
        raise ValueError('legacy_recovery_identity_mismatch: source_file')
    if entry.get('historical_contract') != CONTRACT or entry.get('optional_evidence') != NOT_SUPPLIED:
        raise ValueError('legacy_recovery_unexpected_optional_evidence_or_contract')
    if entry.get('limitation') != LIMITATION:
        raise ValueError('legacy_recovery_missing_limitation')
    # Fail closed if any retained payload contains separately supplied assessment evidence.
    def check(value):
        if isinstance(value, dict):
            if {'role_evidence', 'market_evidence', 'input_evidence'} & value.keys():
                raise ValueError('legacy_recovery_unexpected_optional_evidence')
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(old)
    check(row)
    if entry.get('description_sha256') != description_hash(row):
        raise ValueError('legacy_recovery_description_hash_mismatch')
    detail = row['raw_data']['detail_evidence']
    if (detail.get('description_quality') != 'strong'
            or detail.get('source_url') != row.get('source_url')
            or provenance.get('description_source') != 'detail_evidence.text'):
        raise ValueError('legacy_recovery_description_source_mismatch')
    return {'schema_version': 1, 'role_evidence': {}, 'market_evidence': {}}
