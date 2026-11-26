from datetime import date

from src.career_intelligence.freshness import (
    AGING_PENALTY,
    OLD_PENALTY,
    apply_freshness_penalty,
    calculate_job_freshness,
)


REFERENCE_DAY = date(2026, 9, 4)


def test_freshness_buckets_use_publication_date_first():
    assert calculate_job_freshness(
        publication_date="2026-09-04",
        first_seen_at="2026-08-01T00:00:00+00:00",
        today=REFERENCE_DAY,
    ).bucket == "NEW"
    assert calculate_job_freshness(
        publication_date="2026-08-31",
        today=REFERENCE_DAY,
    ).bucket == "FRESH"
    assert calculate_job_freshness(
        publication_date="2026-08-24",
        today=REFERENCE_DAY,
    ).bucket == "AGING"
    assert calculate_job_freshness(
        publication_date="2026-08-20",
        today=REFERENCE_DAY,
    ).bucket == "OLD"


def test_first_seen_is_labelled_fallback_not_publication_date():
    freshness = calculate_job_freshness(
        publication_date=None,
        first_seen_at="2026-08-29T12:00:00+00:00",
        last_seen_at="2026-09-04T12:00:00+00:00",
        today=REFERENCE_DAY,
    )

    assert freshness.publication_date is None
    assert freshness.first_seen_at == "2026-08-29T12:00:00+00:00"
    assert freshness.last_seen_at == "2026-09-04T12:00:00+00:00"
    assert freshness.effective_date_source == "first_seen_fallback"
    assert freshness.bucket == "FRESH"


def test_missing_reliable_dates_remain_unknown_without_penalty():
    freshness = calculate_job_freshness(today=REFERENCE_DAY)

    assert freshness.bucket == "UNKNOWN"
    assert freshness.age_days is None
    assert freshness.effective_date is None
    assert freshness.ranking_penalty == 0


def test_jobs_older_than_seven_days_receive_ranking_penalty():
    aging = calculate_job_freshness(publication_date="2026-08-24", today=REFERENCE_DAY)
    old = calculate_job_freshness(publication_date="2026-08-01", today=REFERENCE_DAY)

    assert aging.ranking_penalty == AGING_PENALTY
    assert old.ranking_penalty == OLD_PENALTY
    assert apply_freshness_penalty({"opportunity_score": 80}, aging)[
        "opportunity_score"
    ] == 72
    assert apply_freshness_penalty({"opportunity_score": 80}, old)[
        "opportunity_score"
    ] == 65
