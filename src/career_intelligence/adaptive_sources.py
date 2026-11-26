"""Adaptive source discovery read model for Career Intelligence.

The module derives source candidates from existing Career Intelligence outputs and
Silver provenance only. It never registers, activates, crawls, ingests, ranks, or
changes the committed V2.1 source strategy YAML.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import yaml

from src.career_intelligence.batch import RECOMMENDATION_GROUPS, _load_existing_results
from src.career_intelligence.ingest_silver import PROVENANCE_FILE, _load_existing_provenance
from src.career_intelligence.source_strategy import (
    DEFAULT_SOURCE_STRATEGY_PATH,
    CareerSourceStrategy,
    load_source_strategy,
)


DEFAULT_ADAPTIVE_RULES_PATH = Path("config/career_adaptive_source_rules.yaml")
DEFAULT_ADAPTIVE_SOURCE_STATE_PATH = Path(
    ".runtime/career_intelligence/adaptive_source_state.json"
)
DEFAULT_RESULTS_PATH = Path("jobs/results")
RULES_SCHEMA_VERSION = "career_intelligence.adaptive_source_rules.v1"
STATE_SCHEMA_VERSION = 1
VALID_SUGGESTIONS = ("PROMOTE_TO_TIER_A", "PROMOTE_TO_TIER_B", "WATCH", "IGNORE")
VALID_DECISIONS = ("UNREVIEWED", "PROMOTED_A", "PROMOTED_B", "WATCH", "IGNORED")


@dataclass(frozen=True)
class AdaptiveSourceRules:
    lookback_days: int
    thresholds: Mapping[str, Mapping[str, Any]]
    primary_lanes: tuple[str, ...]
    adjacent_lanes: tuple[str, ...]
    berlin_terms: tuple[str, ...]
    remote_germany_terms: tuple[str, ...]
    conflict_terms: tuple[str, ...]


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _as_text_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"adaptive source rules missing {key}")
    result = tuple(str(item).strip().casefold() for item in value if str(item).strip())
    if not result:
        raise ValueError(f"adaptive source rules has empty {key}")
    return result


def load_adaptive_source_rules(
    path: Path = DEFAULT_ADAPTIVE_RULES_PATH,
) -> AdaptiveSourceRules:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("adaptive source rules must be a YAML mapping")
    if payload.get("schema_version") != RULES_SCHEMA_VERSION:
        raise ValueError("unsupported adaptive source rules schema version")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("adaptive source rules must contain thresholds")
    lanes = payload.get("career_lanes")
    locations = payload.get("location_terms")
    if not isinstance(lanes, Mapping) or not isinstance(locations, Mapping):
        raise ValueError("adaptive source rules missing lanes or location terms")
    lookback_days = int(payload.get("lookback_days") or 0)
    if lookback_days <= 0:
        raise ValueError("adaptive source rules lookback_days must be positive")
    return AdaptiveSourceRules(
        lookback_days=lookback_days,
        thresholds=thresholds,
        primary_lanes=_as_text_tuple(lanes, "primary"),
        adjacent_lanes=_as_text_tuple(lanes, "adjacent"),
        berlin_terms=_as_text_tuple(locations, "berlin_compatible"),
        remote_germany_terms=_as_text_tuple(locations, "remote_germany"),
        conflict_terms=_as_text_tuple(locations, "conflicts"),
    )


def normalize_company_key(company_name: str) -> str:
    value = company_name.casefold()
    value = re.sub(r"\b(gmbh|ag|se|inc|llc|ltd|limited|corp|corporation|group)\b", " ", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _empty_state_payload() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "decisions": {}}


def validate_decision(value: str) -> str:
    decision = value.strip().upper()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"invalid adaptive source decision: {value}")
    return decision


def validate_adaptive_source_state_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("adaptive source state file must contain a JSON object")
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported adaptive source state schema version")
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        raise ValueError("adaptive source state file must contain decisions object")
    for key, record in decisions.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("adaptive source decision keys must be non-empty strings")
        if not isinstance(record, dict):
            raise ValueError(f"adaptive source decision for {key} must be an object")
        if record.get("decision") not in VALID_DECISIONS:
            raise ValueError(f"adaptive source decision for {key} is invalid")
        updated = record.get("updated_at_utc")
        if not isinstance(updated, str) or not updated.strip():
            raise ValueError(f"adaptive source decision for {key} missing updated_at_utc")
    return payload


def load_adaptive_source_state(
    path: Path = DEFAULT_ADAPTIVE_SOURCE_STATE_PATH,
) -> dict[str, Any]:
    if not path.exists():
        return _empty_state_payload()
    return validate_adaptive_source_state_payload(json.loads(path.read_text(encoding="utf-8")))


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


def write_adaptive_source_state(path: Path, payload: Mapping[str, Any]) -> None:
    validated = validate_adaptive_source_state_payload(dict(payload))
    content = json.dumps(validated, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    json.loads(content)
    _write_atomic(path, content)


def set_adaptive_source_decision(
    *,
    normalized_company_key: str,
    decision: str,
    company_name: str | None = None,
    path: Path = DEFAULT_ADAPTIVE_SOURCE_STATE_PATH,
) -> dict[str, Any]:
    key = normalize_company_key(normalized_company_key)
    if not key:
        raise ValueError("normalized_company_key must not be blank")
    normalized_decision = validate_decision(decision)
    payload = load_adaptive_source_state(path)
    decisions = dict(payload["decisions"])
    previous = decisions.get(key)
    record = {
        "decision": normalized_decision,
        "company_name": (company_name or key).strip(),
        "updated_at_utc": _utc_timestamp(),
    }
    if isinstance(previous, Mapping):
        first_seen = previous.get("first_seen_utc")
        if isinstance(first_seen, str) and first_seen.strip():
            record["first_seen_utc"] = first_seen
    record.setdefault("first_seen_utc", record["updated_at_utc"])
    decisions[key] = record
    updated = {"schema_version": STATE_SCHEMA_VERSION, "decisions": decisions}
    write_adaptive_source_state(path, updated)
    return updated


def _state_for_key(key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions")
    if not isinstance(decisions, Mapping):
        return {"decision": "UNREVIEWED"}
    record = decisions.get(key)
    if not isinstance(record, Mapping):
        return {"decision": "UNREVIEWED"}
    decision = record.get("decision")
    if not isinstance(decision, str) or decision not in VALID_DECISIONS:
        return {"decision": "UNREVIEWED"}
    return dict(record)


def _provenance_by_source_file(
    provenance: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in provenance:
        source_file = record.get("source_file")
        if isinstance(source_file, str) and source_file:
            result[source_file] = record
    return result


def _configured_company_keys(strategies: Sequence[CareerSourceStrategy]) -> set[str]:
    keys: set[str] = set()
    for strategy in strategies:
        key = normalize_company_key(strategy.company_name)
        if key:
            keys.add(key)
        source_tail = strategy.source_name.split(":", 1)[-1].replace("_", " ")
        source_key = normalize_company_key(source_tail)
        if source_key:
            keys.add(source_key)
    return keys


def _source_role_for_provenance(
    provenance: Mapping[str, Any],
    strategy_by_source: Mapping[str, CareerSourceStrategy],
) -> str:
    source_name = _text(provenance.get("source_name"))
    strategy = strategy_by_source.get(source_name)
    if strategy is not None:
        return strategy.source_role
    canonical_type = _text(provenance.get("canonical_source_type")).casefold()
    if any(token in canonical_type for token in ("aggregator", "discovery", "listing")):
        return "discovery"
    if any(token in canonical_type for token in ("employer", "career", "origin")):
        return "employer_origin"
    return "unknown"


def _evidence_quality(provenance: Mapping[str, Any]) -> str:
    quality = _text(provenance.get("description_quality")).casefold()
    return quality if quality in {"strong", "weak", "missing"} else "unknown"


def _location_text(opportunity: Mapping[str, Any], provenance: Mapping[str, Any]) -> str:
    values = [
        opportunity.get("title"),
        opportunity.get("company"),
        provenance.get("source_url"),
        provenance.get("canonical_key_candidate"),
    ]
    return " ".join(_text(value) for value in values).casefold()


def _recommendation_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(_text(row.get("recommendation")) for row in rows)
    return {name: counter.get(name, 0) for name in RECOMMENDATION_GROUPS}


def _main_lanes(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    counter = Counter(
        _text(row.get("career_lane")) for row in rows if _text(row.get("career_lane"))
    )
    return [
        lane
        for lane, _count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _score(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _location_flags(
    rows: Sequence[Mapping[str, Any]],
    provenance_by_source: Mapping[str, Mapping[str, Any]],
    rules: AdaptiveSourceRules,
) -> tuple[bool, bool, bool]:
    berlin = False
    remote = False
    conflict = False
    for row in rows:
        provenance = provenance_by_source.get(_text(row.get("source_file")), {})
        haystack = _location_text(row, provenance)
        berlin = berlin or any(term in haystack for term in rules.berlin_terms)
        remote = remote or any(term in haystack for term in rules.remote_germany_terms)
        conflict = conflict or any(term in haystack for term in rules.conflict_terms)
    return berlin, remote, conflict


def _date_value(provenance: Mapping[str, Any]) -> str | None:
    for key in ("observed_at", "created_at", "updated_at", "ingested_at"):
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _suggestion(
    *,
    observed: int,
    assessed: int,
    highest_score: int,
    average_score: float,
    lanes: Sequence[str],
    recommendations: Mapping[str, int],
    berlin_relevance: bool,
    remote_germany_relevance: bool,
    location_conflict: bool,
    evidence_quality: str,
    employer_origin_available: bool,
    discovery_available: bool,
    rules: AdaptiveSourceRules,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    observed_label = "opportunity" if observed == 1 else "opportunities"
    reasons.append(f"{observed} observed {observed_label}")
    if assessed:
        assessment_label = "assessment" if assessed == 1 else "assessments"
        reasons.append(f"{assessed} Career Intelligence {assessment_label}")
        reasons.append(f"best Career Intelligence score {highest_score}")
        reasons.append(f"average Career Intelligence score {average_score:.1f}")
    if recommendations.get("APPLY_NOW"):
        reasons.append(f"{recommendations['APPLY_NOW']} opportunities recommended APPLY_NOW")
    if recommendations.get("NETWORK_FIRST"):
        reasons.append(
            f"{recommendations['NETWORK_FIRST']} opportunities recommended NETWORK_FIRST"
        )
    if berlin_relevance:
        reasons.append("Berlin-compatible roles observed")
    if remote_germany_relevance:
        reasons.append("remote Germany-compatible roles observed")
    if location_conflict:
        reasons.append("location constraint conflict detected")
    if employer_origin_available:
        reasons.append("employer-origin evidence available")
    if discovery_available and not employer_origin_available:
        reasons.append("only discovery-source evidence available")
    if evidence_quality != "strong":
        reasons.append(f"{evidence_quality} evidence quality")

    lane_set = {lane.casefold() for lane in lanes}
    primary_hits = len(lane_set.intersection(rules.primary_lanes))
    relevant_hits = len(
        lane_set.intersection((*rules.primary_lanes, *rules.adjacent_lanes))
    )
    if primary_hits:
        reasons.append(
            "primary career lane repeatedly matched"
            if primary_hits > 1
            else "primary career lane matched"
        )
    elif relevant_hits:
        reasons.append("adjacent career lane matched")

    compatible_location = (berlin_relevance or remote_germany_relevance) and not location_conflict
    ignore = rules.thresholds["ignore"]
    if location_conflict and bool(ignore.get("location_conflict_is_ignore")):
        return "IGNORE", reasons
    if observed >= int(ignore["min_observed_opportunities"]) and highest_score <= int(
        ignore["max_highest_score"]
    ):
        return "IGNORE", reasons

    tier_a = rules.thresholds["promote_tier_a"]
    if (
        observed >= int(tier_a["min_observed_opportunities"])
        and assessed >= int(tier_a["min_assessed_opportunities"])
        and highest_score >= int(tier_a["min_highest_score"])
        and average_score >= float(tier_a["min_average_score"])
        and primary_hits >= int(tier_a["min_primary_lane_hits"])
        and (compatible_location or not bool(tier_a.get("require_location_compatible")))
        and evidence_quality == "strong"
        and employer_origin_available
    ):
        return "PROMOTE_TO_TIER_A", reasons

    tier_b = rules.thresholds["promote_tier_b"]
    if (
        observed >= int(tier_b["min_observed_opportunities"])
        and assessed >= int(tier_b["min_assessed_opportunities"])
        and highest_score >= int(tier_b["min_highest_score"])
        and average_score >= float(tier_b["min_average_score"])
        and relevant_hits >= int(tier_b["min_relevant_lane_hits"])
        and (compatible_location or not bool(tier_b.get("require_location_compatible")))
        and evidence_quality in {"strong", "mixed"}
    ):
        return "PROMOTE_TO_TIER_B", reasons

    return "WATCH", reasons


def derive_adaptive_source_candidates(
    opportunities: Sequence[Mapping[str, Any]],
    provenance: Sequence[Mapping[str, Any]],
    *,
    strategies: Sequence[CareerSourceStrategy],
    rules: AdaptiveSourceRules,
    state_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    provenance_by_source = _provenance_by_source_file(provenance)
    configured_keys = _configured_company_keys(strategies)
    strategy_by_source = {strategy.source_name: strategy for strategy in strategies}
    by_company: dict[str, list[Mapping[str, Any]]] = {}
    for opportunity in opportunities:
        company = _text(opportunity.get("company"))
        key = normalize_company_key(company)
        if not key or key in configured_keys:
            continue
        by_company.setdefault(key, []).append(opportunity)

    candidates: list[dict[str, Any]] = []
    state_payload = state_payload or _empty_state_payload()
    for key, rows in by_company.items():
        scores = [_score(row.get("opportunity_score")) for row in rows]
        assessed = sum(
            1 for row in rows if _text(row.get("recommendation")) in RECOMMENDATION_GROUPS
        )
        highest_score = max(scores) if scores else 0
        average_score = sum(scores) / len(scores) if scores else 0.0
        recommendations = _recommendation_distribution(rows)
        lanes = _main_lanes(rows)
        berlin, remote_germany, location_conflict = _location_flags(
            rows,
            provenance_by_source,
            rules,
        )
        source_roles = [
            _source_role_for_provenance(
                provenance_by_source.get(_text(row.get("source_file")), {}),
                strategy_by_source,
            )
            for row in rows
        ]
        qualities = [
            _evidence_quality(
                provenance_by_source.get(_text(row.get("source_file")), {})
            )
            for row in rows
        ]
        quality_set = set(qualities)
        evidence_quality = (
            "strong"
            if quality_set == {"strong"}
            else (
                "mixed"
                if "strong" in quality_set
                else (qualities[0] if qualities else "unknown")
            )
        )
        employer_origin = "employer_origin" in source_roles
        discovery = "discovery" in source_roles
        suggestion, reasons = _suggestion(
            observed=len(rows),
            assessed=assessed,
            highest_score=highest_score,
            average_score=average_score,
            lanes=lanes,
            recommendations=recommendations,
            berlin_relevance=berlin,
            remote_germany_relevance=remote_germany,
            location_conflict=location_conflict,
            evidence_quality=evidence_quality,
            employer_origin_available=employer_origin,
            discovery_available=discovery,
            rules=rules,
        )
        dates = [
            value
            for row in rows
            if (value := _date_value(provenance_by_source.get(_text(row.get("source_file")), {})))
        ]
        state = _state_for_key(key, state_payload)
        company_names = Counter(_text(row.get("company")) for row in rows)
        company_name = sorted(company_names.items(), key=lambda item: (-item[1], item[0]))[0][0]
        candidates.append(
            {
                "company_name": company_name,
                "normalized_company_key": key,
                "observed_opportunity_count": len(rows),
                "assessed_opportunity_count": assessed,
                "highest_opportunity_score": highest_score,
                "average_opportunity_score": round(average_score, 1),
                "recommendations_distribution": recommendations,
                "career_lanes": lanes,
                "berlin_relevance": berlin,
                "remote_germany_relevance": remote_germany,
                "location_constraint_conflicts": location_conflict,
                "evidence_quality": evidence_quality,
                "employer_origin_evidence_available": employer_origin,
                "discovery_source_evidence_available": discovery,
                "network_relevance": None,
                "first_seen": min(dates) if dates else None,
                "last_seen": max(dates) if dates else None,
                "suggested_action": suggestion,
                "operator_decision": state.get("decision", "UNREVIEWED"),
                "operator_decision_updated_at_utc": state.get("updated_at_utc"),
                "source_strategy_status": "adaptive_candidate",
                "promotion_reasons": reasons,
            }
        )

    candidates.sort(
        key=lambda item: (
            VALID_SUGGESTIONS.index(str(item["suggested_action"])),
            -int(item["highest_opportunity_score"]),
            -float(item["average_opportunity_score"]),
            str(item["company_name"]).casefold(),
        )
    )
    return candidates


def derive_source_advisories(
    opportunities: Sequence[Mapping[str, Any]],
    provenance: Sequence[Mapping[str, Any]],
    *,
    strategies: Sequence[CareerSourceStrategy],
) -> dict[str, dict[str, Any]]:
    provenance_by_source = _provenance_by_source_file(provenance)
    rows_by_key: dict[str, list[Mapping[str, Any]]] = {}
    for opportunity in opportunities:
        key = normalize_company_key(_text(opportunity.get("company")))
        rows_by_key.setdefault(key, []).append(opportunity)

    advisories: dict[str, dict[str, Any]] = {}
    for strategy in strategies:
        key = normalize_company_key(strategy.company_name)
        rows = rows_by_key.get(key, [])
        scores = [_score(row.get("opportunity_score")) for row in rows]
        qualities = [
            _evidence_quality(provenance_by_source.get(_text(row.get("source_file")), {}))
            for row in rows
        ]
        if not rows:
            status = "NO_RECENT_SIGNAL"
            reasons = ["no Career Intelligence opportunities observed"]
        elif max(scores) < 50:
            status = "LOW_RELEVANCE"
            reasons = [f"best Career Intelligence score {max(scores)}"]
        elif len(rows) == 1:
            status = "LOW_ACTIVITY"
            reasons = ["1 observed opportunity"]
        elif "strong" not in qualities:
            status = "REVIEW_RECOMMENDED"
            reasons = ["no strong description evidence observed"]
        else:
            status = "HEALTHY"
            reasons = [
                f"{len(rows)} observed opportunities",
                f"best Career Intelligence score {max(scores)}",
            ]
        advisories[strategy.source_name] = {
            "status": status,
            "observed_opportunity_count": len(rows),
            "best_score": max(scores) if scores else None,
            "reasons": reasons,
            "automatic_downgrade": False,
        }
    return advisories


def load_adaptive_source_read_model(
    *,
    results: Path = DEFAULT_RESULTS_PATH,
    strategy_path: Path = DEFAULT_SOURCE_STRATEGY_PATH,
    rules_path: Path = DEFAULT_ADAPTIVE_RULES_PATH,
    state_path: Path = DEFAULT_ADAPTIVE_SOURCE_STATE_PATH,
) -> dict[str, Any]:
    try:
        opportunities = _load_existing_results(results / "opportunities.json")
        provenance = _load_existing_provenance(results / PROVENANCE_FILE)
        strategies = load_source_strategy(strategy_path)
        rules = load_adaptive_source_rules(rules_path)
        state_payload = load_adaptive_source_state(state_path)
        candidates = derive_adaptive_source_candidates(
            opportunities,
            provenance,
            strategies=strategies,
            rules=rules,
            state_payload=state_payload,
        )
        advisories = derive_source_advisories(
            opportunities,
            provenance,
            strategies=strategies,
        )
    except Exception as exc:
        return {
            "available": False,
            "status": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "candidates": [],
            "source_advisories": {},
            "summary": {
                "candidate_count": 0,
                "promotion_candidate_count": 0,
                "watch_candidate_count": 0,
                "ignored_candidate_count": 0,
                "review_recommended_source_count": 0,
            },
        }

    return {
        "available": True,
        "status": "ready",
        "reason": None,
        "state_action_path": "/api/v1/career-intelligence/adaptive-sources",
        "candidates": candidates,
        "source_advisories": advisories,
        "summary": {
            "candidate_count": len(candidates),
            "promotion_candidate_count": sum(
                candidate["suggested_action"] in {"PROMOTE_TO_TIER_A", "PROMOTE_TO_TIER_B"}
                for candidate in candidates
            ),
            "watch_candidate_count": sum(
                candidate["suggested_action"] == "WATCH" for candidate in candidates
            ),
            "ignored_candidate_count": sum(
                candidate["operator_decision"] == "IGNORED" for candidate in candidates
            ),
            "review_recommended_source_count": sum(
                advisory["status"] == "REVIEW_RECOMMENDED"
                for advisory in advisories.values()
            ),
        },
        "boundaries": {
            "adaptive_sources_are_candidates_only": True,
            "curated_source_strategy_remains_authority": True,
            "no_connector_activation": True,
            "no_connector_registration": True,
            "no_provider_requests": True,
            "no_product_v1_ranking_authority": True,
            "no_scoring_redesign": True,
        },
    }


__all__ = [
    "DEFAULT_ADAPTIVE_RULES_PATH",
    "DEFAULT_ADAPTIVE_SOURCE_STATE_PATH",
    "VALID_DECISIONS",
    "VALID_SUGGESTIONS",
    "derive_adaptive_source_candidates",
    "derive_source_advisories",
    "load_adaptive_source_read_model",
    "load_adaptive_source_rules",
    "load_adaptive_source_state",
    "normalize_company_key",
    "set_adaptive_source_decision",
    "validate_adaptive_source_state_payload",
    "validate_decision",
    "write_adaptive_source_state",
]
