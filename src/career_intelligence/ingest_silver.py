"""Assess normalized Silver jobs through the Career Intelligence V1.1 lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from src.career_intelligence.assessor import assess_opportunity
from src.career_intelligence.batch import (
    _load_existing_results,
    _render_radar,
    _result_record,
    _sort_opportunities,
    _validate_result_record,
    _write_temporary,
)
from src.career_intelligence.freshness import apply_freshness_penalty
from src.career_intelligence.scoring import calculate_opportunity_score
from src.career_intelligence.silver_adapter import (
    ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY,
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
    if record["description_quality"] not in {
        "strong",
        "weak",
        "missing",
        ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY,
    }:
        raise ValueError("Silver provenance record has invalid description_quality")
    return record


def _remove_missing_description_evidence(
    assessment: dict[str, Any],
    item: SilverCareerInput,
) -> dict[str, Any]:
    if item.description_quality != ATS_PROVIDER_IDENTITY_DESCRIPTION_QUALITY:
        return assessment

    scores = dict(assessment.get("scores") or {})
    scores["capability_fit"] = 0
    scores["domain_fit"] = 0
    scores["evidence_strength"] = 0
    if assessment.get("explanation", {}).get("semantics_version", 0) >= 3:
        scores["career_lane_fit"] = 0

    adjusted = dict(assessment)
    adjusted["scores"] = scores
    adjusted["matched_capabilities"] = []
    adjusted["domain_matches"] = []
    adjusted["evidence_details"] = []
    adjusted["opportunity_score"] = calculate_opportunity_score(scores)
    adjusted["recommendation"] = "SKIP" if assessment["recommendation"] == "SKIP" else "WATCH"
    if "explanation" in adjusted:
        adjusted["explanation"] = dict(adjusted["explanation"])
        adjusted["explanation"]["recommended_action"] = adjusted["recommendation"]
        adjusted["explanation"]["supporting_capabilities"] = []
        adjusted["explanation"]["scores"] = scores
        adjusted["explanation"]["gates"] = [
            {
                "gate": "description_missing",
                "reason": "No requirement evidence; candidate score is zero.",
            }
        ]
        adjusted["explanation"]["candidate_strength"] = {
            "score": 0,
            "blocking_gaps": {"description_missing": "No role requirement evidence."},
        }
    adjusted["candidate_strength"] = {
        "score": 0,
        "blocking_gaps": {"description_missing": "No role requirement evidence."},
    }
    item.provenance["missing_description_evidence_policy"] = (
        "ats_provider_identity_only_no_capability_or_domain_evidence"
    )
    return adjusted


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
        previous = by_source_file.get(source_file)
        if (
            previous is not None
            and previous.get("ingestion_status") == "assessed"
            and item.get("ingestion_status") == "skipped"
            and "duplicate_reason" not in item
        ):
            continue
        by_source_file[source_file] = item
    return [by_source_file[key] for key in sorted(by_source_file)]


def _prepare_json_payloads(
    opportunities: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> tuple[str, str, str]:
    validated_opportunities = [_validate_result_record(record) for record in opportunities]
    validated_provenance = [_validate_provenance_record(record) for record in provenance]
    opportunities_content = json.dumps(validated_opportunities, indent=2, ensure_ascii=False) + "\n"
    radar_content = _render_radar(validated_opportunities)
    provenance_content = (
        json.dumps(validated_provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )

    json.loads(opportunities_content)
    json.loads(provenance_content)
    return opportunities_content, radar_content, provenance_content


def _apply_freshness_to_assessment(
    assessment: dict[str, Any],
    item: SilverCareerInput,
) -> dict[str, Any]:
    base_score = assessment["opportunity_score"]
    adjusted = apply_freshness_penalty(assessment, item.freshness)
    # Freshness affects ranking, never creates a new access/capability recommendation.
    # In particular it cannot turn WATCH or a warm/referral APPLY into NETWORK FIRST.
    if item.freshness.ranking_penalty and assessment["recommendation"] in {
        "APPLY_NOW",
        "NETWORK_FIRST",
    }:
        adjusted["recommendation"] = "WATCH"
    if "explanation" in adjusted:
        adjusted["explanation"] = dict(adjusted["explanation"])
        adjusted["explanation"]["recommended_action"] = {
            "APPLY_NOW": "APPLY",
            "NETWORK_FIRST": "NETWORK FIRST",
        }.get(adjusted["recommendation"], adjusted["recommendation"])
    item.provenance["base_opportunity_score"] = base_score
    item.provenance["freshness_adjusted_opportunity_score"] = adjusted["opportunity_score"]
    if adjusted.get("explanation", {}).get("semantics_version", 0) >= 3:
        adjusted["explanation"]["freshness_ranking_score"] = adjusted["opportunity_score"]
        adjusted["opportunity_score"] = base_score
        if item.freshness.ranking_penalty:
            adjusted["explanation"]["gates"] = [
                *adjusted["explanation"].get("gates", []),
                {
                    "gate": "freshness_review",
                    "reason": "Age changes ranking/action, not candidate evidence.",
                    "ranking_penalty": item.freshness.ranking_penalty,
                },
            ]
    return adjusted


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    return None


def _refresh_existing_freshness(
    opportunity: dict[str, Any],
    existing_provenance: dict[str, Any] | None,
    item: SilverCareerInput,
) -> bool:
    if opportunity.get("explanation", {}).get("semantics_version", 0) >= 3:
        base = opportunity["opportunity_score"]
        ranking = max(0, int(round(base)) - item.freshness.ranking_penalty)
        explanation = opportunity["explanation"]
        changed = explanation.get("freshness_ranking_score") != ranking
        explanation["freshness_ranking_score"] = ranking
        if item.freshness.ranking_penalty and opportunity["recommendation"] in {
            "APPLY_NOW",
            "NETWORK_FIRST",
        }:
            opportunity["recommendation"] = "WATCH"
            explanation["recommended_action"] = "WATCH"
            explanation["gates"] = [
                *explanation.get("gates", []),
                {"gate": "freshness_review", "reason": "Age review; candidate score unchanged."},
            ]
            changed = True
        item.provenance["base_opportunity_score"] = base
        item.provenance["freshness_adjusted_opportunity_score"] = ranking
        return changed
    previous_penalty = _number((existing_provenance or {}).get("freshness_ranking_penalty")) or 0
    base_score = _number((existing_provenance or {}).get("base_opportunity_score"))
    if base_score is None:
        current_score = _number(opportunity.get("opportunity_score"))
        if current_score is None:
            return False
        base_score = min(100, current_score + previous_penalty)

    adjusted_score = max(0, base_score - item.freshness.ranking_penalty)
    item.provenance["base_opportunity_score"] = base_score
    item.provenance["freshness_adjusted_opportunity_score"] = adjusted_score
    if opportunity.get("opportunity_score") == adjusted_score:
        return False
    opportunity["opportunity_score"] = adjusted_score
    return True


def _dedupe_preference(item: SilverCareerInput) -> tuple[int, int, str]:
    canonical_type = str(item.provenance.get("canonical_source_type") or "").casefold()
    employer_origin_rank = 0 if "employer_origin" in canonical_type else 1
    quality_rank = 0 if item.description_quality == "strong" else 1
    return employer_origin_rank, quality_rank, item.source_file


def _provenance_preference(provenance: Mapping[str, Any]) -> tuple[int, int, str]:
    canonical_type = str(provenance.get("canonical_source_type") or "").casefold()
    quality = str(provenance.get("description_quality") or "").casefold()
    source_file = str(provenance.get("source_file") or "")
    employer_origin_rank = 0 if "employer_origin" in canonical_type else 1
    quality_rank = 0 if quality == "strong" else 1
    return employer_origin_rank, quality_rank, source_file


def deduplicate_silver_inputs(
    inputs: list[SilverCareerInput],
) -> tuple[list[SilverCareerInput], list[dict[str, Any]]]:
    by_key: dict[str, list[SilverCareerInput]] = {}
    passthrough: list[SilverCareerInput] = []
    for item in inputs:
        canonical_key = item.provenance.get("canonical_key_candidate")
        if isinstance(canonical_key, str) and canonical_key.strip():
            by_key.setdefault(canonical_key, []).append(item)
        else:
            passthrough.append(item)

    kept: list[SilverCareerInput] = list(passthrough)
    skipped: list[dict[str, Any]] = []
    for rows in by_key.values():
        winner = sorted(rows, key=_dedupe_preference)[0]
        kept.append(winner)
        for duplicate in rows:
            if duplicate is winner:
                continue
            provenance = dict(duplicate.provenance)
            provenance["ingestion_status"] = "skipped"
            provenance["duplicate_of_source_file"] = winner.source_file
            provenance["duplicate_reason"] = "same_silver_canonical_key"
            skipped.append(provenance)

    kept.sort(key=lambda item: item.source_file)
    skipped.sort(key=lambda item: str(item.get("source_file") or ""))
    return kept, skipped


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
    provenance_by_source_file = {
        str(item.get("source_file")): item
        for item in existing_provenance
        if isinstance(item.get("source_file"), str) and item["source_file"]
    }
    opportunities_by_source_file = {
        str(item["source_file"]): item
        for item in opportunities
        if isinstance(item.get("source_file"), str)
    }

    errors: list[dict[str, Any]] = []
    assessed: list[SilverCareerInput] = []
    refreshed_provenance: list[dict[str, Any]] = []
    freshness_refreshed = 0
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
            existing_opportunity = opportunities_by_source_file.get(item.source_file)
            if existing_opportunity is not None and _refresh_existing_freshness(
                existing_opportunity,
                provenance_by_source_file.get(item.source_file),
                item,
            ):
                freshness_refreshed += 1
            refreshed_provenance.append(item.provenance)
            continue

        canonical_key = item.provenance.get("canonical_key_candidate")
        existing_duplicate = None
        if isinstance(canonical_key, str) and canonical_key.strip():
            existing_duplicate = next(
                (
                    record
                    for record in existing_provenance
                    if record.get("canonical_key_candidate") == canonical_key
                    and isinstance(record.get("source_file"), str)
                    and record.get("source_file") in opportunities_by_source_file
                ),
                None,
            )
        if existing_duplicate is not None:
            existing_source_file = str(existing_duplicate["source_file"])
            if _dedupe_preference(item) < _provenance_preference(existing_duplicate):
                opportunities = [
                    opportunity
                    for opportunity in opportunities
                    if opportunity.get("source_file") != existing_source_file
                ]
                opportunities_by_source_file.pop(existing_source_file, None)
                existing_sources.discard(existing_source_file)
                skipped_existing = dict(existing_duplicate)
                skipped_existing["ingestion_status"] = "skipped"
                skipped_existing["duplicate_of_source_file"] = item.source_file
                skipped_existing["duplicate_reason"] = "same_silver_canonical_key"
                refreshed_provenance.append(skipped_existing)
            else:
                skipped_item = dict(item.provenance)
                skipped_item["ingestion_status"] = "skipped"
                skipped_item["duplicate_of_source_file"] = existing_source_file
                skipped_item["duplicate_reason"] = "same_silver_canonical_key"
                refreshed_provenance.append(skipped_item)
                continue

        try:
            assessment = assess_opportunity(item.company, item.title, item.description)
            assessment = _remove_missing_description_evidence(assessment, item)
            assessment = _apply_freshness_to_assessment(assessment, item)
            opportunities.append(_result_record(assessment, item.source_file))
            existing_sources.add(item.source_file)
            assessed.append(item)
        except Exception as exc:
            errors.append({"record": item.source_file, "error": str(exc)})

    merged_provenance = _merge_provenance(
        existing_provenance,
        [
            *(skipped_provenance or []),
            *refreshed_provenance,
            *[item.provenance for item in assessed],
        ],
    )
    _sort_opportunities(opportunities)
    if assessed or skipped_provenance or refreshed_provenance or not opportunities_path.exists():
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
        "freshness_refreshed": freshness_refreshed,
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
    inputs, duplicate_provenance = deduplicate_silver_inputs(inputs)
    skipped_provenance = [
        error["provenance"]
        for error in conversion_errors
        if isinstance(error.get("provenance"), dict)
    ] + duplicate_provenance
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
        help=(
            "Optional exact source name or source-family filter, e.g. personio:target or personio."
        ),
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
