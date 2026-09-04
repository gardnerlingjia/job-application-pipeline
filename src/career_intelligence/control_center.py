"""Control Center read model for Career Intelligence runtime outputs."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from src.career_intelligence.batch import (
    RECOMMENDATION_GROUPS,
    _load_existing_results,
)
from src.career_intelligence.ingest_silver import (
    PROVENANCE_FILE,
    _load_existing_provenance,
    _validate_provenance_record,
)
from src.career_intelligence.operator_state import (
    DEFAULT_STATE_PATH,
    VALID_STATES,
    load_state_payload,
    state_for_opportunity,
)


DEFAULT_RESULTS_PATH = Path("jobs/results")
UNAVAILABLE_NETWORK_REASON = "not_available_in_v1_1_result_schema"


def _int_or_none(value: object) -> int | None:
    try:
        result = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return result if result is not None and result > 0 else None


def _job_ids(payload: Mapping[str, object]) -> set[int]:
    result: set[int] = set()
    for collection_name in ("job_readiness", "top_jobs"):
        collection = payload.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            silver_job_id = _int_or_none(item.get("silver_job_id"))
            if silver_job_id is not None:
                result.add(silver_job_id)
    return result


def _provenance_by_source_file(path: Path) -> dict[str, dict[str, Any]]:
    rows = _load_existing_provenance(path)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = _validate_provenance_record(row)
        source_file = str(record["source_file"])
        result[source_file] = record
    return result


def _recommendation_counts(records: list[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(str(record.get("recommendation") or "") for record in records)
    return {name: counter.get(name, 0) for name in RECOMMENDATION_GROUPS}


def _state_counts(records: list[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(str(record.get("operator_state") or "") for record in records)
    return {name: counter.get(name, 0) for name in VALID_STATES}


def _record_sort_key(item: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        -int(item.get("opportunity_score") or 0),
        str(item.get("company") or "").casefold(),
        str(item.get("title") or "").casefold(),
        str(item.get("source_file") or "").casefold(),
    )


def load_career_intelligence_control_center(
    product_payload: Mapping[str, object],
    *,
    results: Path = DEFAULT_RESULTS_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Build a sidecar Career Intelligence lens for the Product V1 Control Center.

    The function reads only V1.1/V1.2/V1.4 runtime files. It does not call scoring,
    does not mutate Product V1 ranking inputs, and fails closed when runtime files
    are absent or malformed.
    """

    opportunities_path = results / "opportunities.json"
    provenance_path = results / PROVENANCE_FILE
    if not opportunities_path.exists():
        return {
            "available": False,
            "status": "not_run",
            "reason": f"{opportunities_path} not found",
            "records": [],
            "by_silver_job_id": {},
            "summary": {
                "opportunity_count": 0,
                "joined_job_count": 0,
                "unmatched_opportunity_count": 0,
                "recommendation_counts": _recommendation_counts([]),
                "operator_state_counts": _state_counts([]),
            },
        }

    try:
        opportunities = _load_existing_results(opportunities_path)
        provenance = _provenance_by_source_file(provenance_path)
        state_payload = load_state_payload(state_path)
    except Exception as exc:
        return {
            "available": False,
            "status": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "records": [],
            "by_silver_job_id": {},
            "summary": {
                "opportunity_count": 0,
                "joined_job_count": 0,
                "unmatched_opportunity_count": 0,
                "recommendation_counts": _recommendation_counts([]),
                "operator_state_counts": _state_counts([]),
            },
        }

    known_job_ids = _job_ids(product_payload)
    records: list[dict[str, Any]] = []
    by_silver_job_id: dict[str, dict[str, Any]] = {}
    for opportunity in opportunities:
        source_file = str(opportunity["source_file"])
        source_provenance = provenance.get(source_file, {})
        silver_job_id = _int_or_none(source_provenance.get("silver_job_id"))
        joined = silver_job_id is not None and silver_job_id in known_job_ids
        operator_state = state_for_opportunity(opportunity, state_payload)
        record = {
            "source_file": source_file,
            "silver_job_id": silver_job_id,
            "job_join_status": "joined" if joined else "unmatched",
            "company": opportunity["company"],
            "title": opportunity["title"],
            "career_lane": opportunity["career_lane"],
            "career_lane_label": opportunity["career_lane_label"],
            "opportunity_score": opportunity["opportunity_score"],
            "recommendation": opportunity["recommendation"],
            "constraint_action": opportunity["constraint_action"],
            "risks": list(opportunity["risks"]),
            "key_matched_capabilities": list(opportunity["key_matched_capabilities"]),
            "operator_state": operator_state,
            "network_access": None,
            "relationship_level": None,
            "network_status": UNAVAILABLE_NETWORK_REASON,
            "workspace_available": bool(
                joined
                and silver_job_id is not None
                and (
                    operator_state == "INTERESTED"
                    or opportunity["recommendation"] in {"APPLY_NOW", "NETWORK_FIRST"}
                )
            ),
            "provenance": {
                "source_file": source_file,
                "silver_job_id": silver_job_id,
                "raw_job_id": source_provenance.get("raw_job_id"),
                "source_name": source_provenance.get("source_name"),
                "external_job_id": source_provenance.get("external_job_id"),
                "source_url": source_provenance.get("source_url"),
                "stable_identity_type": source_provenance.get("stable_identity_type"),
                "stable_identity_sha256": source_provenance.get(
                    "stable_identity_sha256"
                ),
                "description_source": source_provenance.get("description_source"),
                "description_quality": source_provenance.get("description_quality"),
                "ingestion_status": source_provenance.get("ingestion_status"),
            },
        }
        records.append(record)
        if silver_job_id is not None:
            existing = by_silver_job_id.get(str(silver_job_id))
            if existing is None or _record_sort_key(record) < _record_sort_key(existing):
                by_silver_job_id[str(silver_job_id)] = record

    records.sort(
        key=lambda item: (
            item["operator_state"] == "DISMISSED",
            item["operator_state"] != "INTERESTED",
            item["recommendation"] not in {"APPLY_NOW", "NETWORK_FIRST"},
            *_record_sort_key(item),
        )
    )
    joined_count = sum(record["job_join_status"] == "joined" for record in records)
    return {
        "available": True,
        "status": "ready",
        "reason": None,
        "records": records,
        "by_silver_job_id": by_silver_job_id,
        "state_action_path": "/api/v1/career-intelligence/operator-state",
        "summary": {
            "opportunity_count": len(records),
            "joined_job_count": joined_count,
            "unmatched_opportunity_count": len(records) - joined_count,
            "recommendation_counts": _recommendation_counts(records),
            "operator_state_counts": _state_counts(records),
        },
        "boundaries": {
            "career_intelligence_is_additional_decision_lens": True,
            "product_v1_ranking_authority": False,
            "application_submission_authority": False,
            "opportunities_schema_unchanged": True,
            "network_fields_not_recomputed": True,
        },
    }


def merge_career_intelligence_payload(
    payload: Mapping[str, object],
    career_payload: Mapping[str, Any],
) -> dict[str, object]:
    """Attach Career Intelligence read-model data without changing Product V1 order."""

    result = dict(payload)
    by_id = career_payload.get("by_silver_job_id")
    by_silver_job_id = by_id if isinstance(by_id, Mapping) else {}
    for collection_name in ("job_readiness", "top_jobs"):
        collection = result.get(collection_name)
        if not isinstance(collection, list):
            continue
        decorated: list[object] = []
        for item in collection:
            if not isinstance(item, Mapping):
                decorated.append(item)
                continue
            copied = dict(item)
            silver_job_id = _int_or_none(copied.get("silver_job_id"))
            copied["career_intelligence"] = (
                by_silver_job_id.get(str(silver_job_id))
                if silver_job_id is not None
                else None
            )
            decorated.append(copied)
        result[collection_name] = decorated

    result["career_intelligence"] = dict(career_payload)
    summary = dict(result.get("summary") or {})
    ci_summary = career_payload.get("summary")
    if isinstance(ci_summary, Mapping):
        summary["career_intelligence_opportunity_count"] = ci_summary.get(
            "opportunity_count",
            0,
        )
        summary["career_intelligence_joined_job_count"] = ci_summary.get(
            "joined_job_count",
            0,
        )
    result["summary"] = summary

    boundaries = dict(result.get("boundaries") or {})
    boundaries.update(
        {
            "career_intelligence_is_not_product_v1_ranking_authority": True,
            "career_intelligence_operator_state_is_local_runtime": True,
            "career_intelligence_does_not_automate_applications": True,
        }
    )
    result["boundaries"] = boundaries
    return result


__all__ = [
    "DEFAULT_RESULTS_PATH",
    "UNAVAILABLE_NETWORK_REASON",
    "load_career_intelligence_control_center",
    "merge_career_intelligence_payload",
]
