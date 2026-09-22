from typing import Dict, List


def recommend_action(
    opportunity_score: float,
    constraint_action: str,
    network_access: float,
    high_risks: List[Dict],
    reviews: List[Dict],
) -> str:

    if constraint_action == "SKIP":
        return "SKIP"

    # Legacy callers do not supply independent candidate strength or categorical access.
    # A composite score cannot establish APPLY or NETWORK FIRST eligibility.
    return "WATCH" if opportunity_score >= 45 else "SKIP"


def recommend_strategy_action(
    candidate_strength: float,
    constraints: str,
    context: dict,
    location: dict,
    access: str,
    blocking_gaps: dict,
    commissioning_status: str,
) -> str:
    """NETWORK FIRST solves cold access only; never capability or requirement uncertainty."""
    policy = context["policy"]
    if constraints == "SKIP" or location.get("hard_conflict"):
        return "SKIP"
    if context["transition"] == "unrealistic":
        return "SKIP"
    strategic_fit = context["transition"] in {"direct", "adjacent", "bridge"}
    if blocking_gaps or constraints == "HIGH_RISK":
        return "WATCH" if strategic_fit else "SKIP"
    if not strategic_fit:
        return (
            "WATCH"
            if context["autonomy_matches"] or context["domain_advantage_matches"]
            else "SKIP"
        )
    if not location["location_matches"]:
        return "WATCH"
    if commissioning_status in {"unknown", "core_required"}:
        return "WATCH"
    sufficient = candidate_strength >= policy["candidate_network_threshold"]
    evidence = context.get("evidence_strength", candidate_strength)
    sufficient = sufficient and evidence >= policy["evidence_network_threshold"]
    if not sufficient:
        return "WATCH"
    if context["executive_role"]:
        return "NETWORK_FIRST" if access == "cold" else "WATCH"
    if (
        access == "cold"
        and (context["autonomy_matches"] or context.get("cold_access_review"))
        and commissioning_status != "confirmed_not_core"
    ):
        return "NETWORK_FIRST"
    if (
        candidate_strength >= policy["candidate_apply_threshold"]
        and evidence >= policy["evidence_apply_threshold"]
    ):
        return "APPLY_NOW"
    return "NETWORK_FIRST" if access == "cold" else "WATCH"
