"""Configurable retrieval gate; it never changes candidate scoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import unicodedata

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/career_role_relevance.yaml"
GROUPS = ("junior", "technician", "leadership", "engineering", "product_leadership",
          "relevant_context")


@dataclass(frozen=True)
class RoleDecision:
    reason: str
    matched_rule: str | None
    config_version: str = "career_intelligence.role_relevance.v1"

    @property
    def relevant(self) -> bool:
        return self.reason == "RELEVANT_ROLE"

    def as_dict(self) -> dict:
        return asdict(self)


class RoleRelevanceGate:
    def __init__(self, path: Path = DEFAULT_CONFIG):
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("schema_version") != (
            "career_intelligence.role_relevance.v1"
        ):
            raise ValueError("Invalid role relevance configuration")
        self.rules = {}
        for group in GROUPS:
            rules = config.get(group)
            if not isinstance(rules, list) or not rules or not all(
                isinstance(rule, str) and rule for rule in rules
            ):
                raise ValueError(f"Missing role relevance rules: {group}")
            self.rules[group] = [re.compile(rule, re.IGNORECASE) for rule in rules]

    def decide(self, title: object) -> RoleDecision:
        text = unicodedata.normalize("NFKC", str(title or "")).casefold()
        text = re.sub(r"[-–—_/]+", " ", text)
        text = " ".join(text.split())
        matches = {group: next((r.pattern for r in rules if r.search(text)), None)
                   for group, rules in self.rules.items()}
        for group, reason in (("junior", "EXCLUDED_JUNIOR"),
                              ("technician", "EXCLUDED_TECHNICIAN"),
                              ("leadership", "RELEVANT_ROLE")):
            if matches[group]:
                return RoleDecision(reason, matches[group])
        # Product leadership needs explicit domain context; technical terms alone are not enough.
        if matches["product_leadership"] and matches["relevant_context"]:
            return RoleDecision("RELEVANT_ROLE", matches["product_leadership"])
        if matches["engineering"]:
            return RoleDecision("EXCLUDED_ENGINEERING", matches["engineering"])
        return RoleDecision("AMBIGUOUS_REVIEW", None)
