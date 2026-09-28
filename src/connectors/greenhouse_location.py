"""Country-scoped acquisition from explicit Greenhouse location metadata only."""
import re


def germany_location_decision(job: dict) -> dict:
    location = job.get('location')
    name = location.get('name') if isinstance(location, dict) else None
    if not isinstance(name, str) or not name.strip():
        return {'decision': 'excluded', 'reason': 'missing_location', 'original_location': location}
    # A country token is required; cities alone and Europe/remote are ambiguous.
    countries = re.findall(
        r'\b(germany|deutschland|united states|usa|united kingdom|uk|india|japan|'
        r'poland|taiwan|france|canada|australia|netherlands|switzerland|austria)\b',
        name.casefold())
    german = any(c in {'germany', 'deutschland'} for c in countries)
    foreign = any(c not in {'germany', 'deutschland'} for c in countries)
    reason = ('mixed_country_location' if german and foreign else 'verified_germany'
              if german else 'verified_outside_germany' if foreign else 'ambiguous_location')
    return {'decision': 'retained' if reason == 'verified_germany' else 'excluded',
            'reason': reason, 'original_location': location}
