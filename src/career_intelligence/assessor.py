from typing import Dict

from src.career_intelligence.classifier import classify_job, strategy_context, contains_term
from src.career_intelligence.constraints import evaluate_constraints
from src.career_intelligence.scoring import (
    calculate_opportunity_score,
    evidence_anchors,
)
from src.career_intelligence.recommender import recommend_strategy_action
from src.career_intelligence.capability_matcher import match_capabilities
from src.career_intelligence.domain_matcher import match_domain
from src.career_intelligence.location_matcher import match_location
from src.career_intelligence.evidence_strength import calculate_evidence_strength
from src.career_intelligence.network_matcher import match_network


def assess_opportunity(
    company_name: str,
    title: str,
    description: str,
    *,
    role_evidence: dict | None = None,
    market_evidence: dict | None = None,
) -> Dict:
    role_evidence = role_evidence or {}
    classification = classify_job(title, description)
    constraints = evaluate_constraints(title, description)
    capability_match = match_capabilities(title, description)
    evidence = calculate_evidence_strength(capability_match["matched_capabilities"])
    network_match = match_network(company_name, role_evidence=role_evidence)
    access = network_match["access_type"]
    context = strategy_context(title, description, access)
    policy = context["policy"]

    domain_match = match_domain(
        title,
        description,
        classification["career_lane"],
    )

    location_match = match_location(
        title,
        description,
    )

    # Access may make a bridge worth pursuing, but never creates candidate evidence.
    evidence_context = strategy_context(title, description)
    anchors = evidence_anchors(capability_match["matched_capabilities"], evidence_context)
    scores = {
        "career_lane_fit": anchors["career_lane_fit"],
        "capability_fit": capability_match["capability_fit"],
        "domain_fit": anchors["domain_fit"],
        "location_fit": location_match["location_fit"],
        "network_access": network_match["network_access"],
        "evidence_strength": evidence["evidence_strength"],
    }

    weighted_candidacy = calculate_opportunity_score(scores)
    text = f"{title} {description}"
    gaps = {
        name: rule["reason"]
        for name, rule in policy["gap_rules"].items()
        if any(contains_term(text, term) for term in rule["terms"])
    }
    if context["engineering_mismatch"]:
        gaps["engineering_heavy_role"] = (
            "Role requires specialist engineering beyond supported evidence."
        )
    if access == "cold":
        gaps["cold_access"] = "No documented referral, hiring-manager contact or warm access."
    if location_match.get("travel_status", "").startswith("frequent"):
        gaps["frequent_travel_conflict"] = "Required travel exceeds occasional domestic travel."
    elif location_match.get("hard_conflict"):
        gaps["relocation_conflict"] = "Required presence conflicts with Berlin-region constraints."
    if location_match.get("travel_status") == "unknown":
        gaps["travel_unknown"] = "Travel requirements are not evidenced; confirm before applying."
    if not location_match["location_matches"]:
        gaps["location_unknown"] = "Confirm Berlin-compatible presence and travel requirements."
    market = normalize_market_evidence(market_evidence)
    exposure = market["traditional_automotive_exposure"]
    if exposure["status"] == "confirmed" and exposure["value"] is True:
        gaps["automotive_headcount_exposure"] = (
            "Confirmed traditional automotive exposure; review budget and hiring intent."
        )
    requirements = assess_role_requirements(title, description, role_evidence, context)
    blocking_gaps = {item["constraint"]: item["reason"] for item in constraints["high_risks"]}
    blocking_gaps.update(requirements["blocking_gaps"])
    for name, reason in requirements["blocking_gaps"].items():
        constraints["high_risks"].append(
            {
                "constraint": name,
                "reason": reason,
                "severity": "high",
                "action": "HIGH_RISK",
                "section": "role_requirements",
                "matches": [],
            }
        )
    if blocking_gaps and constraints["overall_action"] != "SKIP":
        constraints["overall_action"] = "HIGH_RISK"
    if context["engineering_mismatch"] or context["unsupported_leadership"]:
        blocking_gaps["decisive_capability_mismatch"] = (
            "Specialist role is outside supported evidence."
        )
    gap_cap = (
        policy["decisive_mismatch_strength_cap"]
        if context["engineering_mismatch"] or context["unsupported_leadership"]
        else policy["core_gap_strength_cap"]
        if blocking_gaps
        else 100
    )
    gap_cap = min(gap_cap, anchors["total_cap"])
    opportunity_score = round(min(weighted_candidacy, gap_cap), 1)
    candidate_strength = {
        "score": opportunity_score,
        "weighted_before_caps": weighted_candidacy,
        "anchors": anchors,
        "matched_capability_fit": scores["capability_fit"],
        "matched_evidence_strength": scores["evidence_strength"],
        "gap_cap": gap_cap,
        "blocking_gaps": blocking_gaps,
    }
    strategic_attractiveness = {
        "sufficient": context["transition"] in {"direct", "adjacent", "bridge"},
        "transition": context["transition"],
        "lane": classification["career_lane"],
        "domain_matches": context["autonomy_matches"] + context["domain_advantage_matches"],
    }
    from src.career_intelligence.classifier import load_career_profile

    strategy_lane = (
        "ai_data_transformation"
        if context["transition"] == "bridge"
        else "autonomy_robotics"
        if context["autonomy_matches"]
        else "technology_programs"
        if context["domain_advantage_matches"]
        else None
    )
    strategic_value = {
        "lane": strategy_lane,
        "search_allocation_percent": load_career_profile()["career_lanes"][strategy_lane][
            "allocation_percent"
        ]
        if strategy_lane
        else 0,
        "role_alignment": strategic_attractiveness["sufficient"],
        "reason": "Search allocation and role relevance only; no contribution to candidacy.",
    }
    context["evidence_strength"] = scores["evidence_strength"]
    gaps.update(blocking_gaps)
    if requirements["commissioning_status"] == "unknown":
        gaps["commissioning_scope_unknown"] = (
            "Confirm hands-on robotics engineering/commissioning is not a core requirement."
        )
    recommendation = recommend_strategy_action(
        candidate_strength["score"],
        constraints["overall_action"],
        context,
        location_match,
        access,
        blocking_gaps,
        requirements["commissioning_status"],
    )
    if recommendation != "SKIP" and any(
        market[key]["status"] == "confirmed"
        and market[key]["value"] in ("weak", "unfunded", "frozen")
        for key in ("hiring_intent_strength", "funding_or_budget_signal")
    ):
        recommendation = "WATCH"
        gaps["hiring_budget_risk"] = (
            "Confirmed weak hiring intent or budget; verify before applying."
        )
    if location_match.get("hard_conflict") or context["transition"] == "unrealistic":
        constraints["overall_action"] = "SKIP"
        constraints["hard_skips"].append(
            {
                "constraint": "location_conflict"
                if location_match.get("hard_conflict")
                else "unsupported_role_transition",
                "reason": "Required presence conflicts with location constraints."
                if location_match.get("hard_conflict")
                else "Role requirements lack a supported direct, adjacent or selective bridge.",
                "severity": "high",
                "action": "SKIP",
                "section": "career_strategy",
                "matches": [],
            }
        )
    constraints["reviews"].extend(
        {
            "constraint": name,
            "reason": reason,
            "severity": "medium",
            "action": "REVIEW",
            "matches": [],
            "section": "career_strategy",
        }
        for name, reason in gaps.items()
    )
    explanation = {
        "semantics_version": 4,
        "score_semantics": "weighted_current_candidacy_after_caps",
        "strategic_value": strategic_value,
        "scores": scores,
        "gates": decision_gates(
            recommendation,
            constraints,
            context,
            location_match,
            requirements,
            blocking_gaps,
            gaps,
            candidate_strength,
            access,
        ),
        "candidate_strength": candidate_strength,
        "strategic_attractiveness": strategic_attractiveness,
        "role_requirements": requirements,
        "fit": context["transition"],
        "supporting_capabilities": [
            item["capability"] for item in capability_match["matched_capabilities"]
        ],
        "fit_signals": {
            key: context[key]
            for key in (
                "autonomy_matches",
                "domain_advantage_matches",
                "delivery_matches",
                "engineering_mismatch",
                "unsupported_leadership",
            )
        },
        "gaps": {
            **gaps,
            **{
                item["constraint"]: item["reason"]
                for item in constraints["hard_skips"] + constraints["high_risks"]
            },
        },
        "location": location_match,
        "access": access,
        "traditional_automotive_exposure": exposure,
        "missing_market_evidence": [
            key for key, item in market.items() if item["status"] == "unknown"
        ],
        "recommended_action": {"APPLY_NOW": "APPLY", "NETWORK_FIRST": "NETWORK FIRST"}.get(
            recommendation, recommendation
        ),
    }

    return {
        "candidate_strength": candidate_strength,
        "strategic_attractiveness": strategic_attractiveness,
        "transition": context["transition"],
        "access_type": access,
        "market_evidence": market,
        "explanation": explanation,
        "title": title,
        "career_lane": classification["career_lane"],
        "career_lane_label": classification["career_lane_label"],
        "domain_matches": domain_match["domain_matches"],
        "location_matches": location_match["location_matches"],
        "lane_score": classification["score"],
        "lane_confidence": classification["confidence"],
        "runner_up_lane": classification["runner_up_lane"],
        "runner_up_score": classification["runner_up_score"],
        "constraint_action": constraints["overall_action"],
        "boosters": constraints["boosters"],
        "company_name": company_name,
        "network_access": network_match["network_access"],
        "relationship_level": network_match["relationship_level"],
        "strategic_relevance": network_match["strategic_relevance"],
        "known_company": network_match["known_company"],
        "high_risks": constraints["high_risks"],
        "hard_skips": constraints["hard_skips"],
        "reviews": constraints["reviews"],
        "scores": scores,
        "matched_capabilities": capability_match["matched_capabilities"],
        "opportunity_score": opportunity_score,
        "evidence_details": evidence["evidence_details"],
        "recommendation": recommendation,
    }


def decision_gates(
    action, constraints, context, location, requirements, blocking, gaps, strength, access
):
    """Explain every cap and action override, including high-fit hard exclusions."""
    gates = []
    if strength["score"] < strength["weighted_before_caps"]:
        gates.append(
            {
                "gate": "candidacy_cap",
                "reason": strength["anchors"]["basis"],
                "cap": strength["gap_cap"],
                "blocking_gaps": sorted(blocking),
            }
        )
    if constraints["overall_action"] == "SKIP":
        gates.extend(
            {"gate": item["constraint"], "reason": item["reason"]}
            for item in constraints["hard_skips"]
        )
    gates.extend({"gate": key, "reason": reason} for key, reason in blocking.items())
    for key in ("location_unknown", "travel_unknown", "commissioning_scope_unknown", "hiring_budget_risk"):
        if key in gaps:
            gates.append({"gate": key, "reason": gaps[key]})
    if action == "SKIP" and not gates:
        gates.append(
            {
                "gate": "unrelated_role",
                "reason": "Role has no supported strategic transition or relevant domain.",
            }
        )
    if action == "NETWORK_FIRST":
        gates.append(
            {
                "gate": "cold_access",
                "reason": "Fit/evidence thresholds passed; access is the remaining actionable weakness.",
            }
        )
    elif action == "WATCH" and not blocking:
        gates.append(
            {
                "gate": "evidence_or_scope_review",
                "reason": "Current evidence, role scope or seniority does not yet justify APPLY.",
            }
        )
    if access != "cold":
        gates.append(
            {"gate": "adequate_access", "reason": "Confirmed access excludes NETWORK FIRST."}
        )
    if action == "APPLY_NOW":
        gates.append(
            {
                "gate": "apply_eligible",
                "reason": "Fit, evidence and location qualify; no decisive gap. Cold access need not delay this role.",
            }
        )
    return gates


def assess_role_requirements(title: str, description: str, evidence: dict, context: dict) -> dict:
    """Require sourced boolean facts for negative scope confirmation; text can reveal risk."""
    import re

    facts = evidence.get("requirements", {})
    if not isinstance(facts, dict):
        raise ValueError("role_evidence.requirements must be a mapping")
    normalized = {}
    for key in ("commercial_core", "engineering_commissioning_core", "technical_core"):
        fact = facts.get(key, {})
        if not isinstance(fact, dict):
            raise ValueError(f"{key} must be an evidence mapping")
        confirmed = (
            fact.get("status") == "confirmed"
            and isinstance(fact.get("value"), bool)
            and isinstance(fact.get("evidence_source"), str)
            and bool(fact["evidence_source"].strip())
        )
        normalized[key] = {
            "value": fact.get("value") if confirmed else None,
            "status": "confirmed" if confirmed else "unknown",
            "evidence_source": fact.get("evidence_source"),
        }
    # Preserve A.I. punctuation; sentence boundaries require whitespace after the period.
    clauses = re.split(r"[;\n]|\.\s+", f"{title}. {description}")
    matches = {}
    for category, terms in context["policy"]["core_requirement_terms"].items():
        matches[category] = [
            term
            for term in terms
            for clause in clauses
            if contains_term(clause, term)
            and not re.search(r"\b(no|not|without|rather than|optional)\b", clause, re.IGNORECASE)
        ]
    blocking = {}
    for category, fact_key in (
        ("commercial", "commercial_core"),
        ("engineering", "engineering_commissioning_core"),
        ("technical", "technical_core"),
    ):
        if matches[category] or normalized[fact_key]["value"] is True:
            blocking[f"core_{category}_gap"] = (
                f"Core {category} ownership is required but candidate evidence is missing."
            )
    robotics_experience = [
        match.group(0)
        for pattern in context["policy"].get("robotics_experience_patterns", [])
        for match in re.finditer(pattern, description, re.IGNORECASE)
    ]
    if robotics_experience:
        blocking["professional_robotics_years_missing"] = (
            "Multiple years of direct robotics-product experience required; vehicle programs are transferable only."
        )
    executive_dimensions = (
        {
            key: {
                "matches": [term for term in terms if contains_term(description, term)],
                "candidate_evidence": "unknown",
            }
            for key, terms in context["policy"].get("executive_requirement_terms", {}).items()
        }
        if context["executive_role"]
        else {}
    )
    for key in ("finance", "fundraising", "company_building", "commercial", "seniority"):
        if executive_dimensions.get(key, {}).get("matches"):
            blocking[f"executive_{key}_gap"] = (
                f"Executive {key} responsibility needs direct evidence."
            )
    status = "not_applicable"
    if context["commissioning_review_required"]:
        value = normalized["engineering_commissioning_core"]["value"]
        if "core_engineering_gap" in blocking:
            status = "core_required"
        elif value is False:
            status = "confirmed_not_core"
        else:
            status = "unknown"
    return {
        "robotics_experience_requirements": robotics_experience,
        "executive_dimensions": executive_dimensions,
        "commissioning_status": status,
        "facts": normalized,
        "requirement_matches": matches,
        "blocking_gaps": blocking,
    }


def print_assessment(result: Dict) -> None:
    print("=" * 60)
    print("OPPORTUNITY ASSESSMENT")
    print("=" * 60)

    print(f"\nRole: {result['title']}")

    print("\nCareer lane")
    print(f"  {result['career_lane_label']}")
    print(f"  Score: {result['lane_score']}")
    print(f"  Confidence: {result['lane_confidence']}")

    print(f"\nCompany: {result['company_name']}")
    print("\nNetwork")
    print(f"  Access score: {result['network_access']}")
    print(f"  Relationship: {result['relationship_level']}")
    print(f"  Strategic relevance: {result['strategic_relevance']}")

    print("\nRunner-up")
    print(f"  {result['runner_up_lane']} (score {result['runner_up_score']})")

    print("\nConstraint evaluation")
    print(f"  Overall action: {result['constraint_action']}")

    print("\nOpportunity")
    print(f"  Score: {result['opportunity_score']} / 100")
    print(f"  Recommendation: {result['recommendation']}")

    print("\nStrategy explanation")
    for key, value in result.get("explanation", {}).items():
        print(f"  {key}: {value}")

    print("\nScore breakdown")
    for name, value in result["scores"].items():
        print(f"  {name}: {value}")

    if result["boosters"]:
        print("\nPositive signals")
        for item in result["boosters"]:
            print(f"  + {item['constraint']}: {item['reason']}")

    if result["reviews"]:
        print("\nReview points")
        for item in result["reviews"]:
            print(f"  ? {item['constraint']}: {item['reason']}")

    if result["high_risks"]:
        print("\nHigh risks")
        for item in result["high_risks"]:
            print(f"  ! {item['constraint']}: {item['reason']}")

    if result["hard_skips"]:
        print("\nHard-stop reasons")
        for item in result["hard_skips"]:
            print(f"  X {item['constraint']}: {item['reason']}")

    print("\n" + "=" * 60)


def normalize_market_evidence(evidence: dict | None) -> dict:
    """Unverified facts remain unknown; no inferred/unknown market score adjustments."""
    fields = (
        "employer_segment",
        "traditional_automotive_exposure",
        "autonomy_or_robotics_relevance",
        "hiring_intent_strength",
        "funding_or_budget_signal",
    )
    result = {}
    for field in fields:
        item = (evidence or {}).get(field, {})
        if not isinstance(item, dict):
            raise ValueError(f"{field} evidence must be a mapping")
        status = item.get("status", "unknown")
        if status not in {"confirmed", "inferred", "unknown"}:
            raise ValueError(f"Invalid evidence status: {status}")
        source = item.get("evidence_source")
        freshness = item.get("evidence_freshness")
        if not source or item.get("value") is None:
            status = "unknown"
        result[field] = {
            "value": item.get("value") if status != "unknown" else None,
            "status": status,
            "evidence_source": source,
            "evidence_freshness": freshness,
        }
    return result


if __name__ == "__main__":
    sample_title = "Senior Cloud Architect - Autonomous Mobility"

    sample_description = """
    Lead AWS architecture for an autonomous driving platform.

    We are looking for extensive hands-on cloud architecture experience.
    The team develops autonomous mobility services and fleet technology.

    Location: Berlin.
    """

    result = assess_opportunity(
        "MOIA",
        sample_title,
        sample_description,
    )

    print_assessment(result)
