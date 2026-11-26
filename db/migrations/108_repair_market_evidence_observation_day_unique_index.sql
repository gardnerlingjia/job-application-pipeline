-- V2.3 local fresh-init repair: preserve market_evidence day-level uniqueness
-- with an immutable timestamptz expression.
--
-- Migration 026 originally used source_seen_at::date / observed_at::date, which
-- is not immutable for timestamptz because it depends on the session time zone.
-- A temporary local repair used raw timestamptz coalescing, but that widened the
-- uniqueness grain from one observation per day to one observation per instant.
-- This forward migration restores the intended per-day uniqueness using UTC.

DROP INDEX IF EXISTS idx_market_evidence_observation_unique;

CREATE UNIQUE INDEX idx_market_evidence_observation_unique
    ON market_evidence (
        lower(source_name),
        normalized_company_key,
        lower(title),
        coalesce(evidence_url, ''),
        ((coalesce(source_seen_at, observed_at) AT TIME ZONE 'UTC')::date)
    );
