"""Serve the canonical Product V1 Control Center.

The canonical launcher preserves the reviewed read models and deterministic
downstream evidence-preview GET endpoint. Three narrowly allowlisted POST actions
are exposed: the existing employer-origin final-approval gate, append-only
operator review relevance labels, and local Career Intelligence operator state.
None can perform connector registration, activation, ingestion, provider,
ranking or application behavior.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import psycopg
from psycopg.rows import dict_row

if not __package__:  # direct ``python scripts/...`` execution
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts import product_v1_control_center_base as _base
from scripts.product_v1_control_center_actions import (
    ControlCenterActionStop,
    FINAL_APPROVAL_ACTION_PATH,
    apply_final_approval_action,
    parse_final_approval_action_payload,
)
from scripts.product_v1_downstream_preview_runtime import (
    load_downstream_evidence_preview_payload,
)
from scripts.product_v1_job_review_actions import (
    JOB_REVIEW_LABEL_ACTION_PATH,
    apply_job_review_label_action,
    parse_job_review_label_action_payload,
)
from scripts.run_employer_origin_candidate_queue_agent import DatabaseConfig
from src.career_intelligence.adaptive_sources import (
    set_adaptive_source_decision,
    validate_decision,
)
from src.career_intelligence.control_center import (
    load_career_intelligence_control_center,
    merge_career_intelligence_payload,
)
from src.career_intelligence.operator_state import set_operator_state, validate_state
from src.career_intelligence.source_strategy import enrich_source_overview_with_strategy
from src.connectors.registry import build_default_connector_registry
from src.search_intelligence.product_v1_demo_origin_projection import (
    project_demo_origin_truth,
)
from src.search_intelligence.product_v1_downstream_preview import DownstreamPreviewStop


build_parser = _base.build_parser
build_source_connector_overview = _base.build_source_connector_overview
rank_product_jobs = _base.rank_product_jobs
_HARD_FILTER_POLICY_RELATION = "product_v1_hard_filter_policy"
_MAX_ACTION_BODY_BYTES = 4096
CAREER_OPERATOR_STATE_ACTION_PATH = "/api/v1/career-intelligence/operator-state"
CAREER_ADAPTIVE_SOURCE_ACTION_PATH = "/api/v1/career-intelligence/adaptive-sources"


def load_source_connector_overview_payload() -> dict[str, object]:
    """Load source lifecycle truth decorated with Lingjia's Career strategy."""

    return enrich_source_overview_with_strategy(
        _base.load_source_connector_overview_payload(),
        registry=build_default_connector_registry(),
    )


def _merge_structured_job_locations(
    payload: dict[str, object],
    location_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Attach explicit one-to-many Silver locations without rewriting legacy city truth."""

    by_job: dict[int, list[dict[str, object]]] = {}
    for row in location_rows:
        raw_id = row.get("silver_job_id")
        if raw_id is None:
            continue
        try:
            silver_job_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        by_job.setdefault(silver_job_id, []).append(
            {
                "city": str(row.get("city") or "").strip(),
                "country_code": str(row.get("country_code") or "").strip(),
                "is_primary": bool(row.get("is_primary")),
                "evidence_source": str(row.get("evidence_source") or "").strip(),
            }
        )

    result = dict(payload)
    for collection_name in ("job_readiness", "top_jobs"):
        raw_collection = result.get(collection_name)
        if not isinstance(raw_collection, list):
            continue
        enriched: list[object] = []
        for item in raw_collection:
            if not isinstance(item, dict):
                enriched.append(item)
                continue
            copied = dict(item)
            raw_id = copied.get("silver_job_id")
            try:
                silver_job_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                silver_job_id = None
            copied["structured_locations"] = (
                list(by_job.get(silver_job_id, [])) if silver_job_id is not None else []
            )
            enriched.append(copied)
        result[collection_name] = enriched
    return result


def _merge_observed_opportunities(
    payload: dict[str, object],
    opportunity_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Expose market evidence without promoting it into canonical job truth."""

    result = dict(payload)
    result["observed_opportunities"] = opportunity_rows
    summary = dict(result.get("summary") or {})
    summary["observed_opportunity_count"] = len(opportunity_rows)
    summary["verified_market_opportunity_count"] = sum(
        row.get("opportunity_stage") == "vacancy_verified_active"
        for row in opportunity_rows
    )
    summary["pending_market_opportunity_count"] = sum(
        row.get("opportunity_stage")
        in {
            "employer_candidate_missing",
            "origin_source_required",
            "risk_review",
            "vacancy_verification_pending",
        }
        for row in opportunity_rows
    )
    result["summary"] = summary
    boundaries = dict(result.get("boundaries") or {})
    boundaries.update(
        {
            "manual_market_evidence_is_not_job_truth": True,
            "observed_opportunity_is_not_ranking_authority": True,
            "observed_opportunity_is_not_application_authority": True,
        }
    )
    result["boundaries"] = boundaries
    return result


def _merge_job_review_labels(
    payload: dict[str, object],
    label_rows: list[dict[str, object]],
    *,
    capture_available: bool,
) -> dict[str, object]:
    """Project latest operator labels back to jobs without changing product decisions."""

    by_job: dict[int, dict[str, object]] = {}
    for row in label_rows:
        try:
            silver_job_id = int(row["silver_job_id"])
        except (KeyError, TypeError, ValueError):
            continue
        by_job[silver_job_id] = {
            "label_event_id": int(row["label_event_id"]),
            "label": str(row["label"]),
            "reviewed_by": str(row["reviewed_by"]),
            "reviewed_at": row["reviewed_at"],
            "evidence_cutoff": row["evidence_cutoff"],
            "job_evidence_fingerprint": str(row["job_evidence_fingerprint"]),
            "selection_reason": str(row["selection_reason"]),
            "capture_surface": str(row["capture_surface"]),
            "deterministic_signal_visible": bool(row["deterministic_signal_visible"]),
            "ml_signal_visible": bool(row["ml_signal_visible"]),
            "llm_signal_visible": bool(row["llm_signal_visible"]),
            "supervised_target": row["supervised_target"],
            "training_eligible": bool(row["training_eligible"]),
        }

    result = dict(payload)
    for collection_name in ("job_readiness", "top_jobs"):
        raw_collection = result.get(collection_name)
        if not isinstance(raw_collection, list):
            continue
        enriched: list[object] = []
        for item in raw_collection:
            if not isinstance(item, dict):
                enriched.append(item)
                continue
            copied = dict(item)
            raw_id = copied.get("silver_job_id")
            try:
                silver_job_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                silver_job_id = None
            copied["review_label"] = (
                dict(by_job[silver_job_id])
                if silver_job_id is not None and silver_job_id in by_job
                else None
            )
            enriched.append(copied)
        result[collection_name] = enriched

    summary = dict(result.get("summary") or {})
    summary["reviewed_job_count"] = len(by_job)
    summary["training_eligible_review_label_count"] = sum(
        bool(row.get("training_eligible")) for row in by_job.values()
    )
    result["summary"] = summary
    result["review_label_capture"] = {
        "available": capture_available,
        "action_path": JOB_REVIEW_LABEL_ACTION_PATH,
        "labels": ["interesting", "not_relevant", "unsure"],
        "selection_reason": "normal_review",
        "product_authority": False,
    }
    boundaries = dict(result.get("boundaries") or {})
    boundaries.update(
        {
            "operator_review_label_capture_is_append_only": True,
            "operator_review_labels_are_not_ranking_authority": True,
            "operator_review_labels_are_not_application_authority": True,
            "operator_review_labels_do_not_start_training": True,
        }
    )
    result["boundaries"] = boundaries
    return result


def _merge_demo_origin_projection(payload: dict[str, object]) -> dict[str, object]:
    """Separate discovery provenance from current actionable Product URLs."""

    result = dict(payload)
    for collection_name in ("job_readiness", "top_jobs"):
        raw = result.get(collection_name)
        if isinstance(raw, list):
            rows = [item for item in raw if isinstance(item, dict)]
            result[collection_name] = project_demo_origin_truth(rows)

    job_rows = result.get("job_readiness")
    actionable_count = (
        sum(
            bool(item.get("demo_actionable"))
            for item in job_rows
            if isinstance(item, dict)
        )
        if isinstance(job_rows, list)
        else 0
    )
    summary = dict(result.get("summary") or {})
    summary["demo_actionable_job_count"] = actionable_count
    result["summary"] = summary
    boundaries = dict(result.get("boundaries") or {})
    boundaries.update(
        {
            "discovery_url_is_not_product_action_url": True,
            "employer_origin_required_for_demo_action": True,
        }
    )
    result["boundaries"] = boundaries
    return result


def load_product_v1_payload() -> dict[str, object]:
    """Load canonical Product V1 truth plus bounded operator-facing evidence."""

    payload = _base.load_product_v1_payload()
    raw_jobs = payload.get("job_readiness")
    silver_job_ids = (
        sorted(
            {
                int(item["silver_job_id"])
                for item in raw_jobs
                if isinstance(item, dict) and item.get("silver_job_id") is not None
            }
        )
        if isinstance(raw_jobs, list)
        else []
    )

    location_rows: list[dict[str, object]] = []
    opportunity_rows: list[dict[str, object]] = []
    label_rows: list[dict[str, object]] = []
    label_capture_available = False
    with psycopg.connect(
        DatabaseConfig.from_environment().dsn(), row_factory=dict_row
    ) as conn:
        if silver_job_ids and _base._relation_exists(conn, "silver_job_locations"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        silver_job_id,
                        city,
                        country_code,
                        is_primary,
                        evidence_source
                    FROM silver_job_locations
                    WHERE silver_job_id = ANY(%s)
                    ORDER BY silver_job_id, is_primary DESC, id
                    """,
                    (silver_job_ids,),
                )
                location_rows = [dict(row) for row in cur.fetchall()]

        if _base._relation_exists(conn, "gold_market_opportunity_status"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        opportunity_id,
                        evidence_source,
                        observation_channel,
                        normalized_company_key,
                        company_name,
                        title,
                        evidence_url,
                        search_profile_name,
                        search_term,
                        source_seen_at,
                        observed_at,
                        market_evidence ->> 'location' AS location,
                        market_evidence ->> 'remote_signal' AS remote_signal,
                        candidate_id,
                        candidate_status,
                        candidate_risk_level,
                        employer_origin_url,
                        verification_outcome,
                        verified_vacancy_url,
                        verification_reason,
                        verification_observed_at,
                        opportunity_stage,
                        ranking_authority,
                        application_authority
                    FROM gold_market_opportunity_status
                    ORDER BY observed_at DESC, opportunity_id DESC
                    LIMIT 250
                    """
                )
                opportunity_rows = [dict(row) for row in cur.fetchall()]

        label_capture_available = (
            _base._relation_exists(conn, "job_review_relevance_label_events")
            and _base._relation_exists(conn, "gold_job_review_relevance_labels")
        )
        if silver_job_ids and label_capture_available:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        label_event_id,
                        silver_job_id,
                        label,
                        reviewed_by,
                        reviewed_at,
                        evidence_cutoff,
                        job_evidence_fingerprint,
                        selection_reason,
                        capture_surface,
                        deterministic_signal_visible,
                        ml_signal_visible,
                        llm_signal_visible,
                        supervised_target,
                        training_eligible
                    FROM gold_job_review_relevance_labels
                    WHERE silver_job_id = ANY(%s)
                    ORDER BY silver_job_id
                    """,
                    (silver_job_ids,),
                )
                label_rows = [dict(row) for row in cur.fetchall()]

    payload["source_connector_overview"] = enrich_source_overview_with_strategy(
        dict(payload.get("source_connector_overview") or {}),
        registry=build_default_connector_registry(),
    )
    enriched = _merge_structured_job_locations(payload, location_rows)
    enriched = _merge_observed_opportunities(enriched, opportunity_rows)
    enriched = _merge_job_review_labels(
        enriched,
        label_rows,
        capture_available=label_capture_available,
    )
    enriched = _merge_demo_origin_projection(enriched)
    career_payload = load_career_intelligence_control_center(enriched)
    return merge_career_intelligence_payload(enriched, career_payload)


class ProductV1Handler(_base.ProductV1Handler):
    """Canonical read-mostly handler with reviewed low-authority POST actions."""

    server_version = "DeepOceanProductV1/0.6"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/product-v1":
            try:
                self._send_json(load_product_v1_payload())
            except Exception as exc:  # pragma: no cover - runtime diagnostics
                self._send_json(
                    {
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
        if parsed.path == "/api/v1/source-connectors":
            self._send_json(load_source_connector_overview_payload())
            return
        if parsed.path != "/api/v1/product-v1/evidence-preview":
            super().do_GET()
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_ids = query.get("silver_job_id") or []
        if len(raw_ids) != 1:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": "exactly one silver_job_id query parameter is required",
                    "provider_requests": 0,
                    "database_writes": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        try:
            silver_job_id = int(raw_ids[0])
        except (TypeError, ValueError):
            self._send_json(
                {
                    "status": "blocked",
                    "reason": "silver_job_id must be an integer",
                    "provider_requests": 0,
                    "database_writes": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            self._send_json(load_downstream_evidence_preview_payload(silver_job_id))
        except DownstreamPreviewStop as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "provider_requests": 0,
                    "database_writes": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.CONFLICT,
            )
        except Exception as exc:  # pragma: no cover - runtime diagnostics
            self._send_json(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "provider_requests": 0,
                    "database_writes": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _read_action_payload(self) -> object:
        content_type = (
            str(self.headers.get("Content-Type") or "")
            .split(";", 1)[0]
            .strip()
            .casefold()
        )
        if content_type != "application/json":
            raise ControlCenterActionStop("action content type must be application/json")
        raw_length = str(self.headers.get("Content-Length") or "").strip()
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ControlCenterActionStop("valid Content-Length is required") from exc
        if content_length <= 0 or content_length > _MAX_ACTION_BODY_BYTES:
            raise ControlCenterActionStop("action body size is outside the allowed bound")
        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length:
            raise ControlCenterActionStop("action body was truncated")
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlCenterActionStop("action body must be valid UTF-8 JSON") from exc

    def _post_job_review_label(self) -> None:
        try:
            silver_job_id, label = parse_job_review_label_action_payload(
                self._read_action_payload()
            )
            result = apply_job_review_label_action(
                silver_job_id=silver_job_id,
                label=label,
            )
        except ControlCenterActionStop as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except (ValueError, RuntimeError) as exc:
            self._send_json(
                {
                    "status": "review_required",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        status = (
            HTTPStatus.OK
            if result.get("status") in {"applied", "unchanged"}
            else HTTPStatus.CONFLICT
        )
        self._send_json(result, status=status)

    def _post_career_operator_state(self) -> None:
        try:
            payload = self._read_action_payload()
            if not isinstance(payload, dict):
                raise ControlCenterActionStop("action payload must be a JSON object")
            if set(payload) != {"source_file", "state"}:
                raise ControlCenterActionStop("action payload contains unexpected fields")
            source_file = str(payload.get("source_file") or "").strip()
            state = validate_state(str(payload.get("state") or ""))
            updated = set_operator_state(source_file=source_file, state=state)
        except ControlCenterActionStop as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except ValueError as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as exc:
            self._send_json(
                {
                    "status": "review_required",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        self._send_json(
            {
                "status": "applied",
                "source_file": source_file,
                "state": state,
                "operator_state_count": len(updated["states"]),
                "local_runtime_writes": 1,
                "database_writes": 0,
                "provider_requests": 0,
                "product_authority": False,
            }
        )

    def _post_career_adaptive_source_decision(self) -> None:
        try:
            payload = self._read_action_payload()
            if not isinstance(payload, dict):
                raise ControlCenterActionStop("action payload must be a JSON object")
            if set(payload) - {"normalized_company_key", "decision", "company_name"}:
                raise ControlCenterActionStop("action payload contains unexpected fields")
            company_key = str(payload.get("normalized_company_key") or "").strip()
            company_name = str(payload.get("company_name") or "").strip() or None
            decision = validate_decision(str(payload.get("decision") or ""))
            updated = set_adaptive_source_decision(
                normalized_company_key=company_key,
                decision=decision,
                company_name=company_name,
            )
        except ControlCenterActionStop as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except ValueError as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as exc:
            self._send_json(
                {
                    "status": "review_required",
                    "reason": str(exc),
                    "database_writes": 0,
                    "provider_requests": 0,
                    "product_authority": False,
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        self._send_json(
            {
                "status": "applied",
                "normalized_company_key": company_key,
                "decision": decision,
                "adaptive_source_decision_count": len(updated["decisions"]),
                "local_runtime_writes": 1,
                "database_writes": 0,
                "provider_requests": 0,
                "product_authority": False,
                "connector_activation": False,
                "connector_registration": False,
            }
        )

    def do_POST(self) -> None:  # noqa: N802 - exact reviewed action allowlist
        parsed = urlparse(self.path)
        if parsed.path == CAREER_ADAPTIVE_SOURCE_ACTION_PATH:
            self._post_career_adaptive_source_decision()
            return
        if parsed.path == CAREER_OPERATOR_STATE_ACTION_PATH:
            self._post_career_operator_state()
            return
        if parsed.path == JOB_REVIEW_LABEL_ACTION_PATH:
            self._post_job_review_label()
            return
        if parsed.path != FINAL_APPROVAL_ACTION_PATH:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": "Product V1 POST route is not in the reviewed action allowlist.",
                },
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )
            return

        try:
            candidate_id, confirmation = parse_final_approval_action_payload(
                self._read_action_payload()
            )
            result = apply_final_approval_action(
                candidate_id=candidate_id,
                confirmation=confirmation,
            )
        except ControlCenterActionStop as exc:
            self._send_json(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "provider_requests": 0,
                    "source_activation": False,
                    "product_authority": False,
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except (ValueError, RuntimeError) as exc:
            self._send_json(
                {
                    "status": "review_required",
                    "reason": str(exc),
                    "provider_requests": 0,
                    "source_activation": False,
                    "product_authority": False,
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        status = (
            HTTPStatus.OK
            if result.get("status") in {"applied", "not_applicable"}
            else HTTPStatus.CONFLICT
        )
        self._send_json(result, status=status)


def run_server(args: argparse.Namespace) -> None:
    server = ThreadingHTTPServer((args.host, args.port), ProductV1Handler)
    server.frontend_dist = args.frontend_dist  # type: ignore[attr-defined]
    print(f"Deep Ocean Product V1 Control Center: http://{args.host}:{args.port}/")
    print(
        "Boundary: read models + observed opportunities + deterministic evidence preview "
        "+ reviewed final-approval and append-only review-label actions; no provider call, "
        "connector registration, source activation, ingestion, ranking mutation, model "
        "training or application submission."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProduct V1 Control Center stopped by operator.")
    finally:
        server.server_close()


def main() -> None:
    run_server(build_parser().parse_args())


def __getattr__(name: str):
    """Preserve existing module-level read helpers without duplicating the base."""

    return getattr(_base, name)


if __name__ == "__main__":
    main()
