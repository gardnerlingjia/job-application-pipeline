"""Lingjia-specific source strategy read model for Career Intelligence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import yaml


DEFAULT_SOURCE_STRATEGY_PATH = Path("config/career_source_strategy.yaml")
SCHEMA_VERSION = "career_intelligence.source_strategy.v1"
VALID_TIERS = ("A", "B", "C")
VALID_ROLES = ("employer_origin", "discovery")
VALID_STATUSES = ("active", "watch", "inactive")


class ConnectorRegistryLike(Protocol):
    def create(self, source_name: str) -> object: ...


@dataclass(frozen=True)
class CareerSourceStrategy:
    company_name: str
    source_name: str
    tier: str
    strategic_priority: int
    relevant_career_lanes: tuple[str, ...]
    preferred_evidence_type: str
    source_role: str
    location_relevance: tuple[str, ...]
    status: str

    @property
    def tier_label(self) -> str:
        if self.tier == "A":
            return "Strategic employer"
        if self.tier == "B":
            return "Adjacent employer"
        return "Discovery source"


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source strategy record missing {field}")
    return value.strip()


def _text_tuple(record: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = record.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"source strategy record {record.get('source_name')} missing {field}")
    result = tuple(str(item).strip() for item in value if str(item).strip())
    if not result:
        raise ValueError(f"source strategy record {record.get('source_name')} has empty {field}")
    return result


def strategy_from_mapping(record: Mapping[str, Any]) -> CareerSourceStrategy:
    source_name = _required_text(record, "source_name")
    tier = _required_text(record, "tier").upper()
    if tier not in VALID_TIERS:
        raise ValueError(f"source strategy record {source_name} has invalid tier")
    role = _required_text(record, "source_role")
    if role not in VALID_ROLES:
        raise ValueError(f"source strategy record {source_name} has invalid source_role")
    status = _required_text(record, "status")
    if status not in VALID_STATUSES:
        raise ValueError(f"source strategy record {source_name} has invalid status")
    try:
        priority = int(record["strategic_priority"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"source strategy record {source_name} has invalid priority") from exc
    if priority < 0 or priority > 100:
        raise ValueError(f"source strategy record {source_name} priority must be 0-100")
    if tier == "C" and role != "discovery":
        raise ValueError(f"Tier C source strategy record {source_name} must be discovery")
    if tier in {"A", "B"} and role != "employer_origin":
        raise ValueError(
            f"Tier {tier} source strategy record {source_name} must be employer_origin"
        )
    return CareerSourceStrategy(
        company_name=_required_text(record, "company_name"),
        source_name=source_name,
        tier=tier,
        strategic_priority=priority,
        relevant_career_lanes=_text_tuple(record, "relevant_career_lanes"),
        preferred_evidence_type=_required_text(record, "preferred_evidence_type"),
        source_role=role,
        location_relevance=tuple(
            str(item).strip()
            for item in record.get("location_relevance", [])
            if str(item).strip()
        ),
        status=status,
    )


def load_source_strategy(
    path: Path = DEFAULT_SOURCE_STRATEGY_PATH,
) -> list[CareerSourceStrategy]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("career source strategy must be a YAML mapping")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported career source strategy schema version")
    records = payload.get("source_strategy")
    if not isinstance(records, list) or not records:
        raise ValueError("career source strategy must contain source_strategy records")
    strategies = [
        strategy_from_mapping(record)
        for record in records
        if isinstance(record, Mapping)
    ]
    if len(strategies) != len(records):
        raise ValueError("career source strategy records must be mappings")
    source_names = [record.source_name for record in strategies]
    duplicates = sorted(name for name, count in Counter(source_names).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate career source strategy source_name: {', '.join(duplicates)}")
    return sorted(strategies, key=lambda item: (-item.strategic_priority, item.source_name))


def _source_name(source: Mapping[str, Any]) -> str:
    return str(source.get("source_name") or "").strip()


def _registry_support(
    registry: ConnectorRegistryLike | None,
    source_name: str,
) -> dict[str, Any]:
    if registry is None:
        return {
            "code_backed_registered": False,
            "registration_status": "unknown",
            "connector_class": None,
        }
    try:
        connector = registry.create(source_name)
    except ValueError as exc:
        return {
            "code_backed_registered": False,
            "registration_status": "not_registered",
            "connector_class": None,
            "registration_detail": str(exc),
        }
    connector_type = type(connector)
    return {
        "code_backed_registered": True,
        "registration_status": "registered",
        "connector_class": f"{connector_type.__module__}.{connector_type.__name__}",
    }


def _strategy_payload(strategy: CareerSourceStrategy) -> dict[str, Any]:
    return {
        "company_name": strategy.company_name,
        "source_name": strategy.source_name,
        "tier": strategy.tier,
        "tier_label": strategy.tier_label,
        "strategic_priority": strategy.strategic_priority,
        "relevant_career_lanes": list(strategy.relevant_career_lanes),
        "preferred_evidence_type": strategy.preferred_evidence_type,
        "source_role": strategy.source_role,
        "is_employer_origin": strategy.source_role == "employer_origin",
        "is_discovery": strategy.source_role == "discovery",
        "location_relevance": list(strategy.location_relevance),
        "status": strategy.status,
        "career_relevance": (
            "high"
            if strategy.tier == "A"
            else ("medium" if strategy.tier == "B" else "discovery")
        ),
    }


def _source_status(source: Mapping[str, Any], strategy: CareerSourceStrategy) -> str:
    active = source.get("activation")
    connector = source.get("connector")
    gates = source.get("gates")
    if isinstance(active, Mapping) and active.get("active") is True:
        return "active"
    if isinstance(connector, Mapping) and connector.get("code_backed_registered") is not True:
        return "connector_gap"
    validation_passed = (
        isinstance(gates, Mapping)
        and isinstance(gates.get("connector_validation_gate"), Mapping)
        and gates["connector_validation_gate"].get("passed") is True
    )
    if not validation_passed and strategy.source_role == "employer_origin":
        return "candidate_source_gap"
    return "watch" if strategy.status == "watch" else "configured_not_active"


def _gap_source(
    strategy: CareerSourceStrategy,
    *,
    registry: ConnectorRegistryLike | None,
) -> dict[str, Any]:
    registration = _registry_support(registry, strategy.source_name)
    registered = registration["code_backed_registered"] is True
    return {
        "candidate_id": None,
        "source_name": strategy.source_name,
        "source_label": strategy.company_name,
        "source_type": "configured_career_strategy_gap",
        "candidate_status": "not_created",
        "connector": {
            "implemented": registered,
            "implementation_status": "implemented" if registered else "not_implemented",
            "implementation_truth_source": (
                "runtime_registry" if registered else "career_source_strategy"
            ),
            "code_backed_registered": registered,
            "registration_status": registration["registration_status"],
            "connector_class": registration["connector_class"],
            "registration_error": None,
        },
        "gates": {
            "connector_validation_gate": {
                "status": "unknown",
                "decision": None,
                "passed": False,
                "truth_source": "unknown",
            },
            "final_approval_gate": {
                "status": "unknown",
                "decision": None,
                "passed": False,
                "truth_source": "unknown",
            },
        },
        "activation": {
            "status": "not_activated",
            "active": False,
            "truth_source": "career_source_strategy",
            "truth_available": True,
        },
        "search_profiles": {
            "status": "not_configured",
            "profile_count": 0,
            "active_profile_count": 0,
            "active_search_term_count": 0,
            "truth_source": "search_profiles/search_terms",
            "truth_available": True,
        },
        "last_ingestion": {
            "status": "not_run",
            "started_at": None,
            "finished_at": None,
            "total_loaded": 0,
            "inserted_count": 0,
            "error_message": None,
            "truth_source": "ingestion_runs",
            "truth_available": True,
        },
        "layers": {
            "status": "no_ingestion",
            "bronze_present": False,
            "bronze_count": 0,
            "silver_present": False,
            "silver_count": 0,
            "truth_source": "raw_jobs/silver_jobs",
            "bronze_truth_available": True,
            "silver_truth_available": True,
        },
        "lifecycle": {
            "implementation": "implemented" if registered else "not_implemented",
            "validation": "unknown",
            "final_approval": "unknown",
            "registration": "registered" if registered else "not_registered",
            "activation": "not_activated",
            "ingestion": "not_ingested",
        },
        "inconsistencies": [],
        "current_blocker": "candidate_source_gap",
        "next_action": "Create and validate a bounded employer-origin source candidate"
        if strategy.source_role == "employer_origin"
        else "Configure controlled discovery source profile if needed",
    }


def enrich_source_overview_with_strategy(
    overview: Mapping[str, Any],
    *,
    strategies: Sequence[CareerSourceStrategy] | None = None,
    strategy_path: Path = DEFAULT_SOURCE_STRATEGY_PATH,
    registry: ConnectorRegistryLike | None = None,
    adaptive_read_model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decorate the existing source overview with Lingjia strategy metadata."""

    strategy_rows = (
        list(strategies) if strategies is not None else load_source_strategy(strategy_path)
    )
    if adaptive_read_model is None:
        from src.career_intelligence.adaptive_sources import load_adaptive_source_read_model

        adaptive_read_model = load_adaptive_source_read_model(strategy_path=strategy_path)
    source_advisories = adaptive_read_model.get("source_advisories")
    if not isinstance(source_advisories, Mapping):
        source_advisories = {}
    strategy_by_source = {item.source_name: item for item in strategy_rows}
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in overview.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        copied = dict(source)
        source_name = _source_name(copied)
        strategy = strategy_by_source.get(source_name)
        if strategy is None:
            copied["career_source_strategy"] = {
                "configured": False,
                "strategy_group": "Existing generic/demo sources",
                "source_role": "generic",
                "is_employer_origin": False,
                "is_discovery": False,
                "source_status": "existing_generic",
            }
        else:
            strategy_payload = _strategy_payload(strategy)
            strategy_payload["configured"] = True
            strategy_payload["strategy_group"] = strategy.tier_label
            strategy_payload["source_status"] = _source_status(copied, strategy)
            copied["career_source_strategy"] = strategy_payload
            copied["source_label"] = strategy.company_name
            copied["career_source_advisory"] = dict(
                source_advisories.get(strategy.source_name) or {}
            )
        sources.append(copied)
        if source_name:
            seen.add(source_name)

    for strategy in strategy_rows:
        if strategy.source_name in seen:
            continue
        gap = _gap_source(strategy, registry=registry)
        strategy_payload = _strategy_payload(strategy)
        strategy_payload["configured"] = True
        strategy_payload["strategy_group"] = strategy.tier_label
        strategy_payload["source_status"] = (
            "connector_supported_unconfigured"
            if gap["connector"]["code_backed_registered"]
            else "connector_gap"
        )
        gap["career_source_strategy"] = strategy_payload
        gap["career_source_advisory"] = dict(
            source_advisories.get(strategy.source_name) or {}
        )
        sources.append(gap)

    sources.sort(
        key=lambda source: (
            0 if source["career_source_strategy"].get("configured") else 1,
            str(source["career_source_strategy"].get("tier") or "Z"),
            -int(source["career_source_strategy"].get("strategic_priority") or 0),
            str(source.get("source_label") or "").casefold(),
            str(source.get("source_name") or "").casefold(),
        )
    )
    summary = dict(overview.get("summary") or {})
    adaptive_candidates = adaptive_read_model.get("candidates")
    if not isinstance(adaptive_candidates, list):
        adaptive_candidates = []
    adaptive_summary = adaptive_read_model.get("summary")
    if not isinstance(adaptive_summary, Mapping):
        adaptive_summary = {}
    configured_sources = [
        source for source in sources if source["career_source_strategy"].get("configured") is True
    ]
    summary.update(
        {
            "career_strategy_source_count": len(configured_sources),
            "career_strategy_tier_a_count": sum(
                source["career_source_strategy"].get("tier") == "A"
                for source in configured_sources
            ),
            "career_strategy_tier_b_count": sum(
                source["career_source_strategy"].get("tier") == "B"
                for source in configured_sources
            ),
            "career_strategy_discovery_count": sum(
                source["career_source_strategy"].get("source_role") == "discovery"
                for source in configured_sources
            ),
            "career_strategy_gap_count": sum(
                source["career_source_strategy"].get("source_status")
                in {"connector_gap", "candidate_source_gap", "connector_supported_unconfigured"}
                for source in configured_sources
            ),
            "generic_demo_source_count": sum(
                source["career_source_strategy"].get("configured") is False
                for source in sources
            ),
            "adaptive_source_candidate_count": len(adaptive_candidates),
            "adaptive_source_promotion_candidate_count": adaptive_summary.get(
                "promotion_candidate_count",
                0,
            ),
        }
    )
    result = dict(overview)
    result["sources"] = sources
    result["summary"] = summary
    boundaries = dict(result.get("boundaries") or {})
    boundaries.update(
        {
            "career_source_strategy_is_prioritization_only": True,
            "career_source_strategy_does_not_activate_connectors": True,
            "employer_origin_preferred_over_discovery_for_career_evidence": True,
            "generic_demo_sources_preserved": True,
            "adaptive_sources_are_candidates_only": True,
            "adaptive_sources_do_not_activate_connectors": True,
            "adaptive_sources_do_not_mutate_product_v1_ranking": True,
        }
    )
    result["boundaries"] = boundaries
    result["adaptive_source_discovery"] = dict(adaptive_read_model)
    result["career_source_strategy"] = {
        "schema_version": SCHEMA_VERSION,
        "owner": "lingjia_gardner",
        "source": str(strategy_path),
        "groups": {
            "strategic_employers": summary["career_strategy_tier_a_count"],
            "adjacent_employers": summary["career_strategy_tier_b_count"],
            "discovery_sources": summary["career_strategy_discovery_count"],
            "existing_generic_demo_sources": summary["generic_demo_source_count"],
        },
    }
    return result


__all__ = [
    "CareerSourceStrategy",
    "DEFAULT_SOURCE_STRATEGY_PATH",
    "SCHEMA_VERSION",
    "enrich_source_overview_with_strategy",
    "load_source_strategy",
    "strategy_from_mapping",
]
