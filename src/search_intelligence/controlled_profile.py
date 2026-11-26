"""Explicit activation scope, separate from approval and acquisition authority."""
import json
from pathlib import Path


def load_controlled_profile(path: Path, company_key: str) -> dict:
    value = json.loads(path.read_text())
    required = {'company_key', 'source_name', 'profile_name', 'search_location',
                'search_radius_km', 'page_size', 'recurring_ingestion_enabled', 'search_terms'}
    if set(value) != required or value['company_key'] != company_key:
        raise ValueError('Controlled profile schema/company mismatch')
    if value['recurring_ingestion_enabled'] is not False:
        raise ValueError('Recurring ingestion requires separate approval')
    if not isinstance(value['search_terms'], list) or not value['search_terms'] or any(
        not isinstance(t, str) or not t.strip() or t.strip() == '*' for t in value['search_terms']
    ):
        raise ValueError('Explicit non-wildcard search terms required')
    if (not value['source_name'].startswith('greenhouse:')
            or value['search_location'] != 'Germany' or value['search_radius_km'] is not None
            or type(value['page_size']) is not int or not 1 <= value['page_size'] <= 100
            or not isinstance(value['profile_name'], str) or not value['profile_name'].strip()):
        raise ValueError('Unsupported controlled Germany profile')
    return value
