from pathlib import Path
from typing import Dict, List

import yaml


CONFIG_PATH = Path("config/career_profile.yaml")


def load_career_profile() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def normalize_text(title: str, description: str) -> str:
    return f"{title} {description}".lower()


def match_location(title: str, description: str, *, structured_location: dict | None = None) -> Dict:
    from src.career_intelligence.practical_constraints import practical_evidence

    practical = practical_evidence(description, structured_location)
    workplace = practical['workplace']
    location_text = workplace['name']
    if workplace['remote']:
        location_text += ' remote Germany' if workplace['germany'] else ' remote'
    result = _match_location('', location_text, practical)
    result.update(practical)
    import yaml
    with Path('config/constraints.yaml').open(encoding='utf-8') as file:
        outside_cities = yaml.safe_load(file)['location_enforcement']['outside_region_cities']
    outside = any(city.lower() in workplace['name'].lower() for city in outside_cities)
    if (outside and not workplace['berlin_preference'] and not workplace['remote']
            and workplace['work_mode'] in {'hybrid', 'in_person'}):
        result.update(hard_conflict=True, compatibility='incompatible', location_fit=0.0,
                      location_matches=['outside_berlin_required_presence'],
                      presence_reason='Hybrid/in-person work at the captured non-Berlin base.',
                      presence_evidence=[workplace['name'], workplace['work_mode']])
    import re

    primary = re.split(r'diese jobs waren bei anderen|similar jobs|related jobs',
                       description, flags=re.I)[0]
    base = re.search(r'Job in (.*?) Jobs finden', primary, re.I)
    mobile = re.search(r'bis zu (\d+)\s*%\s*mobil arbeiten', primary, re.I)
    outside_region = bool(base and re.search(
        r'norderstedt|hamburg|hannover|münchen|munich|frankfurt|stuttgart|düsseldorf',
        base[1], re.I))
    if outside_region and mobile and int(mobile[1]) < 100 and 'berlin' not in base[1].lower():
        result.update(hard_conflict=True, compatibility='incompatible', location_fit=0.0,
                      location_matches=['non_berlin_partial_mobile_work'],
                      category='non_berlin_partial_mobile_work',
                      presence_evidence=[base.group(0), mobile.group(0)],
                      presence_reason='Non-Berlin role permits only partial mobile work; '
                                      'Berlin-based remote employment is not established.')
    if result.get("hard_conflict"):
        result["compatibility"] = "incompatible"
    elif outside and not workplace['berlin_preference'] and not workplace['remote']:
        # A known non-Berlin city with no attendance arrangement is not evidence
        # of Berlin-compatible work, even if the job explicitly requires no travel.
        result['compatibility'] = 'unknown'
    if practical["compatibility"] == "incompatible":
        result.update(location_fit=0.0, location_matches=["location_conflict"],
                      hard_conflict=True, compatibility='incompatible')
    if result["compatibility"] == "confirmed" and not result["location_matches"]:
        result.update(location_fit=80.0, location_matches=[practical["category"]])
    return result


def _match_location(title: str, description: str, practical: dict) -> Dict:
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
    required_relocation = bool(practical["relocation_evidence"])
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
