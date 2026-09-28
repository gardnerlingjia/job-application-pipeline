"""Explicit German delivery responsibilities; never evidence of implementation skill."""
import re


def delivery_signals(role_text: str) -> dict[str, list[str]]:
    patterns = {
        'program_governance': (
            r'steuerung eines portfolios|portfoliosteuerung|'
            r'priorisierung (?:von )?projekten|überwachung der projektdurchführung'),
        'technical_program_leadership': (
            r'erstellung von projektplänen|ressourcenplanung|'
            r'koordination und abstimmung zwischen business.{0,35}data.science.beteiligten|'
            r'programmleitung|leitung (?:von )?(?:transformations|digitalisierungs)programmen'),
        'product_delivery': (
            r'übernahme der rolle des product owners|'
            r'steuerung (?:von )?transformationsprojekten|'
            r'koordination (?:von )?(?:rollouts|produkteinführungen)'),
    }
    return {capability: [match.group(0) for match in re.finditer(pattern, role_text, re.I)]
            for capability, pattern in patterns.items()
            if re.search(pattern, role_text, re.I)}
