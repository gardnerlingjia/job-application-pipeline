from typing import Dict

from src.career_intelligence.classifier import load_career_profile


# Stable field contract; weights are candidate configuration, not search allocation.
WEIGHTS = {
    "career_lane_fit": 0.20,
    "capability_fit": 0.30,
    "domain_fit": 0.20,
    "evidence_strength": 0.30,
    "location_fit": 0.0,
    "network_access": 0.0,
}


def calculate_opportunity_score(scores: Dict[str, float]) -> float:
    weights = load_career_profile()["strategy_policy"].get("candidacy_weights", WEIGHTS)
    if set(weights) != set(WEIGHTS) or abs(sum(weights.values()) - 1) > 1e-9:
        raise ValueError("Candidacy weights must contain all dimensions and sum to one")
    if weights["network_access"] != 0 or weights["location_fit"] != 0:
        raise ValueError("Access and location cannot contribute to evidence-based candidacy")
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("Candidacy weights cannot be negative")
    missing = [key for key in weights if key not in scores]
    if missing:
        raise ValueError(f"Missing score fields: {', '.join(missing)}")
    return round(sum(scores[key] * weight for key, weight in weights.items()), 1)


def calculate_candidate_strength(scores: Dict[str, float], *, gap_cap: float = 100) -> float:
    """Independent minimum evidence gate, retained for existing callers."""
    return round(min(scores["capability_fit"], scores["evidence_strength"], gap_cap), 1)


def evidence_anchors(matched: list[dict], context: dict) -> dict:
    policy = context["policy"]["evidence_anchors"]
    supported = {
        item["capability"]
        for item in matched
        if item.get("match_basis") == "direct_terms"
        and item.get("evidence")
        and item["category"] in {"core", "domain"}
    }
    role = sorted(supported.intersection(policy["direct_role_capabilities"]))
    domain = sorted(supported.intersection(policy["direct_domain_capabilities"]))
    relevant = bool(context["delivery_matches"]) and bool(
        context["autonomy_matches"]
        or context["domain_advantage_matches"]
        or context["transition"] == "bridge"
    )
    relevant = relevant and context["transition"] in {"direct", "adjacent", "bridge"}
    direct = (
        relevant
        and bool(role)
        and bool(domain)
        and not context["executive_role"]
        and context["transition"] in policy["high_anchor_transitions"]
    )
    level = "direct" if direct else "adjacent" if relevant and matched else "unknown"
    anchor = policy[level]
    return {
        "basis": level,
        "career_lane_fit": anchor if relevant else 0,
        "domain_fit": policy["direct"] if domain else anchor if relevant else 0,
        "direct_role_evidence": role,
        "direct_domain_evidence": domain,
        "total_cap": 100
        if direct
        else policy["adjacent_total_cap"]
        if level == "adjacent"
        else policy["unknown"],
    }
