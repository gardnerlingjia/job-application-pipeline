"""Broad market discovery orchestration for Career Intelligence V2.4."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence

import psycopg
from psycopg.rows import dict_row
import yaml

from src import ingest_jobs, run_silver_jobs
from src.career_intelligence.adaptive_sources import load_adaptive_source_read_model
from src.career_intelligence.daily import run_daily as run_career_daily
from src.career_intelligence.discovery_detail_enrichment import (
    enrich_weak_discovery_rows,
    summarize_enrichment,
)
from src.career_intelligence.moia_live_source import (
    MIGRATION_COMMAND,
    START_DATABASE_COMMAND,
    OperationalBlocker,
    connect_database,
    ensure_required_schema,
    missing_required_schema_tables,
)
from src.ingestion.repository import JobIngestionRepository


DEFAULT_MARKET_DISCOVERY_CONFIG_PATH = Path("config/career_market_discovery.yaml")
SCHEMA_VERSION = "career_intelligence.market_discovery.v1"
DEFAULT_LIMIT = 100
IMPLEMENTATION_STATUSES = {
    "LIVE",
    "SUPPORTED_UNCONFIGURED",
    "BLOCKED_AUTH",
    "BLOCKED_ANTI_BOT",
    "BLOCKED_NO_API",
    "BLOCKED_NO_SUPPORTED_CONNECTOR",
    "CONNECTOR_GAP",
    "NOT_EVALUATED",
}


@dataclass(frozen=True)
class MarketDiscoverySource:
    display_name: str
    source_name: str
    source_role: str
    strategy_tier: str
    career_priority: int
    implementation_status: str
    active: bool
    profile_prefix: str | None
    blocker: str | None


@dataclass(frozen=True)
class MarketDiscoveryProfile:
    key: str
    label: str
    career_lanes: tuple[str, ...]
    preferred_evidence_type: str
    search_terms: tuple[str, ...]


@dataclass(frozen=True)
class MarketDiscoveryConfig:
    sources: tuple[MarketDiscoverySource, ...]
    profiles: tuple[MarketDiscoveryProfile, ...]

    @property
    def active_sources(self) -> tuple[MarketDiscoverySource, ...]:
        return tuple(source for source in self.sources if source.active)

    def configured_profile_names(self) -> list[str]:
        return [
            f"{source.profile_prefix}_{profile.key}"
            for source in self.active_sources
            if source.profile_prefix
            for profile in self.profiles
        ]


@dataclass(frozen=True)
class IngestionProfileResult:
    profile_name: str
    source_name: str
    loaded: int
    inserted: int
    duplicate: int
    status: str
    error: str | None = None


class MarketDiscoveryOperations(Protocol):
    def doctor(self, config: MarketDiscoveryConfig) -> tuple[bool, list[str], str]:
        ...

    def run_ingestion_profile(self, profile_name: str) -> IngestionProfileResult:
        ...

    def run_silver(self, source_name: str, *, limit: int) -> int:
        ...

    def enrich_details(self, source_name: str, *, limit: int) -> Mapping[str, int]:
        ...

    def run_career_intelligence(self, source_name: str, *, limit: int) -> tuple[int, list[str]]:
        ...

    def adaptive_summary(self) -> Mapping[str, Any]:
        ...


def _text(value: object) -> str:
    return str(value or "").strip()


def _string_list(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = payload.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"market discovery profile missing {key}")
    result = tuple(_text(value) for value in values if _text(value))
    if not result:
        raise ValueError(f"market discovery profile has empty {key}")
    return result


def _source_from_mapping(payload: Mapping[str, Any]) -> MarketDiscoverySource:
    try:
        career_priority = int(payload.get("career_priority") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("market discovery source has invalid career_priority") from exc
    source = MarketDiscoverySource(
        display_name=_text(payload.get("display_name") or payload.get("source_name")),
        source_name=_text(payload.get("source_name")),
        source_role=_text(payload.get("source_role")),
        strategy_tier=_text(payload.get("strategy_tier")),
        career_priority=career_priority,
        implementation_status=_text(payload.get("implementation_status")),
        active=bool(payload.get("active")),
        profile_prefix=_text(payload.get("profile_prefix")) or None,
        blocker=_text(payload.get("blocker")) or None,
    )
    if not source.source_name:
        raise ValueError("market discovery source missing source_name")
    if source.active and not source.profile_prefix:
        raise ValueError("active market discovery source missing profile_prefix")
    if source.source_role != "discovery":
        raise ValueError(f"market discovery source {source.source_name} must be discovery")
    if source.strategy_tier != "C":
        raise ValueError(f"market discovery source {source.source_name} must be Tier C")
    if source.career_priority <= 0:
        raise ValueError(f"market discovery source {source.source_name} priority must be positive")
    if source.implementation_status not in IMPLEMENTATION_STATUSES:
        raise ValueError(
            f"market discovery source {source.source_name} has invalid implementation_status"
        )
    return source


def _profile_from_mapping(payload: Mapping[str, Any]) -> MarketDiscoveryProfile:
    profile = MarketDiscoveryProfile(
        key=_text(payload.get("key")),
        label=_text(payload.get("label")),
        career_lanes=_string_list(payload, "career_lanes"),
        preferred_evidence_type=_text(payload.get("preferred_evidence_type")),
        search_terms=_string_list(payload, "search_terms"),
    )
    if not profile.key or not profile.label:
        raise ValueError("market discovery profile missing key/label")
    if profile.preferred_evidence_type != "discovery_signal":
        raise ValueError(f"market discovery profile {profile.key} must use discovery_signal")
    return profile


def load_market_discovery_config(
    path: Path = DEFAULT_MARKET_DISCOVERY_CONFIG_PATH,
) -> MarketDiscoveryConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("market discovery config must be a YAML mapping")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported market discovery config schema version")
    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, Mapping):
        raise ValueError("market discovery config missing source_policy")
    source_rows = source_policy.get("sources")
    profile_rows = payload.get("profiles")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("market discovery config must contain sources")
    if not isinstance(profile_rows, list) or not 4 <= len(profile_rows) <= 6:
        raise ValueError("market discovery config must contain 4-6 broad profiles")
    sources = tuple(_source_from_mapping(row) for row in source_rows if isinstance(row, Mapping))
    profiles = tuple(_profile_from_mapping(row) for row in profile_rows if isinstance(row, Mapping))
    if len(sources) != len(source_rows) or len(profiles) != len(profile_rows):
        raise ValueError("market discovery config contains malformed records")
    priorities = [source.career_priority for source in sources]
    if sorted(priorities) != list(range(1, len(priorities) + 1)):
        raise ValueError("market discovery source career_priority values must be contiguous")
    return MarketDiscoveryConfig(
        sources=tuple(sorted(sources, key=lambda item: item.career_priority)),
        profiles=profiles,
    )


class DatabaseMarketDiscoveryOperations:
    def __init__(self, *, results: Path = Path("jobs/results")) -> None:
        self.results = results

    def doctor(self, config: MarketDiscoveryConfig) -> tuple[bool, list[str], str]:
        source_lines: list[str] = []
        try:
            with connect_database() as conn:
                missing = missing_required_schema_tables(conn)
                if missing:
                    return (
                        False,
                        ["BLOCKED: Schema not initialized: " + ", ".join(missing)],
                        MIGRATION_COMMAND,
                    )
                ensure_required_schema(conn)
                from src.career_intelligence.discovery_profile_sync import (
                    build_plan, desired_profiles, read_profiles,
                )
                plan = build_plan(config, read_profiles(conn, desired_profiles(config)))
                if plan["blockers"] or plan["differences"]:
                    return False, ["BLOCKED: database search intent differs from YAML; "
                                   "review the synchronization plan"], (
                        "python -m src.career_intelligence.discovery_profile_sync"
                    )
                active = self._active_configured_profiles(conn, config)
                expected = set(config.configured_profile_names())
                missing_profiles = sorted(expected - active)
                source_lines = self._source_status_lines(conn, config, active_profiles=active)
                if missing_profiles:
                    return (
                        False,
                        source_lines + [
                            "BLOCKED: broad discovery profiles missing/inactive: "
                            + ", ".join(missing_profiles)
                            + "; activation requires the existing approval workflow"
                        ],
                        "python -m src.career_intelligence.discovery_profile_sync",
                    )
        except OperationalBlocker as exc:
            return False, [f"BLOCKED: {exc}"], exc.next_command or START_DATABASE_COMMAND
        except psycopg.Error:
            return (
                False,
                [f"BLOCKED: Database unavailable. Start with: {START_DATABASE_COMMAND}"],
                START_DATABASE_COMMAND,
            )
        return True, source_lines + ["PASS: broad market discovery is ready"], (
            "python -m src.career_intelligence.market_discovery run-daily"
        )

    def _active_configured_profiles(
        self,
        conn: psycopg.Connection[Any],
        config: MarketDiscoveryConfig,
    ) -> set[str]:
        expected = config.configured_profile_names()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT sp.profile_name
                FROM search_profiles sp
                JOIN search_terms st
                  ON st.search_profile_id = sp.id
                WHERE sp.profile_name = ANY(%s)
                  AND sp.is_active = TRUE
                  AND sp.recurring_ingestion_enabled = TRUE
                  AND st.is_active = TRUE
                GROUP BY sp.profile_name
                HAVING count(st.id) > 0;
                """,
                (expected,),
            )
            return {str(row["profile_name"]) for row in cur.fetchall()}

    def _source_status_lines(
        self,
        conn: psycopg.Connection[Any],
        config: MarketDiscoveryConfig,
        *,
        active_profiles: set[str],
    ) -> list[str]:
        lines = ["Source priority status:"]
        with conn.cursor(row_factory=dict_row) as cur:
            for source in config.sources:
                live_fetch_verified = False
                if source.active:
                    cur.execute(
                        """
                        SELECT 1
                        FROM ingestion_runs
                        WHERE source_name = %s
                          AND status = 'success'
                          AND total_loaded > 0
                        LIMIT 1;
                        """,
                        (source.source_name,),
                    )
                    live_fetch_verified = cur.fetchone() is not None
                expected_profiles = {
                    f"{source.profile_prefix}_{profile.key}"
                    for profile in config.profiles
                    if source.active and source.profile_prefix
                }
                profiles_ready = bool(expected_profiles) and expected_profiles <= active_profiles
                status = (
                    "LIVE"
                    if profiles_ready and live_fetch_verified
                    else source.implementation_status
                )
                blocker = source.blocker or (
                    None
                    if live_fetch_verified or not source.active
                    else "no successful nonempty live fetch recorded yet"
                )
                line = (
                    f"- {source.display_name}: career_priority={source.career_priority} "
                    f"implementation_status={status} "
                    f"live_fetch_verified={str(live_fetch_verified).lower()}"
                )
                if blocker:
                    line += f" blocker={blocker}"
                lines.append(line)
        return lines

    def _latest_run_for_profile(self, profile_name: str) -> dict[str, Any] | None:
        with connect_database() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT ir.source_name, ir.total_loaded, ir.inserted_count,
                           ir.duplicate_count, ir.status, ir.error_message
                    FROM ingestion_runs ir
                    JOIN search_profiles sp
                      ON sp.id = ir.search_profile_id
                    WHERE sp.profile_name = %s
                    ORDER BY ir.started_at DESC, ir.id DESC
                    LIMIT 1;
                    """,
                    (profile_name,),
                )
                row = cur.fetchone()
        return dict(row) if row is not None else None

    def run_ingestion_profile(self, profile_name: str) -> IngestionProfileResult:
        repository = JobIngestionRepository()
        profiles = ingest_jobs.select_profiles(
            repository=repository,
            profile_name=profile_name,
            source_filter=None,
            role_filter=None,
        )
        profile = profiles[0]
        try:
            ingest_jobs.run_profile(repository=repository, profile=profile)
        except Exception as exc:
            latest = self._latest_run_for_profile(profile_name) or {}
            return IngestionProfileResult(
                profile_name=profile_name,
                source_name=profile.source_name,
                loaded=int(latest.get("total_loaded") or 0),
                inserted=int(latest.get("inserted_count") or 0),
                duplicate=int(latest.get("duplicate_count") or 0),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        latest = self._latest_run_for_profile(profile_name) or {}
        return IngestionProfileResult(
            profile_name=profile_name,
            source_name=profile.source_name,
            loaded=int(latest.get("total_loaded") or 0),
            inserted=int(latest.get("inserted_count") or 0),
            duplicate=int(latest.get("duplicate_count") or 0),
            status=str(latest.get("status") or "finished"),
            error=None,
        )

    def run_silver(self, source_name: str, *, limit: int) -> int:
        return _call_cli_main(
            run_silver_jobs.main,
            ["--source", source_name, "--limit", str(limit)],
        )

    def enrich_details(self, source_name: str, *, limit: int) -> Mapping[str, int]:
        results = enrich_weak_discovery_rows(source=source_name, limit=limit)
        return summarize_enrichment(results)

    def run_career_intelligence(self, source_name: str, *, limit: int) -> tuple[int, list[str]]:
        exit_status, lines, _path = run_career_daily(
            results=self.results,
            limit=limit,
            source=source_name,
        )
        return exit_status, lines

    def adaptive_summary(self) -> Mapping[str, Any]:
        return load_adaptive_source_read_model(results=self.results).get("summary", {})


def _call_cli_main(func, argv: list[str]) -> int:
    try:
        result = func(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    return int(result or 0)


def _configured_profile_sources(config: MarketDiscoveryConfig) -> dict[str, str]:
    return {
        f"{source.profile_prefix}_{profile.key}": source.source_name
        for source in config.active_sources
        if source.profile_prefix
        for profile in config.profiles
    }


def run_market_discovery(
    *,
    config_path: Path = DEFAULT_MARKET_DISCOVERY_CONFIG_PATH,
    results: Path = Path("jobs/results"),
    limit: int = DEFAULT_LIMIT,
    operations: MarketDiscoveryOperations | None = None,
) -> tuple[int, list[str]]:
    config = load_market_discovery_config(config_path)
    operations = operations or DatabaseMarketDiscoveryOperations(results=results)
    ready, doctor_lines, next_command = operations.doctor(config)
    if not ready:
        return 2, [
            "Career Intelligence broad market discovery",
            *doctor_lines,
            f"Next: {next_command}",
            "Exit status: 2",
        ]

    profile_sources = _configured_profile_sources(config)
    ingestion_results: list[IngestionProfileResult] = []
    errors: list[str] = []
    for profile_name in sorted(profile_sources):
        try:
            result = operations.run_ingestion_profile(profile_name)
        except Exception as exc:
            result = IngestionProfileResult(
                profile_name=profile_name,
                source_name=profile_sources[profile_name],
                loaded=0,
                inserted=0,
                duplicate=0,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        ingestion_results.append(result)
        if result.error:
            errors.append(f"{result.profile_name}: {result.error}")

    silver_failures: list[str] = []
    enrichment_failures: list[str] = []
    enrichment_summary = {"enriched": 0, "needs_detail": 0, "failed": 0}
    career_failures: list[str] = []
    career_summary_lines: dict[str, str] = {}
    career_summary_prefixes = (
        "Silver jobs loaded:",
        "Converted:",
        "Newly assessed:",
        "Already known/skipped:",
        "Errors:",
        "APPLY_NOW:",
        "NETWORK_FIRST:",
        "EXPLORE:",
        "WATCH:",
        "SKIP:",
        "NEW:",
        "INTERESTED:",
        "REVIEWED:",
        "DISMISSED:",
    )
    for source_name in sorted({source.source_name for source in config.active_sources}):
        silver_exit = operations.run_silver(source_name, limit=limit)
        if silver_exit:
            silver_failures.append(f"{source_name}: exit {silver_exit}")
        try:
            detail_counts = operations.enrich_details(source_name, limit=limit)
            for key in enrichment_summary:
                enrichment_summary[key] += int(detail_counts.get(key) or 0)
        except Exception as exc:
            enrichment_failures.append(f"{source_name}: {type(exc).__name__}: {exc}")
        career_exit, lines = operations.run_career_intelligence(source_name, limit=limit)
        for line in lines:
            for prefix in career_summary_prefixes:
                if line.startswith(prefix):
                    career_summary_lines[prefix] = line
        if career_exit:
            career_failures.append(f"{source_name}: exit {career_exit}")

    adaptive = operations.adaptive_summary()
    exit_status = 1 if errors or silver_failures or career_failures else 0
    if enrichment_failures:
        exit_status = 1
    lines = [
        "Career Intelligence broad market discovery",
        f"Started: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"Discovery sources configured: {len(config.sources)}",
        f"Sources attempted: {len(config.active_sources)}",
        f"Profiles attempted: {len(ingestion_results)}",
        f"Bronze jobs loaded: {sum(item.loaded for item in ingestion_results)}",
        f"Bronze jobs inserted: {sum(item.inserted for item in ingestion_results)}",
        f"Bronze duplicates/skipped existing: {sum(item.duplicate for item in ingestion_results)}",
        f"Ingestion profile errors: {len(errors)}",
        f"Silver source errors: {len(silver_failures)}",
        f"Discovery detail enriched: {enrichment_summary['enriched']}",
        f"Discovery detail needs detail: {enrichment_summary['needs_detail']}",
        f"Discovery detail errors: {enrichment_summary['failed'] + len(enrichment_failures)}",
        f"Career Intelligence source errors: {len(career_failures)}",
    ]
    for prefix in career_summary_prefixes:
        if prefix in career_summary_lines:
            lines.append(career_summary_lines[prefix])
    lines.extend(
        [
            f"Adaptive source candidates: {int(adaptive.get('candidate_count') or 0)}",
            (
                "Boundary: discovery sources remain sensors; "
                "employer-origin evidence remains preferred"
            ),
        ]
    )
    if errors:
        lines.append("Ingestion errors:")
        lines.extend(f"- {error}" for error in errors)
    if silver_failures:
        lines.append("Silver errors:")
        lines.extend(f"- {error}" for error in silver_failures)
    if enrichment_failures:
        lines.append("Discovery detail errors:")
        lines.extend(f"- {error}" for error in enrichment_failures)
    if career_failures:
        lines.append("Career Intelligence errors:")
        lines.extend(f"- {error}" for error in career_failures)
    lines.append(f"Exit status: {exit_status}")
    return exit_status, lines


def run_doctor(
    *,
    config_path: Path = DEFAULT_MARKET_DISCOVERY_CONFIG_PATH,
    operations: MarketDiscoveryOperations | None = None,
) -> tuple[int, list[str]]:
    config = load_market_discovery_config(config_path)
    operations = operations or DatabaseMarketDiscoveryOperations()
    ready, lines, next_command = operations.doctor(config)
    status = 0 if ready else 2
    return status, [
        "Career Intelligence broad market discovery doctor",
        *lines,
        "Configured active sources: "
        + ", ".join(source.source_name for source in config.active_sources),
        f"Broad profiles: {len(config.profiles)}",
        f"Next: {next_command}",
        f"Exit status: {status}",
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Lingjia's broad-market Career Intelligence discovery flow."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run-daily"):
        sub = subcommands.add_parser(name)
        sub.add_argument("--config", type=Path, default=DEFAULT_MARKET_DISCOVERY_CONFIG_PATH)
        if name == "run-daily":
            sub.add_argument("--results", type=Path, default=Path("jobs/results"))
            sub.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "doctor":
        exit_status, lines = run_doctor(config_path=args.config)
    else:
        exit_status, lines = run_market_discovery(
            config_path=args.config,
            results=args.results,
            limit=args.limit,
        )
    for line in lines:
        print(line)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
