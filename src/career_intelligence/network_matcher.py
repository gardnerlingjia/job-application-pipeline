from pathlib import Path
from typing import Dict

import yaml


CONFIG_PATH = Path("config/network_profile.yaml")


def load_network_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_company_name(company_name: str) -> str:
    return (
        company_name.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace(".", "")
    )


def match_network(company_name: str) -> Dict:
    profile = load_network_profile()

    relationship_levels = profile["network_model"]["relationship_levels"]
    strategic_levels = profile["network_model"]["strategic_company_relevance"]
    companies = profile.get("companies", {})

    normalized_input = normalize_company_name(company_name)

    matched_company = None

    for _, company in companies.items():
        configured_name = normalize_company_name(
            company["company_name"]
        )

        if configured_name == normalized_input:
            matched_company = company
            break

    if not matched_company:
        return {
            "network_access": 0.0,
            "relationship_level": "none",
            "strategic_relevance": "unknown",
            "known_company": False,
        }

    relationship_level = matched_company.get(
        "relationship_level",
        "none",
    )

    strategic_relevance = matched_company.get(
        "strategic_relevance",
        "low",
    )

    base_score = relationship_levels[
        relationship_level
    ]["score"]

    strategic_bonus = strategic_levels.get(
        strategic_relevance,
        {"bonus": 0},
    )["bonus"]

    network_access = min(
        base_score + strategic_bonus,
        profile["network_scoring_rules"]["maximum_score"],
    )

    return {
        "network_access": float(network_access),
        "relationship_level": relationship_level,
        "strategic_relevance": strategic_relevance,
        "known_company": True,
    }


if __name__ == "__main__":
    for company in ["MOIA", "MOTOR Ai", "Waymo", "Unknown Company"]:
        result = match_network(company)

        print(
            company,
            "->",
            result["network_access"],
            result["relationship_level"],
        )