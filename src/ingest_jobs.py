from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from collections.abc import Sequence

from src.connectors.base import SearchProfile
from src.connectors.registry import SourceRole
from src.connectors.registry import create_connector as registry_create_connector
from src.connectors.registry import source_role as registry_source_role
from src.ingestion.repository import JobIngestionRepository
from src.ingestion.runner import JobIngestionRunner
from src.job_lifecycle_health import JobLifecycleHealthRepository


INGESTION_EXECUTION_APPLICATION_PREFIX = "job-pipeline-ingest:"


def create_connector(source_name: str):
    return registry_create_connector(source_name)


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level),
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_ingestion_execution_application_name() -> str:
    """Bind one opaque correlation ID to all DB connections in this invocation.

    libpq consumes ``PGAPPNAME`` when an explicit ``application_name`` connection
    parameter is absent. Migration 096 uses only the canonical prefix below, so
    unrelated processes cannot accidentally acquire ingestion execution lineage.
    """

    execution_id = str(uuid.uuid4())
    os.environ["PGAPPNAME"] = f"{INGESTION_EXECUTION_APPLICATION_PREFIX}{execution_id}"
    return execution_id


def source_matches(source_name: str, source_filter: str) -> bool:
    return source_name == source_filter or source_name.startswith(f"{source_filter}:")


def source_family(source_name: str) -> str:
    return source_name.split(":", 1)[0]


def profile_source_role(profile: SearchProfile) -> SourceRole:
    try:
        return registry_source_role(profile.source_name)
    except ValueError as exc:
        raise ValueError(
            "Active search profile has no registered source role: "
            f"profile={profile.profile_name!r} source={profile.source_name!r}"
        ) from exc


def format_available_profiles(profiles: Sequence[SearchProfile]) -> str:
    if not profiles:
        return "No active profiles are available."

    source_filters = sorted(
        {profile.source_name for profile in profiles}
        | {source_family(profile.source_name) for profile in profiles}
    )

    lines = ["Available active profiles:"]

    for profile in profiles:
        try:
            role = profile_source_role(profile).value
        except ValueError:
            role = "unclassified"
        lines.append(
            f"- {profile.profile_name} "
            f"(source={profile.source_name}, family={source_family(profile.source_name)}, "
            f"role={role})"
        )

    lines.append("")
    lines.append("Available source filters:")

    for source_filter in source_filters:
        lines.append(f"- {source_filter}")

    return "\n".join(lines)


def load_recurring_profile_names(
    repository: JobIngestionRepository,
    profiles: Sequence[SearchProfile],
) -> set[str]:
    """Return active profiles eligible for unscoped/source-family ingestion.

    Exact explicit profile execution intentionally bypasses this selector. Test
    doubles can provide ``load_recurring_search_profile_names``; the production
    repository is queried directly so this safety boundary does not require a
    broader repository API change.
    """

    loader = getattr(repository, "load_recurring_search_profile_names", None)
    if callable(loader):
        return {str(value) for value in loader()}

    connection_factory = getattr(repository, "get_connection", None)
    if connection_factory is None:
        # Lightweight test doubles predating the recurring-ingestion boundary.
        return {profile.profile_name for profile in profiles}

    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT profile_name
                FROM search_profiles
                WHERE is_active = TRUE
                  AND recurring_ingestion_enabled = TRUE
                ORDER BY source_name, profile_name;
                """
            )
            return {str(row[0]) for row in cur.fetchall()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run job ingestion for recurring-enabled active profiles, a source "
            "family, one source role, or one exact active profile."
        )
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--profile",
        help=(
            "Run exactly one active search profile by profile name, including "
            "controlled profiles with recurring ingestion disabled."
        ),
    )
    mode.add_argument(
        "--source",
        help=(
            "Run recurring-enabled active profiles for one source family, "
            "e.g. greenhouse."
        ),
    )
    mode.add_argument(
        "--role",
        choices=[role.value for role in SourceRole],
        help=(
            "Run recurring-enabled active profiles for one registered source role. "
            "Use employer_origin for authoritative employer connectors or sensor "
            "for market-observation sources."
        ),
    )
    mode.add_argument(
        "--list-profiles",
        action="store_true",
        help="List active search profiles and terms without running ingestion.",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="WARNING",
        help="Logging level for ingestion diagnostics.",
    )

    parser.add_argument(
        "legacy_profile_name",
        nargs="?",
        help=argparse.SUPPRESS,
    )

    return parser


def normalize_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> argparse.Namespace:
    if args.legacy_profile_name:
        if args.profile or args.source or args.role or args.list_profiles:
            parser.error(
                "Do not combine positional profile names with --profile, --source, "
                "--role or --list-profiles."
            )

        args.profile = args.legacy_profile_name

    return args


def select_profiles(
    repository: JobIngestionRepository,
    profile_name: str | None,
    source_filter: str | None,
    role_filter: SourceRole | None = None,
) -> list[SearchProfile]:
    profiles = repository.load_active_search_profiles()

    # An exact profile name is an explicit one-shot/manual execution boundary.
    # It may intentionally select an active controlled profile whose recurring
    # ingestion flag is false.
    if profile_name:
        selected_profiles = [
            profile
            for profile in profiles
            if profile.profile_name == profile_name
        ]

        if selected_profiles:
            return selected_profiles

        raise ValueError(
            f"No active search profile found: {profile_name}\n\n"
            f"{format_available_profiles(profiles)}"
        )

    recurring_names = load_recurring_profile_names(repository, profiles)
    recurring_profiles = [
        profile for profile in profiles if profile.profile_name in recurring_names
    ]

    if source_filter:
        selected_profiles = [
            profile
            for profile in recurring_profiles
            if source_matches(
                source_name=profile.source_name,
                source_filter=source_filter,
            )
        ]

        if selected_profiles:
            return selected_profiles

        raise ValueError(
            f"No recurring-enabled active search profiles found for source: {source_filter}\n\n"
            f"{format_available_profiles(recurring_profiles)}"
        )

    if role_filter is not None:
        selected_profiles = [
            profile
            for profile in recurring_profiles
            if profile_source_role(profile) == role_filter
        ]
        if selected_profiles:
            return selected_profiles
        raise ValueError(
            "No recurring-enabled active search profiles found for role: "
            f"{role_filter.value}\n\n{format_available_profiles(recurring_profiles)}"
        )

    if not recurring_profiles:
        raise ValueError("No recurring-enabled active search profiles found.")

    return recurring_profiles


def print_profiles(repository: JobIngestionRepository) -> None:
    profiles = repository.load_active_search_profiles()
    recurring_names = load_recurring_profile_names(repository, profiles)

    print()
    print("=== Active Search Profiles ===")
    print()

    for profile in profiles:
        recurring = "yes" if profile.profile_name in recurring_names else "no"
        try:
            role = profile_source_role(profile).value
        except ValueError:
            role = "unclassified"
        print(
            f"[{profile.id}] {profile.profile_name} "
            f"source={profile.source_name} "
            f"role={role} "
            f"location={profile.search_location} "
            f"radius_km={profile.search_radius_km} "
            f"recurring={recurring}"
        )

        terms = repository.load_active_search_terms(profile.profile_name)

        if not terms:
            print("    - no active search terms")
            continue

        for _, search_term in terms:
            term_id = search_term.id if search_term.id is not None else "?"
            print(f"    - [{term_id}] {search_term.search_term}")


def run_profile(
    repository: JobIngestionRepository,
    profile: SearchProfile,
    *,
    recurring_health_enabled: bool = False,
) -> None:
    from src.career_intelligence.discovery_profile_sync import assert_profile_intent

    assert_profile_intent(repository, profile)
    connector = create_connector(source_name=profile.source_name)

    health_repository = None
    if (
        recurring_health_enabled
        and profile_source_role(profile) == SourceRole.EMPLOYER_ORIGIN
        and connector.capabilities.supports_full_fetch
    ):
        health_repository = JobLifecycleHealthRepository()

    runner = JobIngestionRunner(
        repository=repository,
        connector=connector,
        health_repository=health_repository,
    )

    runner.run(profile_name=profile.profile_name)


def run_profiles(
    repository: JobIngestionRepository,
    profiles: Sequence[SearchProfile],
    *,
    recurring_health_enabled: bool = False,
) -> int:
    failed_profiles: list[tuple[str, Exception]] = []

    for profile in profiles:
        print("===")
        print(f"Running ingestion profile: {profile.profile_name}")
        print(f"Source: {profile.source_name}")

        try:
            run_profile(
                repository=repository,
                profile=profile,
                recurring_health_enabled=recurring_health_enabled,
            )
        except Exception as exc:
            failed_profiles.append((profile.profile_name, exc))
            print(
                f"Failed ingestion profile {profile.profile_name}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    if failed_profiles:
        print("===")
        print("Failed ingestion profiles:", file=sys.stderr)

        for profile_name, exc in failed_profiles:
            print(
                f"- {profile_name}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        return 1

    return 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = normalize_arguments(
        parser=parser,
        args=parser.parse_args(argv),
    )
    configure_logging(args.log_level)

    repository = JobIngestionRepository()

    if args.list_profiles:
        print_profiles(repository)
        return

    execution_id = configure_ingestion_execution_application_name()
    print(f"Ingestion execution ID: {execution_id}")

    try:
        profiles = select_profiles(
            repository=repository,
            profile_name=args.profile,
            source_filter=args.source,
            role_filter=SourceRole(args.role) if args.role else None,
        )
    except ValueError as exc:
        parser.exit(
            status=2,
            message=f"Error: {exc}\n\nHint: python -m src.ingest_jobs --list-profiles\n",
        )

    exit_code = run_profiles(
        repository=repository,
        profiles=profiles,
        recurring_health_enabled=args.profile is None,
    )

    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
