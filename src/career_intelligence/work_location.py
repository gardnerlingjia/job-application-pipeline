"""Workplace evidence, kept separate from cities named as stakeholder markets."""
import re


def workplace_evidence(description: str, structured_location: dict | None = None) -> dict:
    if structured_location is not None and not isinstance(structured_location, dict):
        raise ValueError('structured_location must be an object')
    structured = structured_location or {}
    name = structured.get('name', '')
    if not isinstance(name, str):
        raise ValueError('structured_location.name must be text')
    text = description.lower()
    text = re.split(r'diese jobs waren bei anderen|similar jobs|related jobs', text)[0]
    source = structured.get('source', 'structured_location') if name.strip() else 'description'
    if not name.strip():
        patterns = [
            r'job in (.*?) jobs finden',
            r'\b(?:location|standort|arbeitsort)\s*:?\s*([^.;\n]+)',
            r'(?:based|located|hybrid|on-site|onsite) in ([^.;\n]+)',
            r'(?:daily presence|daily on-site|daily onsite) in ([^.;\n]+)',
            r'(?:remote (?:in )?germany|germany remote|germany-wide|deutschlandweit)',
            r'\b((?:berlin|potsdam|munich|münchen)(?:\s*/\s*|[- ]based\s*,?\s*)'
            r'(?:hybrid|on[- ]?site|remote)?)\b',
            r'(?:^|[.;\n])\s*((?:berlin|potsdam|germany|deutschland|munich|münchen)'
            r'(?:\s+(?:on-site|onsite|hybrid))?)\s*(?=[.;\n]|$)',
        ]
        hits = [re.split(r'\b(?:and report|with|working|collaborat\w*|stakeholders?|'
                         r'however|but|while|support\w*)\b',
                         m.group(1) if m.lastindex else m.group(0))[0]
                for pattern in patterns for m in re.finditer(pattern, text)
                if not re.search(r'\b(?:teams?|partners?|stakeholders?|headquarters|hauptsitz|'
                                 r'clients?|customers?)\b',
                                 re.split(r'[.;\n]', text[:m.start()])[-1])]
        name = ' '.join(hits).strip()
    location = name.lower()
    remote = bool(re.search(r'\bremote\b|home.?office|fully remote', location))
    # A role-specific remote arrangement can qualify a structured city, but an
    # incidental reference to a remote team cannot.
    remote = remote or bool(re.search(
        r'(?:role|position|job) (?:is |can be )?(?:fully )?remote|'
        r'fully remote (?:role|position|job)|remote (?:in )?germany', text))
    hybrid = bool(re.search(r'\bhybrid\b', location)) or bool(re.search(
        r'hybrid (?:work|role|position|schedule|based)|(?:role|position|work) (?:is )?hybrid', text))
    in_person = bool(re.search(r'\bon[- ]?site\b', location)) or bool(re.search(
        r'in[- ]person (?:role|position|work)|'
        r'(?:role|position) (?:is )?(?:in[- ]person|on[- ]?site)|'
        r'on[- ]?site (?:role|position|work|in )|daily presence|tägliche präsenz', text))
    attendance = []
    for match in re.finditer(
        r'(?:\d+(?:\s*[–-]\s*\d+)?\s*days?\s*(?:/|per |a )week\s*on[- ]?site|'
        r'on[- ]?site\s*\d+(?:\s*[–-]\s*\d+)?\s*days?\s*(?:/|per |a )week|'
        r'\d+(?:\s*[–-]\s*\d+)?\s*tage\s*(?:pro|je) woche\s*(?:vor ort|im büro))', text):
        prefix = text[max(0, match.start()-25):match.start()]
        suffix = text[match.end():match.end()+25]
        if (not re.search(r'optional|not required|no required|nicht erforderlich', prefix)
                and not re.match(r'\s*(?:is |are )?(?:optional|not required|nicht erforderlich)', suffix)):
            attendance.append(match.group(0))
    if attendance:
        hybrid = bool(re.search(r'\bhybrid\b', text))
        in_person = True
    partial_remote = re.search(r'\b(\d+)\s*%\s*(?:remote arbeiten|remote work|mobil arbeiten)', text)
    if partial_remote and 0 <= int(partial_remote[1]) < 100:
        hybrid = True
        attendance.append(partial_remote.group(0))
    mode = 'hybrid' if hybrid else 'in_person' if in_person else 'remote' if remote else 'unknown'
    berlin = bool(re.search(r'\bberlin\b', location))
    germany = bool(re.search(r'germany|deutschland|berlin|potsdam|munich|münchen|^de$', location))
    base = ('berlin' if berlin else 'remote_germany' if remote and germany
            else 'munich' if re.search(r'munich|münchen', location)
            else 'germany_wide' if re.search(r'germany-wide|deutschlandweit', location)
            else 'germany' if germany else 'other' if location else 'unknown')
    return {'name': name, 'source': source, 'base': base, 'work_mode': mode,
            'berlin_preference': int(berlin), 'germany': germany,
            'remote': remote and not hybrid and not in_person,
            **({'attendance_evidence': attendance} if attendance else {})}
