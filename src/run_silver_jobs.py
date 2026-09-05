import argparse

from src.silver.relevance import (
    get_accessibility_matches,
    get_role_matches,
    get_skill_matches,
    get_silver_decision_reason,
    is_relevant_for_silver,
)
from src.silver.repository import SilverJobRepository
from src.silver.successfactors_location_projection import (
    write_silver_job_with_successfactors_locations,
)
from src.silver.transformer import (
    get_supported_source_patterns,
    transform_raw_job_to_silver,
)


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")

    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transform unprocessed Bronze raw_jobs into Silver jobs."
    )
    parser.add_argument(
        "--source",
        help=(
            "Optional exact source name or source-family filter, "
            "e.g. enercity:discovery or enercity."
        ),
    )
    parser.add_argument(
        "--ingestion-run-id",
        type=positive_integer,
        help="Optional exact ingestion run id to bind Bronze selection.",
    )
    parser.add_argument(
        "--reprocess-raw-job-id",
        action="append",
        type=positive_integer,
        default=[],
        help=(
            "Explicitly reprocess an existing raw_jobs.id through the current Silver "
            "logic. May be provided more than once."
        ),
    )
    parser.add_argument("--limit", type=int, default=100)
    return parser


def source_matches_pattern(source_name: str, source_filter: str) -> bool:
    return source_name == source_filter or source_name.startswith(f"{source_filter}:")


def resolve_source_patterns(source_filter: str | None) -> list[str]:
    if not source_filter:
        return get_supported_source_patterns()

    supported = get_supported_source_patterns()

    if source_filter in supported:
        return [source_filter]

    exact_source = source_filter if ":" in source_filter else f"{source_filter}:%"

    if exact_source in supported or exact_source.endswith(":%"):
        return [exact_source]

    return [source_filter]


def deduplicate_raw_job_ids(raw_job_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(raw_job_ids))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    repository = SilverJobRepository()
    source_patterns = resolve_source_patterns(args.source)
    reprocess_raw_job_ids = deduplicate_raw_job_ids(args.reprocess_raw_job_id)

    if reprocess_raw_job_ids:
        if args.ingestion_run_id is not None:
            raise SystemExit("--ingestion-run-id cannot be combined with --reprocess-raw-job-id")

        raw_jobs = repository.load_raw_jobs_by_ids(
            raw_job_ids=reprocess_raw_job_ids,
            source_patterns=source_patterns if args.source else None,
        )
        found_raw_job_ids = {int(raw_job["id"]) for raw_job in raw_jobs}
        missing_raw_job_ids = [
            raw_job_id
            for raw_job_id in reprocess_raw_job_ids
            if raw_job_id not in found_raw_job_ids
        ]
        if missing_raw_job_ids:
            missing = ", ".join(str(raw_job_id) for raw_job_id in missing_raw_job_ids)
            raise SystemExit(
                "Requested raw job ids were not found"
                " or did not match the source filter: "
                f"{missing}"
            )

        print(
            "Explicit Silver reprocess requested for raw_job_id(s): "
            + ", ".join(str(raw_job_id) for raw_job_id in reprocess_raw_job_ids)
        )
    else:
        raw_jobs = repository.load_unprocessed_raw_jobs(
            limit=args.limit,
            source_patterns=source_patterns,
            ingestion_run_id=args.ingestion_run_id,
        )

    if not raw_jobs:
        print("No unprocessed raw jobs found.")
        return

    transformed_count = 0
    skipped_count = 0

    for raw_job in raw_jobs:
        role_matches = get_role_matches(raw_job)
        skill_matches = get_skill_matches(raw_job)
        accessibility_matches = get_accessibility_matches(raw_job)

        if not is_relevant_for_silver(raw_job):
            repository.record_processing_decision(
                raw_job_id=raw_job["id"],
                decision="skipped",
                reason=get_silver_decision_reason(raw_job),
                role_matches=role_matches,
                skill_matches=skill_matches,
                accessibility_matches=accessibility_matches,
            )
            skipped_count += 1

            print(
                f"Skipped raw job: raw_job_id={raw_job['id']} | "
                f"source={raw_job['source_name']} | "
                f"roles={role_matches} | "
                f"skills={skill_matches} | "
                f"accessibility={accessibility_matches}"
            )
            continue

        silver_job = transform_raw_job_to_silver(raw_job)
        write_silver_job_with_successfactors_locations(
            repository,
            silver_job=silver_job,
            raw_job=raw_job,
        )
        repository.record_processing_decision(
            raw_job_id=raw_job["id"],
            decision="included",
            reason="relevant_for_silver",
            role_matches=role_matches,
            skill_matches=skill_matches,
            accessibility_matches=accessibility_matches,
        )
        transformed_count += 1

        print(
            f"Silver job written: raw_job_id={silver_job['raw_job_id']} | "
            f"{silver_job['title']} | {silver_job['company_name']}"
        )

    print("---")
    print(f"Transformed raw jobs: {transformed_count}")
    print(f"Skipped raw jobs: {skipped_count}")


if __name__ == "__main__":
    main()
