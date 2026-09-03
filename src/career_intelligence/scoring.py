from typing import Dict


WEIGHTS = {
    "career_lane_fit": 0.25,
    "capability_fit": 0.25,
    "domain_fit": 0.15,
    "location_fit": 0.10,
    "network_access": 0.10,
    "evidence_strength": 0.15,
}


def calculate_opportunity_score(scores: Dict[str, float]) -> float:
    missing = [key for key in WEIGHTS if key not in scores]
    if missing:
        raise ValueError(f"Missing score fields: {', '.join(missing)}")

    weighted_score = sum(
        scores[key] * weight
        for key, weight in WEIGHTS.items()
    )

    return round(weighted_score, 1)