"""Durable retrieval observations and per-run queues, separate from assessment truth."""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.career_intelligence.batch import _write_temporary
from src.career_intelligence.role_relevance import RoleRelevanceGate
from src.career_intelligence.silver_adapter import source_file_for_row

STATE_FILE = "retrieval_state.json"
DAILY_FILE = "retrieval_daily.json"
METRICS = ("new_jobs_seen", "new_relevant_jobs", "new_ambiguous_jobs", "new_excluded_jobs",
           "target_companies_checked", "target_companies_with_new_jobs",
           "employer_origin_jobs", "discovery_only_jobs")


def write_json(results: Path, name: str, payload: dict) -> None:
    results.mkdir(parents=True, exist_ok=True)
    temp = _write_temporary(results, json.dumps(payload, indent=2, default=str) + "\n")
    try:
        os.replace(temp, results / name)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid retrieval file: {path.name}")
    return payload


def initialize_state(results: Path) -> dict:
    state = read_json(results / STATE_FILE, {})
    if not state:
        state = {"schema_version": 1, "baseline_at": datetime.now(UTC).isoformat(),
                 "identities": {}, "canonical_keys": {}}
        write_json(results, STATE_FILE, state)
    return state


def identity(row: dict) -> str:
    source = str(row.get("source_name") or "")
    external = str(row.get("external_job_id") or "").strip()
    if external:
        value = f"{source}\0{external}"
    elif row.get("source_url"):
        url = urlsplit(str(row["source_url"]))
        query = [(k, v) for k, v in parse_qsl(url.query)
                 if not k.lower().startswith("utm_") and k.lower() not in {"ref", "tracking"}]
        value = urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path.rstrip("/"),
                           urlencode(sorted(query)), ""))
    else:
        value = str(row.get("canonical_key_candidate") or source_file_for_row(row))
    return sha256(value.encode()).hexdigest()


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def observe_rows(rows: list[dict], *, results: Path, gate: RoleRelevanceGate) -> dict:
    state = initialize_state(results)
    baseline = _timestamp(state["baseline_at"])
    # Existing assessments/provenance are baseline history, even without acquisition timestamps.
    provenance_path = results / "silver_ingestion_provenance.json"
    previous = json.loads(provenance_path.read_text()) if provenance_path.exists() else []
    known_files = {p.get("source_file") for p in previous}
    known_keys = {p.get("canonical_key_candidate") for p in previous
                  if p.get("canonical_key_candidate")}
    records = []
    now = datetime.now(UTC).isoformat()
    # Prefer employer-origin evidence within this batch without discarding other observations.
    for row in sorted(rows, key=lambda r: "employer_origin" not in str(
        r.get("canonical_source_type") or ""
    )):
        key = identity(row)
        canonical = row.get("canonical_key_candidate")
        seen = state["identities"].get(key)
        acquired = _timestamp(row.get("first_seen_at"))
        source_file = source_file_for_row(row)
        is_new = bool(not seen and source_file not in known_files
                      and canonical not in known_keys
                      and (not canonical or canonical not in state["canonical_keys"])
                      and acquired and baseline and acquired >= baseline)
        employer = "employer_origin" in str(row.get("canonical_source_type") or "")
        decision = gate.decide(row.get("title")).as_dict()
        record = {
            "identity": key, "source_file": source_file,
            "company": row.get("company_name"), "title": row.get("title"),
            "source_name": row.get("source_name"), "source_url": row.get("source_url"),
            "silver_job_id": row.get("silver_job_id"), "raw_job_id": row.get("raw_job_id"),
            "external_job_id": row.get("external_job_id"),
            "canonical_key_candidate": canonical, "role_gate": decision,
            "employer_origin": employer, "is_new": is_new,
            "first_observed_at": seen["first_observed_at"] if seen else now,
            "last_observed_at": now,
            "novelty_reason": "NEW_IDENTITY" if is_new else (
                "KNOWN_IDENTITY" if seen else "BASELINE_OR_KNOWN_VACANCY"),
        }
        state["identities"][key] = record
        if canonical:
            state["canonical_keys"][canonical] = key
        records.append(record)
    write_json(results, STATE_FILE, state)
    report = build_report(records)
    write_json(results, DAILY_FILE, report)
    return report


def build_report(records: list[dict], companies: list[dict] | None = None) -> dict:
    companies = companies or []
    new = [r for r in records if r["is_new"]]
    relevant = [r for r in new if r["role_gate"]["reason"] == "RELEVANT_ROLE"]
    ambiguous = [r for r in new if r["role_gate"]["reason"] == "AMBIGUOUS_REVIEW"]
    origins = sum(r["employer_origin"] for r in new)
    new_sources = {r["source_name"] for r in new if r["employer_origin"]}
    signals = [c for c in companies if c.get("source_name") in new_sources]
    return {
        "schema_version": 1, "completed_at": datetime.now(UTC).isoformat(),
        "metrics": {
            "new_jobs_seen": len(new), "new_relevant_jobs": len(relevant),
            "new_ambiguous_jobs": len(ambiguous),
            "new_excluded_jobs": len(new) - len(relevant) - len(ambiguous),
            "target_companies_checked": sum(bool(c.get("checked")) for c in companies),
            "target_companies_with_new_jobs": len(signals),
            "employer_origin_jobs": origins, "discovery_only_jobs": len(new) - origins,
        },
        "new_relevant": relevant, "new_ambiguous": ambiguous,
        "target_company_signals": signals,
        "needs_employer_enrichment": [r for r in relevant + ambiguous
                                      if not r["employer_origin"]],
        "records": records, "target_companies": companies,
    }
