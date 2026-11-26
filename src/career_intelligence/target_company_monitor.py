"""Watchlist coverage and reuse of explicitly named, already approved profiles."""
from __future__ import annotations

from pathlib import Path

from psycopg.rows import dict_row
import yaml

from src.career_intelligence.moia_live_source import _gate_passed, connect_database
from src.connectors.registry import SourceRole, create_connector, source_role

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/career_target_companies.yaml"
STATUSES = {"connector_available", "candidate_source_gap", "blocked", "not_evaluated"}


def load_watchlist(path: Path = DEFAULT_CONFIG) -> list[dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Invalid target-company watchlist")
    companies = payload.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("Target-company watchlist is empty")
    keys = set()
    for company in companies:
        if (not isinstance(company, dict) or not company.get("company_key")
                or not company.get("company_name") or not company.get("group")
                or company.get("status") not in STATUSES):
            raise ValueError("Malformed target-company entry")
        if company["company_key"] in keys:
            raise ValueError("Duplicate target company")
        keys.add(company["company_key"])
        if company.get("profile_name") and not company.get("source_name"):
            raise ValueError("Explicit profile requires an exact source name")
    return companies


def company_coverage(conn, company: dict) -> dict:
    result = {**company, "checked": False, "eligible": False}
    source = company.get("source_name")
    if not source:
        return result
    try:
        create_connector(source)
        if source_role(source) != SourceRole.EMPLOYER_ORIGIN:
            raise ValueError("Source is not employer origin")
    except ValueError as exc:
        return {**result, "status": "candidate_source_gap", "reason": str(exc)}
    # Generic family support alone does not verify a company/board binding.
    if not company.get("profile_name"):
        return {**result, "status": "candidate_source_gap",
                "reason": "No validated company-specific profile binding"}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id, status FROM employer_origin_source_candidates
            WHERE company_key = %s AND source_name_candidate = %s
            ORDER BY updated_at DESC, id DESC LIMIT 1
        """, (company["company_key"], source))
        candidate = cur.fetchone()
        cur.execute("""
            SELECT profile_name FROM search_profiles
            WHERE profile_name = %s AND source_name = %s AND is_active = TRUE
        """, (company["profile_name"], source))
        profile = cur.fetchone()
    passed = bool(candidate and candidate["status"] == "active_controlled" and profile)
    if passed:
        for gate, decision in (("connector_validation_gate", "ready_for_final_approval"),
                               ("final_approval_gate", "approve_connector_registration")):
            passed = passed and _gate_passed(conn, candidate_id=candidate["id"],
                                            gate_name=gate, decision=decision)
    return {**result, "status": "connector_available" if passed else "blocked",
            "eligible": passed,
            "reason": "Existing approved controlled profile; scope unchanged" if passed else
                      "Missing active controlled profile or current approval/validation gates"}


def inspect_watchlist() -> list[dict]:
    companies = load_watchlist()
    with connect_database() as conn:
        return [company_coverage(conn, company) for company in companies]


def run_target_monitor(operations, *, limit: int) -> tuple[list[dict], list[str], list[dict]]:
    companies = inspect_watchlist()
    errors = []
    records = []
    for company in companies:
        if not company["eligible"]:
            continue
        try:
            result = operations.run_ingestion_profile(company["profile_name"])
            if result.error or result.status not in {"success", "finished"}:
                raise RuntimeError(result.error or result.status)
            company["checked"] = True
            if operations.run_silver(company["source_name"], limit=limit):
                raise RuntimeError("Silver normalization failed")
            status, _ = operations.run_career_intelligence(company["source_name"], limit=limit)
            if status:
                raise RuntimeError("Career Intelligence refresh failed")
            records.extend(operations.latest_retrieval().get("records", []))
        except Exception as exc:
            company["status"] = "blocked"
            company["reason"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{company['company_name']}: {company['reason']}")
    return companies, errors, records
