"""Persistent operator review state for Career Intelligence opportunities."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Mapping

from src.career_intelligence.batch import (
    RECOMMENDATION_GROUPS,
    _load_existing_results,
    _markdown_text,
)


VALID_STATES = ("NEW", "REVIEWED", "INTERESTED", "DISMISSED")
DISPLAY_STATES = ("NEW", "INTERESTED", "REVIEWED", "DISMISSED")
DEFAULT_ACTIONABLE_STATES = ("NEW", "INTERESTED", "REVIEWED")
DEFAULT_STATE_PATH = Path(".runtime/career_intelligence/operator_state.json")
STATE_SCHEMA_VERSION = 1


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _empty_state_payload() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "states": {},
    }


def validate_state(value: str) -> str:
    state = value.strip().upper()
    if state not in VALID_STATES:
        raise ValueError(f"invalid operator state: {value}")
    return state


def _validate_state_record(source_file: str, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"operator state for {source_file} must be an object")
    state = record.get("state")
    if not isinstance(state, str) or state not in VALID_STATES:
        raise ValueError(f"operator state for {source_file} is invalid")
    updated_at = record.get("updated_at_utc")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ValueError(f"operator state for {source_file} is missing updated_at_utc")
    return record


def validate_state_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("operator state file must contain a JSON object")
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported operator state schema version")
    states = payload.get("states")
    if not isinstance(states, dict):
        raise ValueError("operator state file must contain a states object")
    for source_file, record in states.items():
        if not isinstance(source_file, str) or not source_file.strip():
            raise ValueError("operator state source_file keys must be non-empty strings")
        _validate_state_record(source_file, record)
    return payload


def load_state_payload(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return _empty_state_payload()
    return validate_state_payload(json.loads(path.read_text(encoding="utf-8")))


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_state_payload(path: Path, payload: Mapping[str, Any]) -> None:
    validated = validate_state_payload(dict(payload))
    content = json.dumps(validated, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    json.loads(content)
    _write_atomic(path, content)


def set_operator_state(
    *,
    source_file: str,
    state: str,
    path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    source = source_file.strip()
    if not source:
        raise ValueError("source_file must not be blank")
    normalized_state = validate_state(state)
    payload = load_state_payload(path)
    states = dict(payload["states"])
    previous = states.get(source)
    record = {
        "state": normalized_state,
        "updated_at_utc": _utc_timestamp(),
    }
    if isinstance(previous, dict):
        first_seen = previous.get("first_seen_utc")
        if isinstance(first_seen, str) and first_seen.strip():
            record["first_seen_utc"] = first_seen
    record.setdefault("first_seen_utc", record["updated_at_utc"])
    states[source] = record
    updated = {
        "schema_version": STATE_SCHEMA_VERSION,
        "states": states,
    }
    write_state_payload(path, updated)
    return updated


def state_for_opportunity(
    opportunity: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    source_file = opportunity.get("source_file")
    states = payload.get("states")
    if not isinstance(source_file, str) or not isinstance(states, Mapping):
        return "NEW"
    record = states.get(source_file)
    if not isinstance(record, Mapping):
        return "NEW"
    state = record.get("state")
    return state if isinstance(state, str) and state in VALID_STATES else "NEW"


def _state_priority(state: str) -> int:
    return {
        "NEW": 0,
        "INTERESTED": 1,
        "REVIEWED": 2,
        "DISMISSED": 3,
    }[state]


def _opportunity_sort_key(item: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        -int(item.get("opportunity_score", 0)),
        str(item.get("company", "")).casefold(),
        str(item.get("title", "")).casefold(),
        str(item.get("source_file", "")).casefold(),
    )


def opportunities_with_state(
    opportunities: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for opportunity in opportunities:
        item = dict(opportunity)
        item["operator_state"] = state_for_opportunity(opportunity, payload)
        decorated.append(item)
    decorated.sort(
        key=lambda item: (
            _state_priority(item["operator_state"]),
            RECOMMENDATION_GROUPS.index(item["recommendation"]),
            *_opportunity_sort_key(item),
        )
    )
    return decorated


def operator_state_counts(
    opportunities: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, int]:
    counts = {state: 0 for state in VALID_STATES}
    for opportunity in opportunities:
        counts[state_for_opportunity(opportunity, payload)] += 1
    return counts


def _render_item(item: Mapping[str, Any]) -> str:
    company = _markdown_text(str(item["company"]))
    title = _markdown_text(str(item["title"]))
    lane = _markdown_text(str(item["career_lane_label"]))
    source_file = _markdown_text(str(item["source_file"]))
    return (
        f"- **{company} - {title}** "
        f"({item['opportunity_score']}/100, {lane}) `{source_file}`"
    )


def render_operator_radar(
    opportunities: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any],
    *,
    include_dismissed: bool = False,
) -> str:
    states = DISPLAY_STATES if include_dismissed else DEFAULT_ACTIONABLE_STATES
    decorated = opportunities_with_state(opportunities, payload)
    lines = ["# Career Opportunity Radar", ""]

    for state in states:
        lines.extend((f"## {state}", ""))
        state_matches = [item for item in decorated if item["operator_state"] == state]
        if not state_matches:
            lines.extend(("_No opportunities._", ""))
            continue
        for recommendation in RECOMMENDATION_GROUPS:
            matches = [
                item
                for item in state_matches
                if item["recommendation"] == recommendation
            ]
            if not matches:
                continue
            lines.extend((f"### {recommendation}", ""))
            for item in sorted(matches, key=_opportunity_sort_key):
                lines.append(_render_item(item))
            lines.append("")

    return "\n".join(lines)


def write_operator_radar(
    *,
    opportunities: list[dict[str, Any]],
    results: Path = Path("jobs/results"),
    state_path: Path = DEFAULT_STATE_PATH,
    include_dismissed: bool = False,
) -> str:
    payload = load_state_payload(state_path)
    content = render_operator_radar(
        opportunities,
        payload,
        include_dismissed=include_dismissed,
    )
    _write_atomic(results / "opportunity_radar.md", content)
    return content


def list_operator_states(
    *,
    opportunities_path: Path = Path("jobs/results/opportunities.json"),
    state_path: Path = DEFAULT_STATE_PATH,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    opportunities = _load_existing_results(opportunities_path)
    payload = load_state_payload(state_path)
    rows = opportunities_with_state(opportunities, payload)
    if include_dismissed:
        return rows
    return [row for row in rows if row["operator_state"] != "DISMISSED"]


def format_state_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    lines = ["STATE | RECOMMENDATION | SCORE | COMPANY | TITLE | SOURCE_FILE"]
    for row in rows:
        company = re.sub(r"\s+", " ", str(row["company"])).strip()
        title = re.sub(r"\s+", " ", str(row["title"])).strip()
        lines.append(
            f"{row['operator_state']} | {row['recommendation']} | "
            f"{row['opportunity_score']} | {company} | {title} | {row['source_file']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Career Intelligence operator review state."
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List opportunities with operator state.")
    list_parser.add_argument(
        "--opportunities",
        type=Path,
        default=Path("jobs/results/opportunities.json"),
    )
    list_parser.add_argument(
        "--include-dismissed",
        action="store_true",
        help="Include dismissed opportunities in the listing.",
    )

    set_parser = subparsers.add_parser("set", help="Set operator state for a source_file.")
    set_parser.add_argument("--source-file", required=True)
    set_parser.add_argument("--state", required=True)

    radar_parser = subparsers.add_parser("radar", help="Render the operator radar.")
    radar_parser.add_argument(
        "--opportunities",
        type=Path,
        default=Path("jobs/results/opportunities.json"),
    )
    radar_parser.add_argument(
        "--output",
        type=Path,
        default=Path("jobs/results/opportunity_radar.md"),
    )
    radar_parser.add_argument(
        "--include-dismissed",
        action="store_true",
        help="Include dismissed opportunities in the rendered radar.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            rows = list_operator_states(
                opportunities_path=args.opportunities,
                state_path=args.state_file,
                include_dismissed=args.include_dismissed,
            )
            print(format_state_rows(rows))
            return 0
        if args.command == "set":
            set_operator_state(
                source_file=args.source_file,
                state=args.state,
                path=args.state_file,
            )
            print(f"{args.source_file}: {validate_state(args.state)}")
            return 0
        if args.command == "radar":
            opportunities = _load_existing_results(args.opportunities)
            payload = load_state_payload(args.state_file)
            content = render_operator_radar(
                opportunities,
                payload,
                include_dismissed=args.include_dismissed,
            )
            _write_atomic(args.output, content)
            print(f"Radar written: {args.output}")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
