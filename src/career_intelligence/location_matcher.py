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
    with Path("config/constraints.yaml").open(encoding="utf-8") as file:
        location_policy = yaml.safe_load(file).get("location_enforcement", {})
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

    # Explicit remote Germany is compatible even if the employer HQ is elsewhere.
    remote = any(term in text for term in preferred_terms[1:])
    import re

    required_relocation = (
        any(re.search(r"(?<!no )(?<!not )" + re.escape(term), text) for term in relocation_terms)
        or "requires relocation" in text
    )
    daily = any(
        term.lower() in text for term in location_policy.get("outside_region_daily_terms", [])
    )
    outside = any(term.lower() in text for term in location_policy.get("outside_region_cities", []))
    china_based = any(term in text for term in china_terms)
    munich_onsite = any(term in text for term in munich_terms) and any(
        term in text for term in ("on-site", "onsite", "based in munich", "based in münchen")
    )
    if (
        required_relocation
        or (daily and outside)
        or (not remote and (china_based or munich_onsite))
    ):
        return {
            "location_fit": 0.0,
            "location_matches": ["location_conflict"],
            "hard_conflict": True,
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
