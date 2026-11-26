"""Freshness classification for Career Intelligence Silver opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Mapping


AGING_PENALTY = 8
OLD_PENALTY = 15


@dataclass(frozen=True)
class JobFreshness:
    publication_date: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    effective_date: str | None
    effective_date_source: str | None
    age_days: int | None
    bucket: str
    ranking_penalty: int


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def calculate_job_freshness(
    *,
    publication_date: object = None,
    first_seen_at: object = None,
    last_seen_at: object = None,
    today: date | None = None,
) -> JobFreshness:
    """Classify job age without fabricating a publication date."""

    today = today or datetime.now(UTC).date()
    published = _parse_date(publication_date)
    first_seen = _parse_date(first_seen_at)

    effective = published or first_seen
    source = None
    if published is not None:
        source = "publication_date"
    elif first_seen is not None:
        source = "first_seen_fallback"

    age_days: int | None = None
    bucket = "UNKNOWN"
    penalty = 0
    if effective is not None:
        age_days = max(0, (today - effective).days)
        if age_days <= 3:
            bucket = "NEW"
        elif age_days <= 7:
            bucket = "FRESH"
        elif age_days <= 14:
            bucket = "AGING"
            penalty = AGING_PENALTY
        else:
            bucket = "OLD"
            penalty = OLD_PENALTY

    return JobFreshness(
        publication_date=_iso(publication_date),
        first_seen_at=_iso(first_seen_at),
        last_seen_at=_iso(last_seen_at),
        effective_date=effective.isoformat() if effective is not None else None,
        effective_date_source=source,
        age_days=age_days,
        bucket=bucket,
        ranking_penalty=penalty,
    )


def apply_freshness_penalty(
    assessment: Mapping[str, Any],
    freshness: JobFreshness,
) -> dict[str, Any]:
    """Return an assessment copy with only the CI ranking score adjusted."""

    adjusted = dict(assessment)
    score = adjusted.get("opportunity_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        adjusted["opportunity_score"] = max(0, int(round(score)) - freshness.ranking_penalty)
    return adjusted


def freshness_provenance(freshness: JobFreshness) -> dict[str, Any]:
    return {
        "publication_date": freshness.publication_date,
        "first_seen_at": freshness.first_seen_at,
        "last_seen_at": freshness.last_seen_at,
        "freshness_bucket": freshness.bucket,
        "job_age_days": freshness.age_days,
        "job_age_date_source": freshness.effective_date_source,
        "effective_age_date": freshness.effective_date,
        "freshness_ranking_penalty": freshness.ranking_penalty,
    }


__all__ = [
    "AGING_PENALTY",
    "OLD_PENALTY",
    "JobFreshness",
    "apply_freshness_penalty",
    "calculate_job_freshness",
    "freshness_provenance",
]
