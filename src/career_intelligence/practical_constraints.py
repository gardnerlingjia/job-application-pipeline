"""Conservative practical evidence. Missing or ambiguous travel stays unknown."""
import re

TRAVEL = r'\b(?:travel(?:ling|ing)?|reisen?|reisebereitschaft|reisetätigkeit|reiseaufwand)\b'


def travel_context(clause: str) -> str:
    """Keep qualifiers close to travel, excluding compensation and attendance clauses."""
    parts = re.split(r'\b(?:remote|on[- ]?site|homeoffice|office|präsenz|salary|bonus)\b', clause)
    contexts = []
    for part in parts:
        for match in re.finditer(TRAVEL, part):
            contexts.append(part[max(0, match.start() - 45):match.end() + 100])
    return ' '.join(contexts)


def travel_percentages(context: str) -> list[str]:
    """Percentages must be syntactically attached to travel, not merely nearby."""
    quantity = (r'(?:(?:up to|at most|at least|around|about|approximately|bis zu|etwa|'
                r'maximum|minimum|maximal|mindestens|ca\.?)\s+|~)?\d+\s*%\+?')
    before = quantity + r'\s*(?:of (?:your|the) time\s+)?(?:(?:domestic|international|european)\s+)?' + TRAVEL
    after = TRAVEL + r'\s*(?:(?:requirements?|required|of|for|about|around|approximately|:' \
        r'|\(|within germany|across europe|within europe|in europe|domestic|international)\s*)*' + quantity
    return [m.group(0) for pattern in (before, after) for m in re.finditer(pattern, context)]


def practical_evidence(text: str, structured_location: dict | None = None) -> dict:
    from src.career_intelligence.work_location import workplace_evidence

    workplace = workplace_evidence(text, structured_location)
    text = text.lower()
    # Related-job cards are not requirements of the assessed role.
    text = re.split(r"diese jobs waren bei anderen|similar jobs|related jobs", text)[0]
    clauses = re.split(r"(?<!\bca)\.|[;\n]|\b(?:but|however|aber|jedoch)\b", text)
    frequent, relocation, occasional, absent = [], [], [], []
    travel_details = []
    for clause in clauses:
        # Flat ATS descriptions can concatenate many bullets. An explicit travel
        # label starts its own requirement, not the preceding skills/audits list.
        label = re.search(r'\btravel(?: requirements?)?\s*:', clause)
        if label:
            clause = clause[label.start():]
        travel = bool(re.search(TRAVEL, clause))
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
            context = travel_context(clause)
            quantity_context = ' '.join(travel_percentages(context))
            percentages = sorted({int(n) for n in re.findall(r"(\d+)\s*%", quantity_context)})
            # Day-based travel quantities remain tied to the explicit travel clause.
            if re.search(r'\d+\s*(?:days|tage)', context):
                quantity_context += ' ' + context
            ceiling = bool(re.search(r'(?:up to|at most|maximum|bis zu|maximal)\s+\d+', quantity_context))
            minimum = bool(re.search(r'\d+\s*%\s*\+|(?:at least|minimum|mindestens)\s+\d+', quantity_context))
            approximate = bool(re.search(
                r'(?:~|approximately|around|about|etwa|ca\.?)\s*\d+\s*(?:%|days?|tage)', quantity_context))
            scope = ('international' if re.search(r'international|\bus\b|\buk\b', clause)
                     else 'european' if re.search(r'europe|europa|emea|\beu\b', clause)
                     else 'domestic' if re.search(r'domestic|germany|deutschland|innerdeutsch', clause)
                     else 'unknown')
            scopes = [label for label, pattern in (
                ('domestic', r'domestic|innerdeutsch|within germany|innerhalb deutschlands'),
                ('european', r'europe|europa|emea|\beu\b|\buk\b'),
                ('international', r'international|\bus\b|\buk\b'),
            ) if re.search(pattern, clause)]
            # >=20% or >=4 days/month is materially more than occasional travel.
            monthly_days = re.search(
                r"(\d+)\s*(?:days|tage\w*)\s*(?:per|a|pro|im)\s*(?:month|monat)", context
            )
            recurrent = re.search(
                r"\bfrequent\b|\bextensive\b|\bregular(?:ly)?\b|weekly|every week|häufig|regelmäßig|"
                r"wöchentlich|(?:\d+|one|two|three|four|five) days? (?:per|a) week|"
                r"vier bis fünf tagen pro monat", context,
            )
            established = bool(recurrent or (not ceiling and (
                any(n >= 20 for n in percentages)
                or (monthly_days and int(monthly_days[1]) >= 4))))
            travel_details.append({
                'text': clause.strip(), 'scope': scope, 'scopes': scopes,
                'qualifier': 'frequent' if recurrent else 'ceiling' if ceiling else
                'minimum' if minimum else 'approximate' if approximate else
                'expected' if percentages or monthly_days else 'unspecified',
                'percentages': percentages, 'established_frequent': established,
            })
            if established:
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
    berlin = workplace['berlin_preference'] == 1
    germany = workplace['germany']
    europe = any(re.search(r"europe|europa|emea|\beu\b", c) for c in frequent)
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
        "workplace": workplace, "travel_details": travel_details,
    }
