"""Adapt normalized Silver jobs into Career Intelligence assessment inputs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Iterable, Mapping

import psycopg
from psycopg.rows import dict_row

from src.career_intelligence.freshness import (
    JobFreshness,
    calculate_job_freshness,
    freshness_provenance,
)
from src.config import get_database_config


SOURCE_FILE_PREFIX = "silver"
SOURCE_FILE_VERSION = "career-intelligence-silver-source.v1"
PROVENANCE_SCHEMA_VERSION = 1
ATS_BACKED_EMPLOYER_ORIGIN_SOURCE_TYPE = "employer_origin_ats_backed_career_site"
ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY = "missing_ats_provider_identity"


@dataclass(frozen=True)
class SilverCareerInput:
    company: str
    title: str
    description: str
    description_quality: str
    freshness: JobFreshness
    source_file: str
    provenance: dict[str, Any]


class SilverAdaptationError(ValueError):
    def __init__(self, message: str, *, provenance: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.provenance = provenance


class SilverJobReadRepository:
    """Read-only view over normalized Silver jobs and their linked raw evidence."""

    def __init__(self) -> None:
        self.connection_config = get_database_config()

    def get_connection(self):
        return psycopg.connect(
            **self.connection_config,
            row_factory=dict_row,
        )

    def load_silver_jobs(
        self,
        *,
        limit: int = 100,
        source_patterns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        source_patterns = source_patterns or []
        filters: list[str] = []
        params: list[object] = []

        if source_patterns:
            source_clauses = []
            for pattern in source_patterns:
                if "%" in pattern:
                    source_clauses.append("s.source_name LIKE %s")
                else:
                    source_clauses.append("s.source_name = %s")
                params.append(pattern)
            filters.append("(" + " OR ".join(source_clauses) + ")")

        filter_sql = ""
        if filters:
            filter_sql = "WHERE " + " AND ".join(filters)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        s.id AS silver_job_id,
                        s.raw_job_id,
                        s.source_name,
                        s.external_job_id,
                        s.source_url,
                        s.title,
                        s.company_name,
                        s.city,
                        s.postal_code,
                        s.country,
                        s.publication_date,
                        COALESCE(l.first_seen_at, r.created_at) AS first_seen_at,
                        COALESCE(l.last_seen_at, r.fetched_at) AS last_seen_at,
                        s.canonical_source_type,
                        s.canonical_key_candidate,
                        r.raw_data
                    FROM silver_jobs s
                    JOIN raw_jobs r
                      ON r.id = s.raw_job_id
                    LEFT JOIN job_lifecycle l
                      ON l.source_name = s.source_name
                     AND l.external_job_id = s.external_job_id
                     AND s.external_job_id IS NOT NULL
                    {filter_sql}
                    ORDER BY s.id
                    LIMIT %s;
                    """,
                    (*params, limit),
                )
                return list(cur.fetchall())


def normalize_source_patterns(source_filter: str | None) -> list[str]:
    if not source_filter:
        return []
    value = source_filter.strip()
    if not value:
        return []
    if "%" in value or ":" in value:
        return [value]
    return [f"{value}:%"]


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _provider_text(value: object) -> str | None:
    if isinstance(value, Mapping):
        parts = [_provider_text(item) for item in value.values()]
        text = " ".join(part for part in parts if part)
        return text or None
    if isinstance(value, list):
        parts = [_provider_text(item) for item in value]
        text = " ".join(part for part in parts if part)
        return text or None
    return _clean_text(value)


def _nested(mapping: Mapping[str, Any], path: tuple[str, ...]) -> object:
    current: object = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


STRONG_DESCRIPTION_PATHS: tuple[tuple[str, ...], ...] = (
    ("job", "description"),
    ("job", "jobdescription"),
    ("job", "text"),
    ("job", "content"),
    ("detail_evidence", "description"),
    ("detail_evidence", "text"),
    ("source_specific", "description"),
    ("source_specific", "raw_description"),
)

WEAK_DESCRIPTION_PATHS: tuple[tuple[str, ...], ...] = (
    ("listing_evidence", "listing_text"),
    ("source_specific", "raw_card_text"),
)


def extract_description(raw_data: object) -> tuple[str | None, str | None, str]:
    if not isinstance(raw_data, Mapping):
        return None, None, "missing"

    for path in STRONG_DESCRIPTION_PATHS:
        value = _clean_text(_nested(raw_data, path))
        if value:
            return value, ".".join(path), "strong"

    for path in WEAK_DESCRIPTION_PATHS:
        value = _clean_text(_nested(raw_data, path))
        if value:
            return value, ".".join(path), "weak"

    return None, None, "missing"


def _source_family(source_name: object) -> str | None:
    if not isinstance(source_name, str) or ":" not in source_name:
        return None
    family, _ = source_name.split(":", 1)
    return family or None


def has_ats_backed_provider_identity(row: Mapping[str, Any]) -> bool:
    if row.get("canonical_source_type") != ATS_BACKED_EMPLOYER_ORIGIN_SOURCE_TYPE:
        return False

    source_family = _source_family(row.get("source_name"))
    if source_family not in {"greenhouse", "successfactors"}:
        return False

    raw_data = row.get("raw_data")
    if not isinstance(raw_data, Mapping):
        return False
    job_data = _nested(raw_data, ("job",))
    if not isinstance(job_data, Mapping):
        return False

    provider_job_id = _clean_text(row.get("external_job_id")) or _clean_text(
        job_data.get("id")
    )
    provider_url = (
        _clean_text(job_data.get("absolute_url"))
        or _clean_text(job_data.get("source_url"))
        or _clean_text(row.get("source_url"))
    )
    provider_context = (
        _provider_text(job_data.get("location"))
        or _provider_text(job_data.get("offices"))
        or _clean_text(job_data.get("first_published"))
        or _clean_text(job_data.get("updated_at"))
    )

    return bool(provider_job_id and provider_url and provider_context)


def stable_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    source_name = _clean_text(row.get("source_name"))
    external_job_id = _clean_text(row.get("external_job_id"))
    if source_name and external_job_id:
        return "source_name_external_job_id", f"{source_name}\0{external_job_id}"

    raw_job_id = row.get("raw_job_id")
    if isinstance(raw_job_id, int) and raw_job_id > 0:
        return "raw_job_id", str(raw_job_id)

    silver_job_id = row.get("silver_job_id")
    if isinstance(silver_job_id, int) and silver_job_id > 0:
        return "silver_job_id", str(silver_job_id)

    canonical_key = _clean_text(row.get("canonical_key_candidate"))
    if canonical_key:
        return "canonical_key_candidate", canonical_key

    title = _clean_text(row.get("title")) or ""
    company = _clean_text(row.get("company_name")) or ""
    location = _clean_text(row.get("city")) or ""
    return "deterministic_content_fallback", f"{company}\0{title}\0{location}"


def _slug(value: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (slug or "job")[:max_length].strip("-") or "job"


def source_file_for_row(row: Mapping[str, Any]) -> str:
    identity_type, identity_value = stable_identity(row)
    digest = sha256(
        f"{SOURCE_FILE_VERSION}\0{identity_type}\0{identity_value}".encode("utf-8")
    ).hexdigest()[:16]
    label = _clean_text(row.get("source_name")) or identity_type
    return f"{SOURCE_FILE_PREFIX}-{_slug(label)}-{digest}.json"


def silver_provenance(
    row: Mapping[str, Any],
    *,
    description_source: str | None,
    description_quality: str,
    ingestion_status: str,
) -> dict[str, Any]:
    identity_type, identity_value = stable_identity(row)
    source_file = source_file_for_row(row)
    freshness = calculate_job_freshness(
        publication_date=row.get("publication_date"),
        first_seen_at=row.get("first_seen_at"),
        last_seen_at=row.get("last_seen_at"),
    )
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_file": source_file,
        "ingestion_status": ingestion_status,
        "stable_identity_type": identity_type,
        "stable_identity_sha256": sha256(identity_value.encode("utf-8")).hexdigest(),
        "description_source": description_source,
        "description_quality": description_quality,
        "silver_job_id": row.get("silver_job_id"),
        "raw_job_id": row.get("raw_job_id"),
        "source_name": row.get("source_name"),
        "external_job_id": row.get("external_job_id"),
        "source_url": row.get("source_url"),
        "canonical_source_type": row.get("canonical_source_type"),
        "canonical_key_candidate": row.get("canonical_key_candidate"),
        **freshness_provenance(freshness),
    }


def adapt_silver_row(row: Mapping[str, Any]) -> SilverCareerInput:
    company = _clean_text(row.get("company_name"))
    title = _clean_text(row.get("title"))
    description, description_source, description_quality = extract_description(row.get("raw_data"))
    has_trusted_missing_description_identity = (
        description is None and has_ats_backed_provider_identity(row)
    )
    if has_trusted_missing_description_identity:
        description_quality = ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY
    freshness = calculate_job_freshness(
        publication_date=row.get("publication_date"),
        first_seen_at=row.get("first_seen_at"),
        last_seen_at=row.get("last_seen_at"),
    )
    base_provenance = silver_provenance(
        row,
        description_source=description_source,
        description_quality=description_quality,
        ingestion_status="skipped",
    )

    missing = [
        label
        for label, value in (
            ("company", company),
            ("title", title),
        )
        if not value
    ]
    if missing:
        raise SilverAdaptationError(
            f"missing or empty required fields: {', '.join(missing)}",
            provenance=base_provenance,
        )
    if not description and not has_trusted_missing_description_identity:
        raise SilverAdaptationError(
            "missing or empty required fields: description",
            provenance=base_provenance,
        )
    if description_quality not in {"strong", ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY}:
        raise SilverAdaptationError(
            "insufficient description evidence: weak listing/card text is not scored",
            provenance=base_provenance,
        )

    source_file = source_file_for_row(row)
    provenance = dict(base_provenance)
    provenance["ingestion_status"] = "assessed"

    assert company is not None
    assert title is not None
    return SilverCareerInput(
        company=company,
        title=title,
        description=description or "",
        description_quality=description_quality,
        freshness=freshness,
        source_file=source_file,
        provenance=provenance,
    )


def adapt_silver_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[SilverCareerInput], list[dict[str, Any]]]:
    inputs: list[SilverCareerInput] = []
    errors: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        try:
            if not isinstance(row, Mapping):
                raise ValueError("Silver row must be an object")
            inputs.append(adapt_silver_row(row))
        except Exception as exc:
            label = "unknown"
            if isinstance(row, Mapping):
                label = str(
                    row.get("silver_job_id")
                    or row.get("raw_job_id")
                    or row.get("source_url")
                    or "unknown"
                )
            error: dict[str, Any] = {
                "record": label,
                "index": str(index),
                "error": str(exc),
            }
            provenance = getattr(exc, "provenance", None)
            if isinstance(provenance, dict):
                error["provenance"] = provenance
            errors.append(error)

    return inputs, errors
