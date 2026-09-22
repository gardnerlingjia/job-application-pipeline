"""Conservative practical evidence. Missing or ambiguous travel stays unknown."""
import re


def practical_evidence(text: str) -> dict:
    text = text.lower()
    # Related-job cards are not requirements of the assessed role.
    text = re.split(r"diese jobs waren bei anderen|similar jobs|related jobs", text)[0]
    clauses = re.split(r"[.;\n]|\b(?:but|however|aber|jedoch)\b", text)
    frequent, relocation, occasional, absent = [], [], [], []
    for clause in clauses:
        travel = bool(re.search(r"travel|reis\w*", clause))
        negated_travel = re.search(
            r"\b(?:no|without) (?:(?:frequent|regular|european|international|business) )*travel|"
            r"(?:travel|reis\w*).{0,20}(?:not required|nicht erforderlich|optional)|"
            r"(?:not required|not expected) to travel|keine? (?:häufigen? )?reis\w*",
            clause,
        )
        no_travel = re.search(
            r"\bno travel(?: required)?(?:[,.]|\s*$)|travel (?:is )?not required|"
            r"keine reise\w*(?: erforderlich)?(?:[,.]|\s*$)|"
            r"reise\w* (?:ist )?nicht erforderlich", clause,
        )
        optional = re.search(r"optional|freiwillig", clause)
        if no_travel:
            absent.append(clause.strip())
        if travel and not negated_travel and not optional:
            percentages = [int(n) for n in re.findall(r"(\d+)\s*%", clause)]
            # >=20% or >=4 days/month is materially more than occasional travel.
            monthly_days = re.search(
                r"(\d+)\s*(?:days|tage\w*)\s*(?:per|a|pro|im)\s*(?:month|monat)", clause
            )
            recurrent = re.search(
                r"\bfrequent\b|\bextensive\b|\bregular(?:ly)?\b|weekly|every week|häufig|regelmäßig|"
                r"wöchentlich|(?:\d+|one|two|three|four|five) days? (?:per|a) week|"
                r"vier bis fünf tagen pro monat", clause,
            )
            if (recurrent or any(n >= 20 for n in percentages)
                    or (monthly_days and int(monthly_days[1]) >= 4)):
                frequent.append(clause.strip())
            if (re.search(r"occasional|infrequent|gelegentlich|selten", clause)
                    and re.search(r"germany|deutschland|domestic|innerdeutsch", clause)
                    and not re.search(r"europe|europa|international", clause)):
                occasional.append(clause.strip())
        relocation_requirement = re.search(
            r"relocation (?:is )?required|must relocate|relocate to|requires relocation|"
            r"required to relocate|umzug erforderlich|umzugsbereitschaft", clause,
        )
        negated_relocation = re.search(
            r"no relocation|relocation (?:is )?not required|"
            r"(?:not required|not expected|do not need) to relocate|"
            r"kein umzug|umzug (?:ist )?nicht erforderlich|optional", clause,
        )
        if relocation_requirement and not negated_relocation:
            relocation.append(clause.strip())
    # Headquarters alone does not establish the role's base.
    location_text = " ".join(c for c in clauses if not re.search(r"headquarters|hauptsitz", c))
    berlin = bool(re.search(r"\bberlin\b", location_text))
    germany = berlin or bool(re.search(r"germany|deutschland|potsdam", location_text))
    europe = any(re.search(r"europe|europa|emea", c) for c in frequent)
    travel_status = ("frequent_european" if frequent and europe else "frequent_unspecified"
                     if frequent else "occasional_domestic" if occasional else "none_required"
                     if absent else "unknown")
    category = ("relocation_required" if relocation else "frequent_european_travel"
                if frequent and europe else "frequent_travel" if frequent else "berlin_based"
                if berlin else "germany_occasional_domestic" if germany and occasional
                else "germany_no_travel" if germany and absent
                else "germany_unspecified_travel" if germany else "location_unknown")
    return {
        "category": category, "travel_status": travel_status,
        "travel_evidence": frequent or occasional or absent,
        "relocation_evidence": relocation,
        "compatibility": "incompatible" if frequent or relocation else "confirmed"
        if germany and (occasional or absent) else "unknown",
        "berlin_preference": 1 if berlin else 0,
    }
