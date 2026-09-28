"""Recover optional assessment evidence without guessing absent historical inputs."""
from copy import deepcopy
from pathlib import Path

from src.career_intelligence.batch import _load_job

MARKET_KEYS = {
    "employer_segment", "traditional_automotive_exposure", "autonomy_or_robotics_relevance",
    "hiring_intent_strength", "funding_or_budget_signal",
}
REQUIREMENT_KEYS = {"commercial_core", "engineering_commissioning_core", "technical_core"}
UNKNOWN = {"value": None, "status": "unknown", "evidence_source": None}


def validate_snapshot(snapshot: dict) -> dict:
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1
            or not isinstance(snapshot.get("role_evidence"), dict)
            or not isinstance(snapshot.get("market_evidence"), dict)):
        raise ValueError("invalid_evidence_snapshot: explicit role and market mappings required")
    if snapshot.get('structured_location') is not None:
        location = snapshot['structured_location']
        if not isinstance(location, dict) or not isinstance(location.get('name'), str):
            raise ValueError('invalid_evidence_snapshot: structured location requires a name')
    return deepcopy(snapshot)


def recover_evidence(record: dict, processed: Path) -> tuple[dict, str]:
    explanation = record.get("explanation", {})
    if "input_evidence" in explanation:
        return validate_snapshot(explanation["input_evidence"]), "saved_input_snapshot"
    source = record["source_file"]
    if Path(source).name != source:
        raise ValueError("unsafe_source_identity: source_file must be a basename")
    original = processed / source
    if original.is_file():
        job = _load_job(original)
        if job.get("company") != record["company"] or job.get("title") != record["title"]:
            raise ValueError("archived_input_identity_mismatch")
        snapshot = {"schema_version": 1, "role_evidence": job.get("role_evidence", {}),
                    "market_evidence": job.get("market_evidence", {}),
                    **({'structured_location': job['structured_location']}
                       if 'structured_location' in job else {})}
        return validate_snapshot(snapshot), "archived_original_input"
    if explanation.get("semantics_version") not in {3, 4}:
        raise ValueError("missing_evidence_snapshot: legacy assessment has no reconstructable evidence contract")
    # These versions expose all supported requirement facts and enumerate unknown markets.
    # Categorical positive access cannot recover its original relationship/source.
    if explanation.get("access") != "cold":
        raise ValueError("network_evidence_not_recoverable: positive access lacks original relationship/source")
    facts = explanation.get("role_requirements", {}).get("facts", {})
    if not isinstance(facts, dict) or set(facts) != REQUIREMENT_KEYS:
        raise ValueError("requirement_evidence_incomplete")
    for fact in facts.values():
        if fact == UNKNOWN:
            continue
        if not (isinstance(fact, dict) and fact.get("status") == "confirmed"
                and type(fact.get("value")) is bool
                and isinstance(fact.get("evidence_source"), str)
                and fact["evidence_source"].strip()):
            raise ValueError("requirement_evidence_not_recoverable: incomplete or unconfirmed sourced fact")
    unknown = explanation.get("missing_market_evidence")
    if not isinstance(unknown, list) or not set(unknown) <= MARKET_KEYS:
        raise ValueError("market_evidence_incomplete")
    market = {}
    for key in MARKET_KEYS:
        if key == "traditional_automotive_exposure":
            fact = explanation.get(key)
            if not isinstance(fact, dict):
                raise ValueError("market_evidence_incomplete: traditional_automotive_exposure")
            if key in unknown and (fact.get("value") is not None or fact.get("evidence_source")):
                raise ValueError("market_evidence_not_recoverable: ambiguous unknown exposure")
            market[key] = deepcopy(fact)
        elif key in unknown:
            market[key] = {**UNKNOWN, "evidence_freshness": None}
        else:
            raise ValueError(f"market_evidence_not_recoverable: {key}")
    return {"schema_version": 1, "role_evidence": {"requirements": deepcopy(facts)},
            "market_evidence": market}, "reconstructed_v3_v4_explicit_facts_and_unknowns"
