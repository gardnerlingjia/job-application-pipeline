from pathlib import Path
from typing import Dict, List

import yaml


CONFIG_PATH = Path("config/career_profile.yaml")


def load_career_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def match_location(title: str, description: str) -> Dict:
    profile = load_career_profile()
    text = normalize_text(title, description)

    matched_signals: List[str] = []

    preferred_terms = [
        "berlin",
        "remote germany",
        "remote in germany",
        "germany remote",
    ]

    acceptable_terms = [
        "potsdam",
        "hybrid germany",
        "hybrid in germany",
        "germany-wide",
        "germany wide",
    ]

    relocation_terms = [
        "relocation required",
        "must relocate",
        "relocate to",
    ]

    munich_terms = [
        "munich",
        "münchen",
    ]

    china_terms = [
        "shanghai",
        "beijing",
        "hefei",
        "shenzhen",
        "based in china",
        "location: china",
    ]

    if any(term in text for term in relocation_terms):
        return {
            "location_fit": 0.0,
            "location_matches": ["relocation_required"],
        }

    if any(term in text for term in china_terms):
        return {
            "location_fit": 0.0,
            "location_matches": ["china_based"],
        }

    if any(term in text for term in munich_terms):
        return {
            "location_fit": 20.0,
            "location_matches": ["munich"],
        }

    for term in preferred_terms:
        if term in text:
            matched_signals.append(term)

    if matched_signals:
        return {
            "location_fit": 100.0,
            "location_matches": sorted(set(matched_signals)),
        }

    for term in acceptable_terms:
        if term in text:
            matched_signals.append(term)

    if matched_signals:
        return {
            "location_fit": 80.0,
            "location_matches": sorted(set(matched_signals)),
        }

    return {
        "location_fit": 60.0,
        "location_matches": [],
    }


if __name__ == "__main__":
    result = match_location(
        "Senior Technical Program Manager",
        "Hybrid role based in Berlin with remote work in Germany.",
    )

    print("Location fit:", result["location_fit"])
    print("Matches:", result["location_matches"])