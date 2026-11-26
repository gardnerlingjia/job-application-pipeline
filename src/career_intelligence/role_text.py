"""Conservative, source-independent sections for captured job descriptions.

Sections are evidence scopes, not inferred qualifications. Unstructured historical
descriptions remain usable; explicit employer prose cannot establish role duties.
"""
import re
from html import unescape
from html.parser import HTMLParser


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'p', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'div'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'div'}:
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(text: str) -> str:
    parser = _Text()
    parser.feed(unescape(text))
    return ''.join(parser.parts)


HEADINGS = {
    'duties': r'job responsibilities|your tasks|your mission|'
              r'(?-i:Tasks)(?=\s*:|\s+(?:Identify|Lead|Manage|Develop|Drive|Support|Own))|'
              r'was deinen job ausmacht|you will|your responsibilities(?=\s*[:\n])|'
              r'responsibilities(?=\s*[:\n])|what you.ll do|'
              r'(?:deine|ihre) aufgaben|aufgaben|deine rolle|das erwartet dich',
    'required': r'your profile|must[- ]haves?|das wünschen wir uns|qualifikationen|'
                r'you have|minimum qualifications|required qualifications|requirements(?=\s*[:\n])|'
                r'qualifications(?=\s*[:\n])|what you bring|(?:dein|ihr) profil|profil|'
                r'das bringst du mit|anforderungen',
    'preferred': r'we prefer|preferred qualifications|nice[- ]to[- ]have|idealerweise|wünschenswert',
    'employer': r'about us|about the company|über uns|einleitung|wer wir sind',
    'other': r'benefits|what we offer|why us\?|wir bieten|was wir (?:dir )?bieten|deine benefits|'
             r'similar jobs|related jobs|diese jobs waren bei anderen',
}
MARKERS = re.compile(r'(?<!\w)(?:' + '|'.join(
    f'(?P<{key}>{value})' for key, value in HEADINGS.items()
) + r')(?!\w)\s*:?', re.I)
EMPLOYER = re.compile(
    r'\b(?:we are|our company|our mission|our (?:[\w-]+ )?team|our experts|our products|'
    r'wir sind|unser unternehmen|unsere mission|'
    r'\w+ is (?:an? |the ).{0,65}(?:company|provider|leader))\b', re.I)


def description_sections(description: str) -> dict[str, str]:
    text = plain_text(description)
    markers = list(MARKERS.finditer(text))
    sections = {key: [] for key in (*HEADINGS, 'unstructured')}
    if markers:
        prefix = text[:markers[0].start()]
        # An explicit duties/qualification heading makes the preceding introduction
        # employer context. Explicit role prose before it is still retained.
        start = re.search(r'\b(?:in this role|your role|you will|in dieser.{0,35}rolle)\b',
                          prefix, re.I)
        if start:
            sections['employer'].append(prefix[:start.start()])
            sections['duties'].append(prefix[start.start():])
        elif markers[0].lastgroup in {'required', 'preferred'} and not EMPLOYER.search(prefix):
            sections['unstructured'].append(prefix)
        else:
            sections['employer'].append(prefix)
        for i, marker in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            sections[marker.lastgroup].append(text[marker.end():end])
    else:
        # A known introduction continues until explicit role prose begins. This
        # keeps subsequent product/platform marketing sentences out of evidence.
        employer_context = False
        for sentence in re.split(r'(?<=[.!?])\s+|\n+', text):
            role_start = re.search(
                r'\byou (?:will|are)|\bin this role|\byour role|'
                r'^\s*(?:lead|manage|coordinate|own|deliver|drive|required|must have)\b',
                sentence, re.I)
            employer_context = employer_context or bool(EMPLOYER.search(sentence))
            if role_start:
                if employer_context:
                    sections['employer'].append(sentence[:role_start.start()])
                    sentence = sentence[role_start.start():]
                employer_context = False
            key = 'employer' if employer_context else 'unstructured'
            sections[key].append(sentence)
    result = {key: '\n'.join(parts).strip() for key, parts in sections.items()}
    result['role'] = '\n'.join(result[key] for key in
                              ('duties', 'required', 'preferred', 'unstructured') if result[key])
    return result
