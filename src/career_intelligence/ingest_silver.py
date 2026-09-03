"""Assess normalized Silver jobs through the Career Intelligence V1.1 lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.batch import (
    _load_existing_results,
    _render_radar,
    _result_record,
    _sort_opportunities,
    _validate_result_record,
    _write_temporary,
)
from src.career_intelligence.silver_adapter import (
    SilverCareerInput,
    SilverJobReadRepository,
    adapt_silver_rows,
    normalize_source_patterns,
)


PROVENANCE_FILE = "silver_ingestion_provenance.json"


def _load_existing_provenance(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{PROVENANCE_FILE} must contain a JSON array")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{PROVENANCE_FILE} must contain JSON objects")
    return payload


def _validate_provenance_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("Silver provenance record must be a JSON object")
    required = (
        "schema_version",
        "source_file",
        "ingestion_status",
        "stable_identity_type",
        "stable_identity_sha256",
        "description_source",
        "description_quality",
        "silver_job_id",
        "raw_job_id",
        "source_name",
        "external_job_id",
        "source_url",
    )
    missing = [field for field in required if field not in record]
    if missing:
        raise ValueError(f"Silver provenance record missing fields: {', '.join(missing)}")
    if not isinstance(record["source_file"], str) or not record["source_file"]:
        raise ValueError("Silver provenance record has invalid source_file")
    if record["ingestion_status"] not in {"assessed", "skipped"}:
        raise ValueError("Silver provenance record has invalid ingestion_status")
    if record["description_quality"] not in {"strong", "weak", "missing"}:
        raise ValueError("Silver provenance record has invalid description_quality")
    return record


def _merge_provenance(
    existing: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_source_file = {
        str(item.get("source_file")): item
        for item in existing
        if isinstance(item.get("source_file"), str) and item["source_file"]
    }
    for item in additions:
        source_file = str(item["source_file"])
        by_source_file.setdefault(source_file, item)
    return [by_source_file[key] for key in sorted(by_source_file)]


def _prepare_json_payloads(
    opportunities: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> tuple[str, str, str]:
    validated_opportunities = [_validate_result_record(record) for record in opportunities]
    validated_provenance = [_validate_provenance_record(record) for record in provenance]
    opportunities_content = (
        json.dumps(validated_opportunities, indent=2, ensure_ascii=False) + "\n"
    )
    radar_content = _render_radar(validated_opportunities)
    provenance_content = (
        json.dumps(validated_provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )

    json.loads(opportunities_content)
    json.loads(provenance_content)
    return opportunities_content, radar_content, provenance_content


def _write_output_pair(
    results: Path,
    *,
    opportunities: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> None:
    opportunities_content, radar_content, provenance_content = _prepare_json_payloads(
        opportunities,
        provenance,
    )
    temporary_paths: list[Path] = []
    try:
        opportunities_temporary = _write_temporary(results, opportunities_content)
        temporary_paths.append(opportunities_temporary)
        radar_temporary = _write_temporary(results, radar_content)
        temporary_paths.append(radar_temporary)
        provenance_temporary = _write_temporary(results, provenance_content)
        temporary_paths.append(provenance_temporary)

        os.replace(opportunities_temporary, results / "opportunities.json")
        os.replace(radar_temporary, results / "opportunity_radar.md")
        os.replace(provenance_temporary, results / PROVENANCE_FILE)
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def assess_silver_inputs(
    inputs: list[SilverCareerInput],
    *,
    results: Path = Path("jobs/results"),
    skipped_provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    results.mkdir(parents=True, exist_ok=True)
    opportunities_path = results / "opportunities.json"
    opportunities = _load_existing_results(opportunities_path)
    existing_sources = {item["source_file"] for item in opportunities}
    existing_provenance = _load_existing_provenance(results / PROVENANCE_FILE)

    errors: list[dict[str, Any]] = []
    assessed: list[SilverCareerInput] = []
    seen_this_run: set[str] = set()

    for item in inputs:
        if item.source_file in seen_this_run:
            errors.append(
                {
                    "record": item.source_file,
                    "error": "duplicate Silver source identity in this run",
                }
            )
            continue
        seen_this_run.add(item.source_file)
        if item.source_file in existing_sources:
            continue

        try:
            assessment = assess_opportunity(item.company, item.title, item.description)
            opportunities.append(_result_record(assessment, item.source_file))
            existing_sources.add(item.source_file)
            assessed.append(item)
        except Exception as exc:
            errors.append({"record": item.source_file, "error": str(exc)})

    merged_provenance = _merge_provenance(
        existing_provenance,
        [*(skipped_provenance or []), *[item.provenance for item in assessed]],
    )
    _sort_opportunities(opportunities)
    if assessed or skipped_provenance or not opportunities_path.exists():
        _write_output_pair(
            results,
            opportunities=opportunities,
            provenance=merged_provenance,
        )

    return {
        "processed": len(assessed),
        "skipped_existing": len(inputs) - len(assessed) - len(errors),
        "errors": errors,
        "opportunities": opportunities,
        "provenance": merged_provenance,
    }


def process_silver(
    *,
    repository: SilverJobReadRepository | None = None,
    results: Path = Path("jobs/results"),
    limit: int = 100,
    source: str | None = None,
) -> dict[str, Any]:
    repository = repository or SilverJobReadRepository()
    rows = repository.load_silver_jobs(
        limit=limit,
        source_patterns=normalize_source_patterns(source),
    )
    inputs, conversion_errors = adapt_silver_rows(rows)
    skipped_provenance = [
        error["provenance"]
        for error in conversion_errors
        if isinstance(error.get("provenance"), dict)
    ]
    summary = assess_silver_inputs(
        inputs,
        results=results,
        skipped_provenance=skipped_provenance,
    )
    summary["errors"] = conversion_errors + summary["errors"]
    summary["loaded"] = len(rows)
    summary["converted"] = len(inputs)
    return summary


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess normalized Silver jobs with Career Intelligence."
    )
    parser.add_argument(
        "--source",
        help="Optional exact source name or source-family filter, e.g. personio:target or personio.",
    )
    parser.add_argument("--limit", type=positive_integer, default=100)
    parser.add_argument("--results", type=Path, default=Path("jobs/results"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = process_silver(
        results=args.results,
        limit=args.limit,
        source=args.source,
    )
    print(
        f"Loaded {summary['loaded']} Silver job(s); "
        f"converted {summary['converted']}; "
        f"assessed {summary['processed']}; "
        f"skipped existing {summary['skipped_existing']}; "
        f"{len(summary['errors'])} error(s)."
    )
    for error in summary["errors"]:
        print(
            f"ERROR {error.get('record', 'unknown')}: {error['error']}",
            file=sys.stderr,
        )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
