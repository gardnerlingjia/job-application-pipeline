"""Read-only market visibility over persisted Career Intelligence vacancies.

This module applies the existing title relevance gate for discovery triage only.
It does not run scoring, career eligibility, or operator-state transitions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from psycopg.rows import dict_row

from src.career_intelligence.role_relevance import RoleRelevanceGate


GEOGRAPHIES = ("Germany", "Berlin", "Other Europe", "US", "Other international", "Unknown")


def production_strategy() -> str:
    """Deployment selection; omission retains the V3.3 rollback default."""
    strategy = os.environ.get("CAREER_INTELLIGENCE_STRATEGY", "v3.3")
    if strategy not in {"v3.3", "v3.4"}:
        raise ValueError("Unknown production career strategy")
    return strategy


def _geography(text: str) -> str:
    value = text.casefold()
    if any(term in value for term in (
        "berlin", "germany", "deutschland", "hamburg", "munich", "münchen", "frankfurt",
        "stuttgart", "cologne", "köln", "düsseldorf", "dortmund", "planegg", "dornstadt",
        "schönefeld",
    )):
        return "Germany"
    if any(term in value for term in (
        "united states", "usa", "u.s.", "california", "mountain view", "san francisco",
        "new york", "seattle", "texas", "washington",
    )):
        return "US"
    if any(term in value for term in (
        "united kingdom", "uk", "london", "france", "paris", "netherlands", "amsterdam",
        "sweden", "stockholm", "switzerland", "zurich", "zürich", "austria", "vienna",
        "denmark", "copenhagen", "belgium", "brussels", "spain", "madrid", "italy", "milan",
        "poland", "warsaw", "finland", "norway", "ireland", "portugal",
    )):
        return "Other Europe"
    if any(term in value for term in (
        "japan", "fukuoka", "singapore", "canada", "india", "taiwan", "australia", "china",
    )):
        return "Other international"
    return "Unknown"


def _locations(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("locations")
    if isinstance(raw, list):
        values = [str(value).strip() for value in raw if str(value).strip()]
    else:
        values = []
    if not values and row.get("location_text"):
        values = [str(row["location_text"]).strip()]
    return list(dict.fromkeys(values))


def _role_family(reason: str, matched_rule: str | None) -> str:
    if reason == "EXCLUDED_JUNIOR":
        return "Junior / early career"
    if reason == "EXCLUDED_TECHNICIAN":
        return "Technician / hands-on trade"
    if reason == "EXCLUDED_ENGINEERING":
        return "Individual contributor engineering"
    if reason == "AMBIGUOUS_REVIEW":
        return "Ambiguous / other"
    rule = (matched_rule or "").casefold()
    if any(term in rule for term in ("product", "transformation", "digital")):
        return "Product / digital leadership"
    return "Program / delivery / operations leadership"


def _json_value(value: Any) -> Any:
    """Convert database temporal values to JSON-safe ISO strings."""
    return value.isoformat() if hasattr(value, "isoformat") else value


def build_market_intelligence(
    rows: Iterable[Mapping[str, Any]], *, gate: RoleRelevanceGate | None = None,
    strategy_version: str = "v3.3", candidate_facts_path: Path | None = None,
) -> dict[str, Any]:
    """Build summaries and gate explanations from actual, non-removed vacancies."""
    role_gate = gate or RoleRelevanceGate()
    if strategy_version not in {"v3.3", "v3.4"}:
        raise ValueError("Unknown career strategy")
    strategy = candidate = None
    if strategy_version == "v3.4":
        from src.career_intelligence.competency_qualification import (
            load_candidate_evidence, load_strategy,
        )
        strategy = load_strategy()
        candidate = load_candidate_evidence(strategy, candidate_facts_path)
    review_notes = {}
    if strategy and strategy.get("preview_job_evidence_file"):
        review_path = Path(__file__).resolve().parents[2] / strategy["preview_job_evidence_file"]
        if review_path.exists():
            review_notes = json.loads(review_path.read_text(encoding="utf-8")).get("vacancies", {})
    vacancies: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    geo_counts: dict[str, set[str]] = {name: set() for name in GEOGRAPHIES}
    employer_counts: dict[str, Counter[str]] = defaultdict(Counter)
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("vacancy_type", "actual_vacancy") != "actual_vacancy":
            continue
        if row.get("lifecycle_status", "active") == "removed":
            continue
        title = str(row.get("title") or "")
        decision = role_gate.decide(title)
        places = _locations(row)
        buckets = {_geography(place) for place in places} or {"Unknown"}
        if any("berlin" in place.casefold() for place in places):
            buckets.add("Berlin")
        role_family = _role_family(decision.reason, decision.matched_rule)
        company = str(row.get("company_name") or "Unknown employer")
        identifier = str(row.get("vacancy_id") or row.get("id") or "")
        reasons[decision.reason] += 1
        for bucket in buckets:
            geo_counts[bucket].add(identifier)
        employer_counts[company][decision.reason] += 1
        family_counts[role_family][decision.reason] += 1
        vacancies.append({
            "vacancy_id": identifier,
            "company": company,
            "title": title,
            "locations": places,
            "geographies": sorted(buckets, key=GEOGRAPHIES.index),
            "gate_reason": decision.reason,
            "matched_rule": decision.matched_rule,
            "role_family": role_family,
            "why": (
                f"Title matched configured rule: {decision.matched_rule}"
                if decision.matched_rule else
                "Title did not match a configured relevant or exclusion rule; review is ambiguous."
            ),
            "source_key": row.get("source_key"),
            "source_job_id": row.get("source_job_id"),
            "source_url": row.get("source_url"),
            "publication_at": _json_value(row.get("publication_at")),
            "source_updated_at": _json_value(row.get("source_updated_at")),
            "first_seen_at": _json_value(row.get("first_seen_at")),
            "last_seen_at": _json_value(row.get("last_seen_at")),
            "career_compatibility": "not_assessed",
        })
        if strategy:
            from src.career_intelligence.competency_qualification import qualify_vacancy
            description, description_source = observation_description(row)
            note = review_notes.get(identifier, {})
            # Supplemental, explicitly non-authoritative review evidence. Never writes source observations.
            review_description = note.get("description", description)
            qualification = qualify_vacancy(
                {**row, "description": review_description,
                 "description_source": note.get("source_url", description_source),
                 "review_active_status": note.get("active_status", "UNKNOWN"),
                 "review_confirmed_requirement_gap": note.get("confirmed_requirement_gap"),
                 "review_life_incompatibility": note.get("life_incompatibility"),
                 "review_description_scope": note.get("description_scope", "captured_source"),
                 "employer_review": note.get("employer_review")},
                config=strategy, candidate=candidate,
            )
            vacancies[-1].update({
                "qualification": qualification, "industry": qualification["industry"],
                "industries": qualification["industries"],
                "legacy_role_family": role_family,
                "role_family": qualification["role_family"],
            })
            # Family summaries use V3.4 taxonomy, while title gate counts stay unchanged.
            family_counts[role_family][decision.reason] -= 1
            if not family_counts[role_family][decision.reason]:
                del family_counts[role_family][decision.reason]
            if not family_counts[role_family]:
                del family_counts[role_family]
            family_counts[qualification["role_family"]][decision.reason] += 1
    vacancies.sort(key=lambda item: (
        item["gate_reason"] not in {"RELEVANT_ROLE", "AMBIGUOUS_REVIEW"},
        str(item["company"]).casefold(), str(item["title"]).casefold(), item["vacancy_id"],
    ))

    def grouped(counter: Mapping[str, Counter[str]]) -> list[dict[str, Any]]:
        return [
            {"name": name, "total": sum(counts.values()), "by_gate": dict(counts)}
            for name, counts in sorted(counter.items(), key=lambda item: (
                -sum(item[1].values()), item[0].casefold(),
            ))
        ]

    result = {
        "status": "ready",
        "strategy_version": strategy_version,
        "screening_method": "existing title-only RoleRelevanceGate; no assessment or score recomputation",
        "summary": {
            "vacancy_count": len(vacancies),
            "gate_counts": {name: reasons.get(name, 0) for name in (
                "RELEVANT_ROLE", "AMBIGUOUS_REVIEW", "EXCLUDED_JUNIOR",
                "EXCLUDED_TECHNICIAN", "EXCLUDED_ENGINEERING",
            )},
            "relevance_screened_count": reasons.get("RELEVANT_ROLE", 0),
            "ambiguous_review_count": reasons.get("AMBIGUOUS_REVIEW", 0),
            "full_assessment_count": 0,
        },
        "geography": [
            {"name": name, "vacancy_count": len(geo_counts[name])}
            for name in GEOGRAPHIES
        ],
        "employers": grouped(employer_counts),
        "role_families": grouped(family_counts),
        "vacancies": vacancies,
        "boundaries": {
            "career_profile_unchanged": True,
            "scoring_unchanged": True,
            "eligibility_and_location_constraints_unchanged": True,
            "berlin_is_discovery_geography_not_eligibility": True,
            "career_compatibility_for_discovery_inventory": "not_assessed",
        },
    }
    if strategy:
        from src.career_intelligence.competency_qualification import STATUSES
        qualifications = [vacancy["qualification"] for vacancy in vacancies]
        counts = Counter(q["status"] for q in qualifications)
        industries = Counter(q["industry"] for q in qualifications)
        china = Counter(q["china_europe"]["relevance"] for q in qualifications)
        result.update({
            "screening_method": "V3.4 description qualification preview; legacy title gate retained",
            "strategy_sha256": strategy["config_sha256"],
            "candidate_verification_status": candidate["verification_status"],
            "industries": [{"name": key,
                            "label": strategy["industries"].get(key, {}).get("label", "Unknown"),
                            "vacancy_count": count} for key, count in sorted(industries.items())],
        })
        result["summary"].update({
            "qualification_counts": {key: counts.get(key, 0) for key in STATUSES},
            "assessment_eligible_count": sum(q["assessment_eligible"] for q in qualifications),
            "plausible_cross_industry_count": sum(q["plausible_cross_industry"]
                                                 for q in qualifications),
            "china_europe_counts": dict(china),
            "review_judgments": dict(Counter(q["opportunity_review"]["judgment"] for q in qualifications)),
            "excluded_internal_count": sum(not q["opportunity_review"]["discovery_eligible"]
                                           for q in qualifications),
        })
    return result


def observation_description(row: Mapping[str, Any]) -> tuple[str, str | None]:
    """Only captured source text, never title inference or generated report text."""
    if row.get("description"):
        return str(row["description"]), row.get("description_source") or row.get("source_url")
    raw = row.get("raw_payload") or {}
    detail = raw.get("_v34_detail") or {}
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    headings = {"companyDescription": "About us", "jobDescription": "Your tasks",
                "qualifications": "Requirements", "additionalInformation": "Benefits"}
    parts = [headings.get(key, key) + ":\n" + section["text"]
             for key, section in sections.items()
             if isinstance(section, dict) and isinstance(section.get("text"), str)]
    if parts:
        return "\n".join(parts), raw.get("_v34_detail_url")
    for field in ("descriptionPlain", "descriptionHtml", "content", "description",
                  "stellenbeschreibung"):
        if isinstance(raw.get(field), str) and raw[field].strip():
            return raw[field], row.get("source_url")
    return "", None


def load_market_intelligence(conn: Any, *, strategy_version: str | None = None,
                             candidate_facts_path: Path | None = None) -> dict[str, Any]:
    """Read active actual vacancy rows and latest source provenance from PostgreSQL."""
    return build_market_intelligence(load_inventory_rows(conn),
                                     strategy_version=strategy_version or production_strategy(),
                                     candidate_facts_path=candidate_facts_path)


def load_inventory_rows(conn: Any) -> list[dict[str, Any]]:
    """Shared observational inputs for dashboard and reproducible evaluations."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT v.id AS vacancy_id, v.company_name, v.title, v.location_text,
                   v.locations, v.publication_at, v.source_updated_at,
                   v.first_seen_at, v.last_seen_at,
                   latest.source_key, latest.source_job_id, latest.raw_payload,
                   latest.id AS source_observation_id,
                   COALESCE(latest.source_url, v.canonical_url) AS source_url,
                   v.vacancy_type, v.lifecycle_status
            FROM career_discovery_vacancies v
            LEFT JOIN LATERAL (
                SELECT o.source_key, o.source_job_id, o.source_url, o.raw_payload, o.id
                FROM career_discovery_observations o
                WHERE o.vacancy_id = v.id
                ORDER BY o.observed_at DESC, o.id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE v.vacancy_type = 'actual_vacancy'
              AND v.lifecycle_status <> 'removed'
            ORDER BY v.company_name, v.title, v.id
        """)
        rows = [dict(row) for row in cur.fetchall()]
    return rows
