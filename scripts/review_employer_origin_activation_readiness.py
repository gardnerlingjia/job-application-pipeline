from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlparse

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from scripts.review_finanz_informatik_incremental_uniqueness import (
    Candidate,
    EvidenceRecord,
    UniquenessRow,
    build_uniqueness_rows,
    load_database_evidence,
    sha256_file,
)
from src.config import get_database_config
from src.connectors.base import RawJobRecord, SearchProfile, SearchTerm
from src.connectors.registry import create_connector
from src.search_intelligence.connector_feasibility_query_runtime import (
    _safe_query_job_detail_link as is_trusted_query_job_detail_link,
)


DEFAULT_EXPORT_DIR = Path("docs/planning/active/source-candidates")
DEFAULT_LOCATION = "Hannover"
DEFAULT_RADIUS_KM = 50
DEFAULT_OFFER_TYPE = 1
DEFAULT_PAGE_SIZE = 3

JOB_DETAIL_URL_PATH_MARKERS = (
    "/jobs/",
    "/job/",
    "/jobsuche/",
    "/karriere/jobsuche/",
    "/stellenangebote/",
    "/offene-stellen/",
    "/karriere/offene-stellen/",
    "/karriere/jobs/",
)

NON_JOB_URL_PATH_MARKERS = (
    "/privatkunden/",
    "/geschaeftskunden/",
    "/produkte/",
    "/produkt/",
    "/presse/",
    "/news/",
    "/blog/",
)


def shared_database_dsn() -> str:
    return make_conninfo(**get_database_config())


class ConnectorLike(Protocol):
    def fetch_jobs(
        self,
        profile: SearchProfile,
        search_term: SearchTerm,
    ) -> tuple[list[RawJobRecord], str]:
        ...


@dataclass(frozen=True)
class SourceCandidate:
    candidate_id: int
    company_key: str
    company_name: str
    source_name_candidate: str
    source_type_candidate: str
    status: str


@dataclass(frozen=True)
class ActiveProfile:
    profile_name: str
    source_name: str
    is_active: bool


@dataclass(frozen=True)
class ActivationReadinessRow:
    source_candidate_url: str
    page_title: str
    source_name: str
    external_job_id: str
    matched_profile_terms: str
    matched_location_terms: str
    best_match_table: str
    best_match_record_id: str
    best_match_source_name: str
    best_match_source_url: str
    best_match_title: str
    best_match_company_name: str
    best_match_location: str
    exact_url_match: bool
    title_similarity: float
    evidence_similarity: float
    uniqueness_decision: str
    readiness_decision: str
    reason: str


def trusted_query_detail_labels(record: RawJobRecord) -> tuple[str, ...]:
    raw_data = record.raw_data or {}
    containers = (
        raw_data.get("job"),
        raw_data.get("result_card"),
        raw_data.get("detail_evidence"),
        raw_data.get("listing_evidence"),
    )
    keys = ("title", "title", "page_title", "listing_text")
    labels: list[str] = []

    for container, key in zip(containers, keys, strict=True):
        if not isinstance(container, dict):
            continue
        label = str(container.get(key) or "").strip()
        if label and label not in labels:
            labels.append(label)

    return tuple(labels)


def is_greenhouse_query_detail_record(record: RawJobRecord, origin_url: str | None) -> bool:
    """Trust provider-bound query URLs, not arbitrary cross-domain discovery links."""
    from src.search_intelligence.connector_feasibility import (
        is_public_https_origin_url, KNOWN_AGGREGATOR_DOMAINS, SOCIAL_OR_EXTERNAL_NOISE_DOMAINS,
    )
    from src.search_intelligence.connector_feasibility_query_runtime import GENERIC_DETAIL_LABELS

    raw = record.raw_data or {}
    job = raw.get('job')
    token = raw.get('board_token')
    if not isinstance(job, dict) or not isinstance(token, str) or not token:
        return False
    origin = urlparse(origin_url or '')
    if (record.source_name != f'greenhouse:{token}' or origin.scheme != 'https'
            or origin.netloc != 'boards-api.greenhouse.io'
            or origin.path != f'/v1/boards/{token}/jobs'):
        return False
    url = record.source_url
    parsed = urlparse(url)
    if (not is_public_https_origin_url(url) or parsed.username or parsed.password
            or parsed.hostname in KNOWN_AGGREGATOR_DOMAINS | SOCIAL_OR_EXTERNAL_NOISE_DOMAINS
            or parsed.path.rstrip('/') != '/jobs' or parsed.fragment
            or job.get('absolute_url') != url):
        return False
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    identifier = str(job.get('id', ''))
    title = job.get('title')
    description = job.get('description') or job.get('content')
    return bool(
        identifier.isascii() and identifier.isdigit() and int(identifier) > 0
        and record.external_job_id == identifier and pairs == [('gh_jid', identifier)]
        and isinstance(title, str) and title.strip()
        and title.strip().casefold() not in GENERIC_DETAIL_LABELS
        and isinstance(description, str) and description.strip()
    )


def is_probable_job_detail_record(
    record: RawJobRecord,
    *,
    origin_url: str | None = None,
) -> bool:
    path = urlparse(record.source_url).path.lower()

    if any(marker in path for marker in NON_JOB_URL_PATH_MARKERS):
        return False

    if any(marker in path for marker in JOB_DETAIL_URL_PATH_MARKERS):
        return True

    if is_greenhouse_query_detail_record(record, origin_url):
        return True

    if not origin_url:
        return False

    return any(
        is_trusted_query_job_detail_link(origin_url, record.source_url, label)
        for label in trusted_query_detail_labels(record)
    )


def non_job_preview_records(
    records: list[RawJobRecord],
    *,
    origin_url: str | None = None,
) -> list[RawJobRecord]:
    return [
        record
        for record in records
        if not is_probable_job_detail_record(record, origin_url=origin_url)
    ]


def terms_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value if str(item).strip())
    return ""


def candidate_from_raw_record(record: RawJobRecord) -> Candidate:
    raw_data = record.raw_data or {}
    job = raw_data.get("job", {}) if isinstance(raw_data.get("job"), dict) else {}
    result_card = raw_data.get("result_card", {}) if isinstance(raw_data.get("result_card"), dict) else {}

    title = str(job.get("title") or result_card.get("title") or record.external_job_id or "").strip()
    location = str(job.get("location") or result_card.get("location") or "").strip()
    profile_terms = terms_to_text(job.get("profile_terms") or result_card.get("profile_terms"))

    return Candidate(
        source_candidate_url=record.source_url,
        page_title=title,
        recommendation="employer_origin_activation_readiness_record",
        matched_profile_terms=profile_terms,
        matched_location_terms=location,
    )


def classify_readiness(row: UniquenessRow) -> tuple[str, str]:
    if row.uniqueness_decision == "manual_review_db_unavailable":
        return (
            "activation_readiness_blocked_db_unavailable",
            "Activation readiness cannot be evaluated without current database evidence.",
        )

    if row.uniqueness_decision in {"known_exact_url_match", "likely_known_elsewhere"}:
        return (
            "activation_readiness_defer_known_elsewhere",
            "Candidate is already known or likely known elsewhere.",
        )

    if row.uniqueness_decision == "possible_known_elsewhere_review":
        return (
            "activation_readiness_manual_overlap_review",
            "Candidate has enough overlap with existing evidence to require manual duplicate review.",
        )

    if row.uniqueness_decision == "incrementally_unique_candidate":
        return (
            "activation_readiness_supported",
            "Candidate appears to add incremental source value compared with current raw/Silver evidence.",
        )

    return (
        "activation_readiness_manual_review",
        "Unexpected uniqueness decision; manual review required.",
    )


def readiness_rows_from_uniqueness(
    records: list[RawJobRecord],
    uniqueness_rows: list[UniquenessRow],
) -> list[ActivationReadinessRow]:
    records_by_url = {record.source_url: record for record in records}
    rows: list[ActivationReadinessRow] = []

    for unique_row in uniqueness_rows:
        record = records_by_url.get(unique_row.source_candidate_url)
        readiness_decision, readiness_reason = classify_readiness(unique_row)

        rows.append(
            ActivationReadinessRow(
                source_candidate_url=unique_row.source_candidate_url,
                page_title=unique_row.page_title,
                source_name=record.source_name if record else "",
                external_job_id=(record.external_job_id if record and record.external_job_id else ""),
                matched_profile_terms=unique_row.matched_profile_terms,
                matched_location_terms=unique_row.matched_location_terms,
                best_match_table=unique_row.best_match_table,
                best_match_record_id=unique_row.best_match_record_id,
                best_match_source_name=unique_row.best_match_source_name,
                best_match_source_url=unique_row.best_match_source_url,
                best_match_title=unique_row.best_match_title,
                best_match_company_name=unique_row.best_match_company_name,
                best_match_location=unique_row.best_match_location,
                exact_url_match=unique_row.exact_url_match,
                title_similarity=unique_row.title_similarity,
                evidence_similarity=unique_row.evidence_similarity,
                uniqueness_decision=unique_row.uniqueness_decision,
                readiness_decision=readiness_decision,
                reason=f"{unique_row.reason} Readiness interpretation: {readiness_reason}",
            )
        )

    return rows


def summarize_overall_readiness(
    *,
    final_approval_passed: bool,
    active_profiles: list[ActiveProfile],
    rows: list[ActivationReadinessRow],
    non_job_preview_count: int = 0,
) -> str:
    if not final_approval_passed:
        return "activation_readiness_blocked_missing_final_approval"

    if active_profiles:
        return "activation_readiness_blocked_already_active"

    if non_job_preview_count:
        return "activation_readiness_blocked_non_job_preview_records"

    if not rows:
        return "activation_readiness_blocked_no_preview_candidates"

    decisions = Counter(row.readiness_decision for row in rows)

    if decisions.get("activation_readiness_blocked_db_unavailable"):
        return "activation_readiness_blocked_db_unavailable"

    if decisions.get("activation_readiness_supported"):
        if decisions.get("activation_readiness_manual_overlap_review"):
            return "activation_readiness_supported_with_manual_overlap_review"
        return "activation_readiness_supported"

    if decisions.get("activation_readiness_manual_overlap_review"):
        return "manual_overlap_review_required_before_activation"

    if decisions.get("activation_readiness_defer_known_elsewhere") == len(rows):
        return "defer_activation_known_elsewhere"

    return "activation_readiness_manual_review"


def load_candidate(conn: psycopg.Connection[Any], *, candidate_id: int | None, company_key: str | None) -> SourceCandidate:
    with conn.cursor(row_factory=dict_row) as cur:
        if candidate_id is not None:
            cur.execute(
                """
                select id, company_key, company_name, source_name_candidate, source_type_candidate, status
                from employer_origin_source_candidates
                where id = %s
                """,
                (candidate_id,),
            )
        else:
            cur.execute(
                """
                select id, company_key, company_name, source_name_candidate, source_type_candidate, status
                from employer_origin_source_candidates
                where company_key = %s
                order by id desc
                limit 1
                """,
                (company_key,),
            )
        row = cur.fetchone()

    if row is None:
        raise ValueError("No employer-origin source candidate found.")

    return SourceCandidate(
        candidate_id=int(row["id"]),
        company_key=str(row["company_key"]),
        company_name=str(row["company_name"]),
        source_name_candidate=str(row["source_name_candidate"]),
        source_type_candidate=str(row["source_type_candidate"]),
        status=str(row["status"]),
    )


def final_approval_passed(conn: psycopg.Connection[Any], candidate_id: int) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select gate_status, decision
            from employer_origin_candidate_gate_reviews
            where candidate_id = %s
              and gate_name = 'final_approval_gate'
            order by updated_at desc
            limit 1
            """,
            (candidate_id,),
        )
        row = cur.fetchone()

    return bool(row and row["gate_status"] == "passed" and row["decision"] == "approve_connector_registration")


def load_active_profiles(conn: psycopg.Connection[Any], source_name: str) -> list[ActiveProfile]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select profile_name, source_name, is_active
            from search_profiles
            where source_name = %s
              and is_active = true
            order by profile_name
            """,
            (source_name,),
        )
        rows = cur.fetchall()

    return [
        ActiveProfile(
            profile_name=str(row["profile_name"]),
            source_name=str(row["source_name"]),
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]


def preview_connector_records(
    candidate: SourceCandidate,
    connector: ConnectorLike | None = None,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    profile_config: dict | None = None,
) -> tuple[list[RawJobRecord], str]:
    active_connector = connector or create_connector(candidate.source_name_candidate)

    profile = SearchProfile(
        id=0,
        profile_name=f"s7u_{candidate.company_key}_activation_readiness_preview",
        source_name=candidate.source_name_candidate,
        search_location=profile_config["search_location"] if profile_config else DEFAULT_LOCATION,
        search_radius_km=DEFAULT_RADIUS_KM,
        offer_type=DEFAULT_OFFER_TYPE,
        page_size=page_size,
    )

    records, url = active_connector.fetch_jobs(profile, SearchTerm(search_term="*"))
    if profile_config:
        from src.ingestion.post_fetch_filter import apply_multi_term_keyword_filter
        records = apply_multi_term_keyword_filter(records=records, search_terms=[
            SearchTerm(search_term=t) for t in profile_config['search_terms']])
    return records, url


def write_review(
    path: Path,
    *,
    candidate: SourceCandidate,
    requested_url: str,
    rows: list[ActivationReadinessRow],
    evidence_count: int,
    active_profiles: list[ActiveProfile],
    overall_readiness: str,
    non_job_records: list[RawJobRecord] | None = None,
) -> None:
    readiness_counts = Counter(row.readiness_decision for row in rows)
    uniqueness_counts = Counter(row.uniqueness_decision for row in rows)
    non_job_records = non_job_records or []
    non_job_preview_count = len(non_job_records)

    lines = [
        f"# S7U Employer-Origin Activation Readiness — {candidate.company_key}",
        "",
        "## Boundary",
        "",
        "This is a generic employer-origin activation readiness review.",
        "It does not create or activate search profiles, register connectors, write Bronze records or change scheduler configuration.",
        "",
        "Boundary flags:",
        "",
        "- `database_writes`: `false`",
        "- `search_profile_created`: `false`",
        "- `source_activation_allowed`: `false`",
        "- `bronze_persistence_allowed`: `false`",
        "- `recurring_ingestion_allowed`: `false`",
        "- `scheduler_change_allowed`: `false`",
        "- `csv_or_export_inputs_used`: `false`",
        "",
        "## Candidate",
        "",
        f"- company key: `{candidate.company_key}`",
        f"- company name: `{candidate.company_name}`",
        f"- source name: `{candidate.source_name_candidate}`",
        f"- source type: `{candidate.source_type_candidate}`",
        f"- status: `{candidate.status}`",
        "",
        "## Inputs",
        "",
        f"- connector preview requested URL: {requested_url}",
        f"- database evidence rows considered: {evidence_count}",
        f"- active search profiles for this source: {len(active_profiles)}",
        f"- non-job preview records: {non_job_preview_count}",
        "",
        "## Overall Readiness",
        "",
        f"- `{overall_readiness}`",
        "",
        "## Readiness Counts",
        "",
    ]

    for key in sorted(readiness_counts):
        lines.append(f"- {key}: {readiness_counts[key]}")

    lines += ["", "## Uniqueness Counts", ""]
    for key in sorted(uniqueness_counts):
        lines.append(f"- {key}: {uniqueness_counts[key]}")

    if non_job_records:
        lines += ["", "## Non-Job Preview Records", ""]
        for record in non_job_records:
            lines += [
                f"- `{record.source_url}`",
                "  - decision: activation readiness blocked until connector preview excludes non-job records",
            ]

    lines += ["", "## Candidate Results", ""]
    for row in rows:
        lines += [
            f"- `{row.readiness_decision}` — {row.page_title}",
            f"  - uniqueness decision: {row.uniqueness_decision}",
            f"  - url: {row.source_candidate_url}",
            f"  - external job id: {row.external_job_id or '-'}",
            f"  - profile terms: {row.matched_profile_terms or '-'}",
            f"  - location terms: {row.matched_location_terms or '-'}",
            f"  - best match: {row.best_match_table or '-'} {row.best_match_record_id or ''} {row.best_match_source_name or ''}".rstrip(),
            f"  - best match title: {row.best_match_title or '-'}",
            f"  - best match source url: {row.best_match_source_url or '-'}",
            f"  - title similarity: {row.title_similarity}",
            f"  - evidence similarity: {row.evidence_similarity}",
            f"  - reason: {row.reason}",
        ]

    lines += [
        "",
        "## Next Step",
        "",
        "A separate controlled activation migration may be prepared only if this readiness review is accepted.",
        "That later migration must explicitly create or activate a bounded search profile and remain separate from this review artifact.",
    ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_activation_readiness(
    *,
    conn: psycopg.Connection[Any],
    candidate_id: int | None,
    company_key: str | None,
    output_dir: Path,
    write: bool,
    connector: ConnectorLike | None = None,
    evidence_override: list[EvidenceRecord] | None = None,
    db_error_override: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    profile_config: dict | None = None,
) -> dict[str, Any]:
    candidate = load_candidate(conn, candidate_id=candidate_id, company_key=company_key)
    approved = final_approval_passed(conn, candidate.candidate_id)
    active_profiles = load_active_profiles(conn, candidate.source_name_candidate)

    if profile_config and candidate.source_name_candidate != profile_config['source_name']:
        raise ValueError('Controlled profile source does not match candidate')
    records, requested_url = preview_connector_records(
        candidate, connector=connector, page_size=page_size, profile_config=profile_config)
    non_job_records = non_job_preview_records(records, origin_url=requested_url)
    evaluable_records = [record for record in records if record not in non_job_records]
    candidates = [candidate_from_raw_record(record) for record in evaluable_records]

    if evidence_override is None:
        evidence, db_error = load_database_evidence(shared_database_dsn())
    else:
        evidence = evidence_override
        db_error = db_error_override

    if db_error:
        raise RuntimeError(
            "S7U activation readiness requires current database evidence. "
            f"Database evidence loading failed: {db_error}"
        )

    uniqueness_rows = build_uniqueness_rows(candidates, evidence, db_error=None)
    rows = readiness_rows_from_uniqueness(evaluable_records, uniqueness_rows)
    overall_readiness = summarize_overall_readiness(
        final_approval_passed=approved,
        active_profiles=active_profiles,
        rows=rows,
        non_job_preview_count=len(non_job_records),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    review_md = output_dir / f"{candidate.company_key}_controlled_activation_readiness.md"

    if write:
        write_review(
            review_md,
            candidate=candidate,
            requested_url=requested_url,
            rows=rows,
            evidence_count=len(evidence),
            active_profiles=active_profiles,
            overall_readiness=overall_readiness,
            non_job_records=non_job_records,
        )

    manifest = {
        "agent": "s7u_employer_origin_activation_readiness",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "company_key": candidate.company_key,
            "source_name_candidate": candidate.source_name_candidate,
            "source_type_candidate": candidate.source_type_candidate,
            "status": candidate.status,
        },
        "final_approval_passed": approved,
        "active_search_profile_count": len(active_profiles),
        "requested_url": requested_url,
        "candidate_count": len(records),
        "evaluable_candidate_count": len(evaluable_records),
        "non_job_preview_count": len(non_job_records),
        "non_job_preview_urls": [record.source_url for record in non_job_records],
        "evidence_count": len(evidence),
        "overall_readiness": overall_readiness,
        "readiness_counts": dict(Counter(row.readiness_decision for row in rows)),
        "uniqueness_counts": dict(Counter(row.uniqueness_decision for row in rows)),
        "boundary": {
            "database_writes": False,
            "search_profile_created": False,
            "source_activation_allowed": False,
            "bronze_persistence_allowed": False,
            "recurring_ingestion_allowed": False,
            "scheduler_change_allowed": False,
            "csv_or_export_inputs_used": False,
        },
        "output_files": {
            "review_md": str(review_md) if write else None,
        },
        "output_sha256": {
            "review_md": sha256_file(review_md) if write and review_md.exists() else None,
        },
    }

    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run generic employer-origin activation readiness review.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--candidate-id", type=int)
    selector.add_argument("--company-key")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    with psycopg.connect(**get_database_config()) as conn:
        manifest = run_activation_readiness(
            conn=conn,
            candidate_id=args.candidate_id,
            company_key=args.company_key,
            output_dir=args.output_dir,
            write=args.write,
            page_size=args.page_size,
        )

    print("S7U Employer-Origin Activation Readiness")
    print(f"overall_readiness: {manifest['overall_readiness']}")
    print(f"candidate_count: {manifest['candidate_count']}")
    print(f"active_search_profile_count: {manifest['active_search_profile_count']}")
    if args.write:
        print(f"wrote_review: {manifest['output_files']['review_md']}")
    if args.print_json:
        print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
