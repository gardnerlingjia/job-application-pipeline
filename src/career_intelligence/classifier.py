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
        if contains_term(text, keyword):
            score += 2
            matches.append(keyword)

    for keyword in lane_config.get("domain_keywords", []):
        if contains_term(text, keyword):
            score += 1
            matches.append(keyword)

    return round(score * lane_config.get("classification_multiplier", 1)), matches


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


def contains_term(text: str, term: str) -> bool:
    """Match complete terms, avoiding AI in 'chair' and AD in 'lead'."""
    import re

    return bool(re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", text.lower()))


def strategy_context(title: str, description: str, access: str = "cold") -> dict:
    policy = load_career_profile().get("strategy_policy", {})
    text = normalize_text(title, description)

    def matches(key, value=text):
        return [term for term in policy.get(key, []) if contains_term(value, term)]

    autonomy = matches("autonomy_terms")
    domain = matches("domain_advantage_terms")
    ai_data = matches("ai_data_terms")
    delivery = matches("delivery_terms")
    executive = matches("executive_terms", title.lower())
    engineering = matches("engineering_title_terms", title.lower())
    # Research leadership can require specialist practice despite generic adoption language.
    import re
    research_scope = re.search(r'data science|ai research|machine learning', title.lower())
    research_requirement_pattern = (
        r'(?:strong|excellent|advanced).{0,25}(?:python|programming)|'
        r'(?:mehrjährig|several years).{0,85}(?:machine learning|data science)|'
        r'sehr gute programmierkenntnisse|hands-on.{0,25}(?:model|ml)'
    )
    research_requirements = any(
        re.search(research_requirement_pattern, clause)
        and not re.search(r"\b(?:no|not|optional|kein\w*|nicht)\b", clause)
        for clause in re.split(r"[.;\n]", description.lower())
    )
    if research_scope and research_requirements:
        engineering.append("specialist_ml_research_requirements")
    unsupported = matches("unsupported_leadership_terms")
    bridge_support = domain or matches("bridge_support_terms") or access != "cold"
    if engineering or unsupported:
        transition = "unrealistic"
    elif executive:
        transition = "adjacent" if autonomy and delivery else "unrealistic"
    elif ai_data and delivery:
        transition = "bridge" if bridge_support else "unrealistic"
    elif autonomy and delivery:
        transition = "adjacent"
    elif domain and delivery and matches("secondary_relevance_terms"):
        transition = "direct"
    else:
        transition = "unknown"
    return {
        "transition": transition,
        "autonomy_matches": autonomy,
        "domain_advantage_matches": domain,
        "delivery_matches": delivery,
        "bridge_support": bool(bridge_support),
        "executive_role": bool(executive),
        "cold_access_review": bool(matches("cold_access_review_terms")),
        "commissioning_review_required": bool(autonomy)
        and bool(matches("commissioning_review_title_terms", title.lower())),
        "engineering_mismatch": engineering,
        "unsupported_leadership": unsupported,
        "policy": policy,
    }
