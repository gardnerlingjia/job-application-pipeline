from pathlib import Path
from typing import Dict, List

import yaml

from src.career_intelligence.classifier import contains_term


CONFIG_PATH = Path("config/career_profile.yaml")


def load_career_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def match_domain(title: str, description: str, career_lane: str) -> Dict:
    profile = load_career_profile()
    text = normalize_text(title, description)

    lane_config = profile["career_lanes"][career_lane]
    domain_keywords = lane_config.get("domain_keywords", [])

    matches: List[str] = [keyword for keyword in domain_keywords if contains_term(text, keyword)]

    unique_matches = sorted(set(matches))

    if not domain_keywords:
        domain_fit = 0.0
    else:
        coverage = len(unique_matches) / len(domain_keywords)
        domain_fit = round(min(coverage * 250, 100), 1)

    return {
        "domain_fit": domain_fit,
        "domain_matches": unique_matches,
    }


if __name__ == "__main__":
    result = match_domain(
        "Senior Technical Program Manager - Autonomous Mobility",
        """
        Lead autonomous vehicle deployment and fleet operations
        across mobility services and automated driving programs.
        """,
        "autonomy_robotics",
    )

    print("Domain fit:", result["domain_fit"])
    print("Matches:", result["domain_matches"])
