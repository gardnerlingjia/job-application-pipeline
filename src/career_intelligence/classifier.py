from pathlib import Path
from typing import Dict, List, Tuple

import yaml


CONFIG_PATH = Path("config/career_profile.yaml")


def load_career_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def score_lane(text: str, lane_config: dict) -> Tuple[int, List[str]]:
    matches: List[str] = []
    score = 0

    for keyword in lane_config.get("role_keywords", []):
        if keyword.lower() in text:
            score += 2
            matches.append(keyword)

    for keyword in lane_config.get("domain_keywords", []):
        if keyword.lower() in text:
            score += 1
            matches.append(keyword)

    return score, matches


def classify_job(title: str, description: str) -> Dict:
    profile = load_career_profile()
    text = normalize_text(title, description)

    results = {}

    for lane_code, lane_config in profile["career_lanes"].items():
        score, matches = score_lane(text, lane_config)

        results[lane_code] = {
            "label": lane_config["label"],
            "score": score,
            "matches": sorted(set(matches)),
        }

    ranked = sorted(
        results.items(),
        key=lambda item: item[1]["score"],
        reverse=True,
    )

    best_lane_code, best_lane_data = ranked[0]
    second_lane_code, second_lane_data = ranked[1]

    score_gap = best_lane_data["score"] - second_lane_data["score"]

    if best_lane_data["score"] == 0:
        confidence = "low"
    elif score_gap >= 5:
        confidence = "high"
    elif score_gap >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "career_lane": best_lane_code,
        "career_lane_label": best_lane_data["label"],
        "score": best_lane_data["score"],
        "matches": best_lane_data["matches"],
        "runner_up_lane": second_lane_code,
        "runner_up_label": second_lane_data["label"],
        "runner_up_score": second_lane_data["score"],
        "confidence": confidence,
        "all_lane_scores": results,
    }


if __name__ == "__main__":
    sample_title = "Senior Technical Program Manager - Autonomous Mobility"
    sample_description = """
    Lead deployment of autonomous vehicle technology across fleet operations.
    Coordinate engineering, suppliers, launch readiness and mobility services.
    """

    result = classify_job(sample_title, sample_description)

    print("Career lane:", result["career_lane"])
    print("Label:", result["career_lane_label"])
    print("Score:", result["score"])
    print("Runner-up:", result["runner_up_lane"])
    print("Runner-up score:", result["runner_up_score"])
    print("Confidence:", result["confidence"])
    print("Matches:", result["matches"])