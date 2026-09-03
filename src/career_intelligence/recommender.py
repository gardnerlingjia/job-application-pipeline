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

    if high_risks:
        if opportunity_score >= 70:
            return "EXPLORE"

        if opportunity_score >= 45:
            return "WATCH"

        return "SKIP"

    if reviews:
        if opportunity_score >= 70:
            return "EXPLORE"

        if opportunity_score >= 45:
            return "WATCH"

        return "SKIP"

    if opportunity_score >= 82:
        if network_access >= 50:
            return "APPLY_NOW"
        return "NETWORK_FIRST"

    if opportunity_score >= 72:
        return "NETWORK_FIRST"

    if opportunity_score >= 60:
        return "EXPLORE"

    if opportunity_score >= 45:
        return "WATCH"

    return "SKIP"