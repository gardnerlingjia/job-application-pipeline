from pathlib import Path
from typing import Dict, List

import yaml


CONFIG_PATH = Path("config/capability_profile.yaml")


def load_capability_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def match_capabilities(title: str, description: str) -> Dict:
    profile = load_capability_profile()
    text = normalize_text(title, description)

    matched: List[Dict] = []

    for capability_name, capability in profile["capabilities"].items():
        match_keywords = capability.get("match_keywords", [])
        transferable_to = capability.get("transferable_to", [])

        terms = [
            str(item).lower()
            for item in match_keywords + transferable_to
        ]

        hits = [term for term in terms if term in text]

        if hits:
            matched.append(
                {
                    "capability": capability_name,
                    "strength": capability["strength"],
                    "category": capability["category"],
                    "matches": sorted(set(hits)),
                }
            )

    if not matched:
        return {
            "capability_fit": 0,
            "matched_capabilities": [],
        }

    total_strength = sum(item["strength"] for item in matched)
    max_strength = len(matched) * 5

    capability_fit = round(
        (total_strength / max_strength) * 100,
        1,
    )

    return {
        "capability_fit": capability_fit,
        "matched_capabilities": matched,
    }


if __name__ == "__main__":
    result = match_capabilities(
        "Senior Technical Program Manager - Autonomous Mobility",
        """
        Lead autonomous mobility programs across engineering,
        fleet deployment, suppliers and senior stakeholders.
        """,
    )

    print("Capability fit:", result["capability_fit"])

    for item in result["matched_capabilities"]:
        print(
            item["capability"],
            item["strength"],
            item["matches"],
        )