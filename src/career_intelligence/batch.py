"""Batch automation for Career Intelligence assessments."""

import argparse
import errno
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.career_intelligence.assessor import assess_opportunity


SCHEMA_VERSION = 1
RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "source_file",
        "company",
        "title",
        "career_lane",
        "career_lane_label",
        "opportunity_score",
        "recommendation",
        "constraint_action",
        "risks",
        "key_matched_capabilities",
    }
)
RECOMMENDATION_GROUPS = (
    "APPLY_NOW",
    "NETWORK_FIRST",
    "EXPLORE",
    "WATCH",
    "SKIP",
)


def _load_job(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("job must be a JSON object")

    required = ("company", "title", "description")
    missing = [
        field
        for field in required
        if not isinstance(payload.get(field), str) or not payload[field].strip()
    ]
    if missing:
        raise ValueError(f"missing or empty required fields: {', '.join(missing)}")

    return {field: payload[field].strip() for field in required}


def _validate_result_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != RESULT_FIELDS:
        raise ValueError("opportunity result does not match schema version 1")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported opportunity schema version: {record['schema_version']}")
    if not isinstance(record["source_file"], str) or not record["source_file"]:
        raise ValueError("opportunity result has an invalid source_file")
    return record


def _result_record(assessment: dict[str, Any], source_file: str) -> dict[str, Any]:
    risks = assessment["hard_skips"] + assessment["high_risks"] + assessment["reviews"]
    record = {
        "schema_version": SCHEMA_VERSION,
        "source_file": source_file,
        "company": assessment["company_name"],
        "title": assessment["title"],
        "career_lane": assessment["career_lane"],
        "career_lane_label": assessment["career_lane_label"],
        "opportunity_score": assessment["opportunity_score"],
        "recommendation": assessment["recommendation"],
        "constraint_action": assessment["constraint_action"],
        "risks": risks,
        "key_matched_capabilities": assessment["matched_capabilities"],
    }
    return _validate_result_record(record)


def _sort_opportunities(opportunities: list[dict[str, Any]]) -> None:
    opportunities.sort(
        key=lambda item: (
            -item["opportunity_score"],
            item["company"].casefold(),
            item["title"].casefold(),
        )
    )


def _markdown_text(value: str) -> str:
    normalized = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>-])", r"\\\1", normalized)


def _render_radar(opportunities: list[dict[str, Any]]) -> str:
    lines = ["# Opportunity Radar", ""]
    for recommendation in RECOMMENDATION_GROUPS:
        lines.extend((f"## {recommendation}", ""))
        matches = [item for item in opportunities if item["recommendation"] == recommendation]
        if not matches:
            lines.extend(("_No opportunities._", ""))
            continue
        for item in matches:
            company = _markdown_text(item["company"])
            title = _markdown_text(item["title"])
            lane = _markdown_text(item["career_lane_label"])
            lines.append(
                f"- **{company} — {title}** "
                f"({item['opportunity_score']}/100, {lane})"
            )
        lines.append("")
    return "\n".join(lines)


def _load_existing_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("opportunities.json must contain a JSON array")
    return [_validate_result_record(record) for record in payload]


def _move_no_clobber(source: Path, destination: Path) -> None:
    """Move source without ever replacing an existing destination."""
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                temporary = Path(handle.name)
                with source.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    try:
        source.unlink()
    except OSError:
        destination.unlink(missing_ok=True)
        raise


def _write_temporary(directory: Path, content: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _write_outputs(results: Path, opportunities: list[dict[str, Any]]) -> None:
    json_content = json.dumps(opportunities, indent=2, ensure_ascii=False) + "\n"
    radar_content = _render_radar(opportunities)
    json_temporary = _write_temporary(results, json_content)
    radar_temporary: Path | None = None
    try:
        radar_temporary = _write_temporary(results, radar_content)
        os.replace(json_temporary, results / "opportunities.json")
        os.replace(radar_temporary, results / "opportunity_radar.md")
    finally:
        json_temporary.unlink(missing_ok=True)
        if radar_temporary is not None:
            radar_temporary.unlink(missing_ok=True)


def process_batch(
    inbox: Path = Path("jobs/inbox"),
    processed: Path = Path("jobs/processed"),
    results: Path = Path("jobs/results"),
) -> dict[str, Any]:
    """Assess inbox JSON files and merge successful inputs into the current corpus."""
    inbox.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)

    paths = sorted(inbox.glob("*.json"))
    opportunities_path = results / "opportunities.json"
    radar_path = results / "opportunity_radar.md"
    opportunities = _load_existing_results(opportunities_path)
    if not paths:
        if not opportunities_path.exists() and not radar_path.exists():
            _write_outputs(results, opportunities)
        return {"processed": 0, "errors": [], "opportunities": opportunities}

    errors: list[dict[str, str]] = []
    existing_sources = {item["source_file"] for item in opportunities}

    for path in paths:
        try:
            destination = processed / path.name
            if path.name in existing_sources:
                raise FileExistsError(f"source file already exists in results: {path.name}")
            job = _load_job(path)
            assessment = assess_opportunity(job["company"], job["title"], job["description"])
            record = _result_record(assessment, path.name)
            _move_no_clobber(path, destination)
            opportunities.append(record)
            existing_sources.add(path.name)
        except Exception as exc:  # A single bad job must not stop the batch.
            errors.append({"file": path.name, "error": str(exc)})

    _sort_opportunities(opportunities)
    _write_outputs(results, opportunities)
    return {"processed": len(paths) - len(errors), "errors": errors, "opportunities": opportunities}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assess all job JSON files in an inbox.")
    parser.add_argument("--inbox", type=Path, default=Path("jobs/inbox"))
    parser.add_argument("--processed", type=Path, default=Path("jobs/processed"))
    parser.add_argument("--results", type=Path, default=Path("jobs/results"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = process_batch(args.inbox, args.processed, args.results)
    print(f"Processed {summary['processed']} job(s); {len(summary['errors'])} error(s).")
    for error in summary["errors"]:
        print(f"ERROR {error['file']}: {error['error']}", file=sys.stderr)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
