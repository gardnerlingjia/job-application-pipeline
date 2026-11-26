from pathlib import Path


from scripts.review_employer_origin_activation_readiness import (
    ActiveProfile,
    candidate_from_raw_record,
    is_probable_job_detail_record,
    non_job_preview_records,
    summarize_overall_readiness,
)
from src.connectors.base import RawJobRecord


def raw_record(title: str, url: str, profile_terms: list[str]) -> RawJobRecord:
    return RawJobRecord(
        source_name="enercity:discovery",
        source_url=url,
        external_job_id=title.lower().replace(" ", "-"),
        raw_data={
            "job": {
                "title": title,
                "company_name": "enercity AG",
                "location": "Hannover",
                "source_url": url,
                "profile_terms": profile_terms,
            },
            "result_card": {
                "title": title,
                "company_name": "enercity AG",
                "location": "Hannover",
                "detail_url": url,
            },
        },
    )


def test_candidate_from_raw_record_uses_employer_origin_evidence() -> None:
    record = raw_record(
        "Cloud Infrastructure DevOps Engineer",
        "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-J1",
        ["cloud", "azure"],
    )

    candidate = candidate_from_raw_record(record)

    assert candidate.source_candidate_url == record.source_url
    assert candidate.page_title == "Cloud Infrastructure DevOps Engineer"
    assert candidate.recommendation == "employer_origin_activation_readiness_record"
    assert candidate.matched_profile_terms == "cloud; azure"
    assert candidate.matched_location_terms == "Hannover"


def test_overall_readiness_blocks_without_final_approval() -> None:
    assert (
        summarize_overall_readiness(final_approval_passed=False, active_profiles=[], rows=[])
        == "activation_readiness_blocked_missing_final_approval"
    )


def test_overall_readiness_blocks_when_source_is_already_active() -> None:
    active = [ActiveProfile(profile_name="enercity_active", source_name="enercity:discovery", is_active=True)]

    assert (
        summarize_overall_readiness(final_approval_passed=True, active_profiles=active, rows=[])
        == "activation_readiness_blocked_already_active"
    )


def test_script_uses_shared_database_config() -> None:
    text = Path("scripts/review_employer_origin_activation_readiness.py").read_text(encoding="utf-8")

    assert "from src.config import get_database_config" in text
    assert "psycopg.connect(**get_database_config())" in text
    assert "os.environ[" not in text


def test_script_keeps_readiness_boundary() -> None:
    text = Path("scripts/review_employer_origin_activation_readiness.py").read_text(encoding="utf-8")

    assert '"database_writes": False' in text
    assert '"search_profile_created": False' in text
    assert '"source_activation_allowed": False' in text
    assert '"bronze_persistence_allowed": False' in text
    assert '"scheduler_change_allowed": False' in text


def test_script_reuses_shared_database_config_for_uniqueness_evidence() -> None:
    text = Path("scripts/review_employer_origin_activation_readiness.py").read_text(encoding="utf-8")

    assert "from psycopg.conninfo import make_conninfo" in text
    assert "def shared_database_dsn()" in text
    assert "make_conninfo(**get_database_config())" in text
    assert "load_database_evidence(shared_database_dsn())" in text
    assert "load_database_evidence(None)" not in text


def test_non_job_preview_records_detect_product_pages() -> None:
    job = raw_record(
        "Cloud Infrastructure DevOps Engineer",
        "https://www.enercity.de/karriere/jobsuche/cloud-infrastructure-devops-engineer-J1",
        ["cloud"],
    )
    product = raw_record(
        "Elektromobilität",
        "https://www.enercity.de/privatkunden/produkte/elektromobilitaet",
        ["data"],
    )

    assert is_probable_job_detail_record(job)
    assert not is_probable_job_detail_record(product)
    assert non_job_preview_records([job, product]) == [product]


def test_query_parameter_job_detail_reuses_s7n_safety_contract() -> None:
    origin_url = "https://karriere.example.com/de"
    job = raw_record(
        "Data Engineer (m/w/d)",
        "https://karriere.example.com/de?id=51980f",
        ["data"],
    )

    assert is_probable_job_detail_record(job, origin_url=origin_url)
    assert non_job_preview_records([job], origin_url=origin_url) == []


def test_query_parameter_job_detail_uses_trusted_record_evidence() -> None:
    origin_url = "https://karriere.example.com/de"
    url = "https://karriere.example.com/de?id=458ccb"
    job = RawJobRecord(
        source_name="example:discovery",
        source_url=url,
        external_job_id="de:example",
        raw_data={
            "job": {
                "title": "Details",
                "company_name": "Example GmbH",
                "location": "Deutschland",
                "source_url": url,
                "profile_terms": ["ai"],
            },
            "result_card": {
                "title": "Details",
                "company_name": "Example GmbH",
                "location": "Deutschland",
                "detail_url": url,
            },
            "detail_evidence": {
                "page_title": "Bid Manager (m/w/d) Enterprise Ausschreibungen",
            },
            "listing_evidence": {
                "listing_text": "Mehr erfahren",
            },
        },
    )

    assert candidate_from_raw_record(job).page_title == "Details"
    assert is_probable_job_detail_record(job, origin_url=origin_url)
    assert non_job_preview_records([job], origin_url=origin_url) == []


def test_query_parameter_job_detail_stays_blocked_with_only_generic_record_labels() -> None:
    origin_url = "https://karriere.example.com/de"
    url = "https://karriere.example.com/de?id=458ccb"
    generic = RawJobRecord(
        source_name="example:discovery",
        source_url=url,
        external_job_id="de:example",
        raw_data={
            "job": {"title": "Details"},
            "result_card": {"title": "Details"},
            "detail_evidence": {"page_title": "Karriere"},
            "listing_evidence": {"listing_text": "Mehr erfahren"},
        },
    )

    assert not is_probable_job_detail_record(generic, origin_url=origin_url)


def test_query_parameter_job_detail_fails_closed_without_trusted_origin() -> None:
    origin_url = "https://karriere.example.com/de"
    tracking = raw_record(
        "Data Engineer (m/w/d)",
        "https://karriere.example.com/de?utm_source=newsletter",
        ["data"],
    )
    unrelated = raw_record(
        "Data Engineer (m/w/d)",
        "https://jobs.example.net/de?id=51980f",
        ["data"],
    )
    generic = raw_record(
        "Details",
        "https://karriere.example.com/de?id=51980f",
        ["data"],
    )

    assert not is_probable_job_detail_record(tracking, origin_url=origin_url)
    assert not is_probable_job_detail_record(unrelated, origin_url=origin_url)
    assert not is_probable_job_detail_record(generic, origin_url=origin_url)


def test_overall_readiness_blocks_non_job_preview_records() -> None:
    assert (
        summarize_overall_readiness(
            final_approval_passed=True,
            active_profiles=[],
            rows=[],
            non_job_preview_count=1,
        )
        == "activation_readiness_blocked_non_job_preview_records"
    )


def waymo_query_record(job_id=8063637, title='Program Manager, Germany Regulatory'):
    # Actual connector structure: provider ID, ATS-supplied absolute_url, nested location,
    # original content and decoded description. Query URL is on the employer's domain.
    url = f'https://careers.withwaymo.com/jobs?gh_jid={job_id}'
    return RawJobRecord(source_name='greenhouse:waymo', external_job_id=str(job_id),
        source_url=url, raw_data={'board_token': 'waymo', 'job': {
            'id': job_id, 'title': title, 'absolute_url': url,
            'location': {'name': 'Munich, Bavaria, Germany'},
            'content': '<p>Coordinate regulatory deployment programs.</p>',
            'description': 'Coordinate regulatory deployment programs.'},
            'acquisition_scope': 'germany_metadata_only',
            'location_filter': {'decision': 'retained', 'reason': 'verified_germany'}})


def test_waymo_actual_query_preview_structures_are_evaluable():
    records = [waymo_query_record(i, t) for i, t in [
        (8063637, 'Program Manager, Germany Regulatory'),
        (8108104, 'Strategy & BizOps Lead, Germany'),
        (8109449, 'Emergency Services Liaison, Germany'),
        (7922569, 'Lead Diagnostic Technician')]]
    assert non_job_preview_records(records,
        origin_url='https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true') == []


def test_greenhouse_query_detail_identity_and_safety_fail_closed():
    from dataclasses import replace
    from copy import deepcopy
    origin = 'https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true'
    base = waymo_query_record()
    bad = [replace(base, external_job_id='999'), replace(base, source_name='other:waymo')]
    for key, value in [('id', 999), ('absolute_url', 'https://evil.example/jobs?gh_jid=8063637'),
                       ('title', 'Details'), ('description', ''), ('content', '')]:
        raw = deepcopy(base.raw_data)
        raw['job'][key] = value
        if key in {'description', 'content'}:
            raw['job']['description'] = raw['job']['content'] = ''
        bad.append(replace(base, raw_data=raw))
    for url in ['https://careers.withwaymo.com/jobs?gh_jid=999',
                'https://careers.withwaymo.com/jobs?gh_jid=8063637&redirect=https://evil.example',
                'https://careers.withwaymo.com/jobs?gh_jid=8063637&gh_jid=8063637',
                'http://careers.withwaymo.com/jobs?gh_jid=8063637',
                'https://careers.withwaymo.com/produkte/widget?gh_jid=8063637',
                'https://127.0.0.1/jobs?gh_jid=8063637']:
        raw = deepcopy(base.raw_data)
        raw['job']['absolute_url'] = url
        bad.append(replace(base, source_url=url, raw_data=raw))
    assert non_job_preview_records(bad, origin_url=origin) == bad
    assert non_job_preview_records([base], origin_url=origin.replace('/waymo/', '/other/')) == [base]
