"""Bounded V3 read-only discovery runner; never invokes assessment/scoring."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import re
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import yaml

from src.career_intelligence.discovery_store import (
    finalize_run_group, load_monitoring_summary, record_run,
    register_configured_sources,
)
from src.career_intelligence.moia_live_source import connect_database
from src.config import BA_API_KEY
from src.career_intelligence.source_adapters import (
    ProviderParseError, RetrievalLimits, fetch_ashby, fetch_ba, fetch_greenhouse,
    fetch_lever, fetch_smartrecruiters,
)

CONFIG = Path("config/career_discovery_v3.yaml")
EMPLOYERS = Path("config/career_employer_sources.yaml")
V34_CONFIG = Path("config/career_discovery_v34.yaml")
V34_EMPLOYERS = Path("config/career_employer_sources_v34.yaml")


def build_query_plan(config: dict, *, offset: int = 0,
                     maximum: int | None = None) -> list[tuple[str, str, str]]:
    """Allocate requests, never results. Round-robin avoids prefix budget bias."""
    profiles = {key: list(terms) for key, terms in config["profiles"].items()}
    if config.get("strategy_version") == "v3.4":
        attention = config.get("role_attention_percent") or config["industry_attention_percent"]
        if sum(attention.values()) != 100 or set(attention) != set(profiles):
            raise ValueError("Invalid industry attention plan")
        quotas = {key: value // 5 for key, value in attention.items()}
        if any(not terms for terms in profiles.values()) or sum(quotas.values()) != 20:
            raise ValueError("Industry attention must map to twenty nonempty request slots")
        profiles = {key: [terms[(offset + i) % len(terms)] for i in range(quotas[key])]
                    for key, terms in profiles.items()}
        ordered = [(key, terms[i]) for i in range(max(quotas.values()))
                   for key, terms in profiles.items() if i < len(terms)]
    else:
        ordered = [(key, term) for key, terms in profiles.items() for term in terms]
    plan = [(key, term, place) for key, term in ordered
            for place in config["geographic_scopes"]["bundesagentur_fuer_arbeit"]]
    if maximum is not None:
        if maximum < 1:
            raise ValueError("max_queries must be positive")
        plan = plan[:maximum]
    return plan


class RequestBudgetSession:
    def __init__(self, maximum: int, interval: float):
        import requests
        self.session = requests.Session()
        self.maximum = maximum
        self.interval = interval
        self.calls = 0
        self.last = 0.0

    def get(self, *args, **kwargs):
        if self.calls >= self.maximum:
            raise RuntimeError("per-run HTTP request budget exhausted")
        delay = self.interval - (time.monotonic() - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()
        self.calls += 1
        return self.session.get(*args, **kwargs)


def _load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def discovery_candidate_summary(records: list[dict], config: dict) -> dict:
    """Exclude internal applications while retaining every provider observation for audit."""
    excluded = [r for r in records if any(re.fullmatch(
        rf"{re.escape(name)}(?:\s+SE|\s+GmbH)?", str(r.get("company_name") or "").strip(), re.I)
        for name in config.get("excluded_internal_employers", []))]
    return {"active_candidate_records": len(records) - len(excluded),
            "policy_excluded_records": len(excluded),
            "policy_exclusions": [{"source_job_id": r.get("external_job_id"),
                                   "reason": "internal_employer_external_transition_only"}
                                  for r in excluded]}


def run(*, config_path: Path = CONFIG, employers_path: Path = EMPLOYERS,
        results_dir: Path = Path("jobs/results"), database: Any = None,
        max_queries: int | None = None, query_offset: int = 0) -> dict:
    config, employer_config = _load(config_path), _load(employers_path)
    if config.get("schema_version") != "career_intelligence.discovery_v3.v1":
        raise ValueError("Unsupported V3 discovery config")
    if employer_config.get("schema_version") != "career_intelligence.employer_sources.v1":
        raise ValueError("Unsupported employer registry")
    budget_cfg = config["request_budget"]
    session = RequestBudgetSession(int(budget_cfg["max_requests_per_run"]),
                                  float(budget_cfg["minimum_interval_seconds"]))
    limits = RetrievalLimits(page_size=int(budget_cfg["page_size"]),
        max_pages=int(budget_cfg["max_pages_per_query"]),
        max_retries=int(budget_cfg["max_retries"]),
        retry_backoff_seconds=float(budget_cfg["retry_backoff_seconds"]))
    own_db = database is None
    conn_context = connect_database() if own_db else None
    conn = conn_context.__enter__() if conn_context else database
    api_key = BA_API_KEY
    reports = []
    run_group_id = str(uuid4())
    try:
        register_configured_sources(conn, employer_config)
        if api_key:
            query_rows = build_query_plan(config, offset=query_offset, maximum=max_queries)
            # Guard expansion if config changes without a corresponding request-budget update.
            employer_call_budget = sum(
                len(config["geographic_scopes"]["employer_boards"])
                if source.get("active") and source.get("ats") in {"lever", "smartrecruiters"}
                and "EU" in (source.get("regions") or []) else
                len(source.get("regions") or [None])
                if source.get("active") and source.get("ats") in {"lever", "smartrecruiters"}
                else 1
                for source in employer_config.get("sources", []) if source.get("active")
            )
            detail_budget = sum(int(source.get("max_details", 0))
                                for source in employer_config.get("sources", [])
                                if source.get("active"))
            if (len(query_rows) * limits.max_pages + employer_call_budget * limits.max_pages
                    + detail_budget > int(budget_cfg["max_requests_per_run"])):
                raise ValueError("Configured BA query/page plan exceeds request budget")
            for profile, query, location in query_rows:
                try:
                    result = fetch_ba(query=query, location=location, api_key=api_key,
                                      limits=limits, session=session)
                    error_list = result.get("retrieval_errors", [])
                    status = "partial" if error_list else "succeeded"
                    parse_failures = 0
                except ProviderParseError as exc:
                    result = {"records": [], "pages": [], "total_found": None}
                    status = "failed"
                    error_list = [f"{type(exc).__name__}: {exc}"]
                    parse_failures = 1
                except Exception as exc:
                    result = {"records": [], "pages": [], "total_found": None}
                    status = "failed"
                    error_list = [f"{type(exc).__name__}: {exc}"]
                    parse_failures = 0
                telemetry = {"query_text": query, "geographic_scope": location,
                    "queries_attempted": 1, "pages_requested": result.get(
                        "pages_requested", len(result["pages"]) + (1 if status == "failed" else 0)),
                    "pages_retrieved": len(result["pages"]),
                    "raw_results": sum(x["raw_results"] for x in result["pages"]),
                    "retrieval_errors": error_list, "parse_failures": parse_failures}
                persisted = record_run(conn, source_key="bundesagentur_fuer_arbeit",
                    employer=None, provider="bundesagentur_fuer_arbeit", board_id=None,
                    geographic_scope=[location], authorized=True, active=True,
                    access_status="api_key_configured", telemetry=telemetry,
                    records=result["records"], run_group_id=run_group_id,
                    snapshot_complete=False, status=status)
                reports.append({**telemetry, **persisted, "status": status,
                                "profile": profile, "records": len(result["records"]),
                                **discovery_candidate_summary(result["records"], config),
                                "source": "bundesagentur_fuer_arbeit"})
        else:
            reports.append({"source": "bundesagentur_fuer_arbeit", "status": "blocked",
                            "error": "BA_API_KEY is not configured"})

        for source in employer_config.get("sources", []):
            if not source.get("active"):
                continue
            if source.get("access_status") != "public_board":
                reports.append({"source": source.get("employer"), "status": "blocked",
                                "error": "public access is not verified"})
                continue
            provider, board = source["ats"], source["board_id"]
            fn = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
                  "ashby": fetch_ashby, "smartrecruiters": fetch_smartrecruiters}.get(provider)
            if fn is None:
                reports.append({"source": source, "status": "blocked", "error": "unsupported ATS"})
                continue
            key = f"{provider}:{board}"
            regions = source.get("regions") or [None]
            if provider in {"lever", "smartrecruiters"}:
                if "EU" in regions:
                    regions = config["geographic_scopes"]["employer_boards"]
                region_names = {"DE": "Germany", "AT": "Austria", "BE": "Belgium",
                                "CH": "Switzerland", "DK": "Denmark", "FR": "France",
                                "NL": "Netherlands", "SE": "Sweden"}
            else:
                regions = [None]
                region_names = {}
            for region in regions:
                try:
                    kwargs = {"board_id": board, "employer": source["employer"],
                              "limits": limits, "session": session}
                    if provider == "lever" and region:
                        kwargs["location"] = region_names.get(region, region)
                    elif provider == "smartrecruiters" and region:
                        kwargs["country"] = region
                    if provider == "smartrecruiters":
                        # The per-board detail budget is divided across configured regions.
                        kwargs["max_details"] = int(source.get("max_details", 0)) // len(regions)
                        kwargs["query"] = source.get("query")
                    result = fn(**kwargs)
                    error_list = result.get("retrieval_errors", [])
                    status = "partial" if error_list or result.get("detail_errors") else "succeeded"
                    parse_failures = 0
                except ProviderParseError as exc:
                    result = {"records": [], "pages": [], "snapshot_complete": False}
                    status, error_list = "failed", [f"{type(exc).__name__}: {exc}"]
                    parse_failures = 1
                except Exception as exc:
                    result = {"records": [], "pages": [], "snapshot_complete": False}
                    status, error_list = "failed", [f"{type(exc).__name__}: {exc}"]
                    parse_failures = 0
                geo_scope = str(region or ",".join(source["regions"]))
                telemetry = {"query_text": source.get("query"), "geographic_scope": geo_scope,
                    "queries_attempted": 1, "pages_requested": result.get(
                        "pages_requested", len(result["pages"]) + (1 if status == "failed" else 0)),
                    "pages_retrieved": len(result["pages"]),
                    "raw_results": sum(x["raw_results"] for x in result["pages"]),
                    "retrieval_errors": error_list + result.get("detail_errors", []),
                    "parse_failures": parse_failures}
                persisted = record_run(conn, source_key=key, employer=source["employer"],
                    provider=provider, board_id=board, geographic_scope=[geo_scope],
                    authorized=source["access_status"] == "public_board", active=True,
                    access_status=source["access_status"], telemetry=telemetry,
                    records=result["records"], run_group_id=run_group_id,
                    snapshot_complete=bool(result.get("snapshot_complete")) and
                        status == "succeeded" and provider not in {"lever", "smartrecruiters"},
                    status=status)
                reports.append({**telemetry, **persisted, "source": key,
                                "status": status, "records": len(result["records"]),
                                **discovery_candidate_summary(result["records"], config),
                                "details_requested": result.get("details_requested", 0),
                                "scope_complete": bool(result.get("snapshot_complete")),
                                "snapshot_complete": bool(result.get("snapshot_complete")) and
                                    status == "succeeded" and
                                    provider not in {"lever", "smartrecruiters"}})
        finalize_run_group(conn, run_group_id)
        summary = load_monitoring_summary(conn)
        summary["last_run_at"] = datetime.now(UTC).isoformat()
        summary["run_group_id"] = run_group_id
        summary["http_requests"] = session.calls
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "career_discovery_source_health.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        return {"http_requests": session.calls, "runs": reports,
                "strategy_version": config.get("strategy_version", "v3.3"), **summary}
    finally:
        if conn_context:
            conn_context.__exit__(None, None, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--employers", type=Path, default=EMPLOYERS)
    parser.add_argument("--results", type=Path, default=Path("jobs/results"))
    parser.add_argument("--strategy", choices=("v3.3", "v3.4"), default="v3.3")
    parser.add_argument("--max-queries", type=int)
    parser.add_argument("--query-offset", type=int, default=0)
    args = parser.parse_args(argv)
    if args.strategy == "v3.4":
        if args.config == CONFIG:
            args.config = V34_CONFIG
        if args.employers == EMPLOYERS:
            args.employers = V34_EMPLOYERS
        if args.results == Path("jobs/results"):
            args.results = Path(".runtime/career_intelligence/v34")
    print(json.dumps(run(config_path=args.config, employers_path=args.employers,
                         results_dir=args.results, max_queries=args.max_queries,
                         query_offset=args.query_offset), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
