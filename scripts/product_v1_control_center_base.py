"""Serve the read-only Product V1 API and built React Control Center.

This server exposes product state only. It has no POST routes, provider calls,
source activation, candidate mutation, application submission or scheduler writes.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from src.connectors.registry import build_default_connector_registry
from src.config import get_database_config
from src.search_intelligence.product_v1 import (
    OperatorDecisionRequired,
    ProductJob,
    RankingPolicy,
    rank_product_jobs,
)
from src.search_intelligence.product_v1_service import build_product_v1_payload
from src.search_intelligence.source_connector_overview import (
    build_source_connector_overview,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_DIST = ROOT / "frontend" / "control-center" / "dist"


def _relation_exists(
    conn: psycopg.Connection[object], relation_name: str
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS present",
            (f"public.{relation_name}",),
        )
        row = cur.fetchone()
    return bool(row and row["present"])


def _fetch_all(
    conn: psycopg.Connection[object], query: str
) -> list[dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(query)
        return [dict(row) for row in cur.fetchall()]


def _fetch_one(
    conn: psycopg.Connection[object], query: str
) -> dict[str, object] | None:
    with conn.cursor() as cur:
        cur.execute(query)
        row = cur.fetchone()
    return dict(row) if row else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _build_top_jobs(
    job_readiness: list[dict[str, object]],
    ranking_policy: dict[str, object] | None,
) -> list[dict[str, object]]:
    if ranking_policy is None:
        return []
    raw_weights = ranking_policy.get("ranking_weights")
    factor_weights = (
        {str(key): float(value) for key, value in raw_weights.items()}
        if isinstance(raw_weights, dict)
        else {}
    )
    policy = RankingPolicy(
        status=str(ranking_policy.get("status") or "operator_decision_required"),
        top_job_limit=(
            int(ranking_policy["top_job_limit"])
            if ranking_policy.get("top_job_limit") is not None
            else None
        ),
        minimum_quality_score=(
            float(ranking_policy["minimum_quality_score"])
            if ranking_policy.get("minimum_quality_score") is not None
            else None
        ),
        factor_weights=factor_weights,
        comparable_score_delta=(
            float(ranking_policy["comparable_score_delta"])
            if ranking_policy.get("comparable_score_delta") is not None
            else None
        ),
        explanation_mode=(
            str(ranking_policy["explanation_mode"])
            if ranking_policy.get("explanation_mode") is not None
            else None
        ),
        policy_version=(
            str(ranking_policy["policy_version"])
            if ranking_policy.get("policy_version") is not None
            else None
        ),
    )
    jobs = [
        ProductJob(
            silver_job_id=int(row["silver_job_id"]),
            title=str(row.get("title") or ""),
            company_name=str(row.get("company_name") or ""),
            source_url=(
                str(row["source_url"])
                if row.get("source_url") is not None
                else None
            ),
            origin_validation_status=str(
                row.get("origin_validation_status") or "pending"
            ),
            activity_status=str(row.get("activity_status") or "unknown"),
            hard_filter_status=str(row.get("hard_filter_status") or "unknown"),
            profile_direction_score=(
                float(row["profile_direction_score"])
                if row.get("profile_direction_score") is not None
                else None
            ),
            data_focus_score=(
                float(row["data_focus_score"])
                if row.get("data_focus_score") is not None
                else None
            ),
            reliability_focus_score=(
                float(row["reliability_focus_score"])
                if row.get("reliability_focus_score") is not None
                else None
            ),
            evidence_quality_score=(
                float(row["evidence_quality_score"])
                if row.get("evidence_quality_score") is not None
                else None
            ),
            work_model=str(row.get("work_model") or "unknown"),
            commute_minutes=(
                int(row["commute_minutes"])
                if row.get("commute_minutes") is not None
                else None
            ),
            public_transport_quality=str(
                row.get("public_transport_quality") or "unknown"
            ),
            explanations=_string_tuple(row.get("explanations")),
            uncertainties=_string_tuple(row.get("uncertainties")),
        )
        for row in job_readiness
        if row.get("silver_job_id") is not None
    ]
    try:
        ranked = rank_product_jobs(jobs, policy)
    except OperatorDecisionRequired:
        return []

    by_id = {int(row["silver_job_id"]): row for row in job_readiness}
    result: list[dict[str, object]] = []
    for item in ranked:
        source = dict(by_id[item.job.silver_job_id])
        source["product_rank"] = item.rank
        source["overall_quality_score"] = item.overall_quality_score
        source["ranking_reasons"] = list(item.ranking_reasons)
        result.append(source)
    return result


def _load_source_candidates(
    conn: psycopg.Connection[object],
) -> list[dict[str, object]]:
    if not _relation_exists(conn, "employer_origin_source_candidates"):
        return []

    lifecycle_join = ""
    module_path_column = "NULL::text AS connector_module_path"
    if _relation_exists(conn, "gold_candidate_lifecycle_status"):
        lifecycle_join = (
            "LEFT JOIN gold_candidate_lifecycle_status lifecycle "
            "ON lifecycle.candidate_id = candidate.id"
        )
        module_path_column = "lifecycle.connector_module_path"

    gate_join = ""
    gate_columns = """
        NULL::text AS connector_validation_gate_status,
        NULL::text AS connector_validation_gate_decision,
        NULL::text AS final_approval_gate_status,
        NULL::text AS final_approval_gate_decision
    """
    if _relation_exists(conn, "employer_origin_candidate_gate_reviews"):
        gate_join = """
            LEFT JOIN employer_origin_candidate_gate_reviews validation
              ON validation.candidate_id = candidate.id
             AND validation.gate_name = 'connector_validation_gate'
            LEFT JOIN employer_origin_candidate_gate_reviews approval
              ON approval.candidate_id = candidate.id
             AND approval.gate_name = 'final_approval_gate'
        """
        gate_columns = """
            validation.gate_status AS connector_validation_gate_status,
            validation.decision AS connector_validation_gate_decision,
            approval.gate_status AS final_approval_gate_status,
            approval.decision AS final_approval_gate_decision
        """

    return _fetch_all(
        conn,
        f"""
        SELECT
            candidate.id AS candidate_id,
            candidate.company_name,
            candidate.source_name_candidate AS source_name,
            candidate.source_type_candidate AS source_type,
            candidate.status AS candidate_status,
            candidate.updated_at,
            {module_path_column},
            {gate_columns}
        FROM employer_origin_source_candidates candidate
        {lifecycle_join}
        {gate_join}
        ORDER BY candidate.updated_at, candidate.id
        """,
    )


def _load_search_profile_summary(
    conn: psycopg.Connection[object],
) -> list[dict[str, object]]:
    if not _relation_exists(conn, "search_profiles"):
        return []
    if _relation_exists(conn, "search_terms"):
        return _fetch_all(
            conn,
            """
            SELECT
                profile.source_name,
                count(DISTINCT profile.id) AS profile_count,
                count(DISTINCT profile.id) FILTER (
                    WHERE profile.is_active
                ) AS active_profile_count,
                count(term.id) FILTER (
                    WHERE profile.is_active AND term.is_active
                ) AS active_search_term_count
            FROM search_profiles profile
            LEFT JOIN search_terms term
              ON term.search_profile_id = profile.id
            GROUP BY profile.source_name
            ORDER BY profile.source_name
            """,
        )
    return _fetch_all(
        conn,
        """
        SELECT
            source_name,
            count(*) AS profile_count,
            count(*) FILTER (WHERE is_active) AS active_profile_count,
            0::bigint AS active_search_term_count
        FROM search_profiles
        GROUP BY source_name
        ORDER BY source_name
        """,
    )


def _load_latest_ingestion_runs(
    conn: psycopg.Connection[object],
) -> list[dict[str, object]]:
    if not _relation_exists(conn, "ingestion_runs"):
        return []
    return _fetch_all(
        conn,
        """
        SELECT DISTINCT ON (source_name)
            source_name,
            status AS last_ingestion_status,
            started_at,
            finished_at,
            total_loaded,
            inserted_count,
            error_message
        FROM ingestion_runs
        ORDER BY source_name, started_at DESC, id DESC
        """,
    )


def _load_layer_presence(
    conn: psycopg.Connection[object],
) -> list[dict[str, object]]:
    counts: dict[str, dict[str, object]] = {}
    if _relation_exists(conn, "raw_jobs"):
        for row in _fetch_all(
            conn,
            """
            SELECT source_name, count(*) AS bronze_count
            FROM raw_jobs
            GROUP BY source_name
            """,
        ):
            source_name = str(row["source_name"])
            counts.setdefault(source_name, {"source_name": source_name})[
                "bronze_count"
            ] = row["bronze_count"]
    if _relation_exists(conn, "silver_jobs"):
        for row in _fetch_all(
            conn,
            """
            SELECT source_name, count(*) AS silver_count
            FROM silver_jobs
            GROUP BY source_name
            """,
        ):
            source_name = str(row["source_name"])
            counts.setdefault(source_name, {"source_name": source_name})[
                "silver_count"
            ] = row["silver_count"]
    return [counts[source_name] for source_name in sorted(counts)]


def _connector_artifact_exists(candidate: dict[str, object]) -> bool:
    raw_path = candidate.get("connector_module_path")
    if not raw_path:
        return False
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = ROOT / path
    return path.is_file()


def _load_source_connector_overview(
    conn: psycopg.Connection[object],
) -> dict[str, object]:
    return build_source_connector_overview(
        registry=build_default_connector_registry(),
        candidates=_load_source_candidates(conn),
        search_profiles=_load_search_profile_summary(conn),
        ingestion_runs=_load_latest_ingestion_runs(conn),
        layer_presence=_load_layer_presence(conn),
        implementation_probe=_connector_artifact_exists,
        truth_availability={
            "search_profiles": _relation_exists(conn, "search_profiles"),
            "ingestion_runs": _relation_exists(conn, "ingestion_runs"),
            "raw_jobs": _relation_exists(conn, "raw_jobs"),
            "silver_jobs": _relation_exists(conn, "silver_jobs"),
        },
    )


def load_source_connector_overview_payload() -> dict[str, object]:
    with psycopg.connect(**get_database_config(), row_factory=dict_row) as conn:
        return _load_source_connector_overview(conn)


def load_product_v1_payload() -> dict[str, object]:
    with psycopg.connect(**get_database_config(), row_factory=dict_row) as conn:
        source_connector_overview = _load_source_connector_overview(conn)
        required_relations = {
            "search_term_cycle_state",
            "product_v1_ranking_policy",
            "product_v1_hard_filter_policy",
            "gold_product_v1_hard_filter_evaluation",
            "gold_product_v1_job_readiness",
            "gold_product_v1_top_jobs",
            "gold_product_v1_application_readiness",
            "application_source_documents",
        }
        migration_ready = all(
            _relation_exists(conn, relation) for relation in required_relations
        )
        if not migration_ready:
            return build_product_v1_payload(
                wave_states=[],
                job_readiness=[],
                top_jobs=[],
                ranking_policy=None,
                application_readiness=[],
                application_sources=[],
                migration_ready=False,
                hard_filter_policy=None,
                source_connector_overview=source_connector_overview,
            )

        wave_states = _fetch_all(
            conn,
            """
            SELECT
                source_name,
                search_profile_name,
                search_term,
                current_interval_days,
                next_due_at,
                last_quality_score,
                last_new_company_count,
                last_known_cooldown_hit_count,
                is_not_exclusion_enabled,
                current_exclusion_wave_index,
                last_wave_action,
                last_wave_completed_at
            FROM search_term_cycle_state
            WHERE source_name = 'stepstone'
            ORDER BY search_profile_name, search_term
            """,
        )
        job_readiness = _fetch_all(
            conn,
            """
            SELECT *
            FROM gold_product_v1_job_readiness
            ORDER BY
                CASE product_readiness_status
                    WHEN 'rankable' THEN 0
                    WHEN 'ranking_policy_required' THEN 1
                    WHEN 'hard_filter_evidence_required' THEN 2
                    WHEN 'origin_validation_required' THEN 3
                    ELSE 4
                END,
                profile_direction_score DESC NULLS LAST,
                publication_date DESC NULLS LAST,
                silver_job_id
            """,
        )
        ranking_policy = _fetch_one(
            conn,
            """
            SELECT *
            FROM product_v1_ranking_policy
            WHERE policy_key = 'default'
            """,
        )
        hard_filter_policy = _fetch_one(
            conn,
            """
            SELECT *
            FROM product_v1_hard_filter_policy
            WHERE policy_key = 'default'
            """,
        )
        top_jobs = _build_top_jobs(job_readiness, ranking_policy)
        application_readiness = _fetch_all(
            conn,
            """
            SELECT *
            FROM gold_product_v1_application_readiness
            ORDER BY silver_job_id
            """,
        )
        application_sources = _fetch_all(
            conn,
            """
            SELECT
                id,
                document_type,
                source_label,
                source_reference,
                content_sha256,
                status,
                approved_by,
                approved_at,
                created_at
            FROM application_source_documents
            ORDER BY document_type, created_at DESC
            """,
        )

    return build_product_v1_payload(
        wave_states=wave_states,
        job_readiness=job_readiness,
        top_jobs=top_jobs,
        ranking_policy=ranking_policy,
        application_readiness=application_readiness,
        application_sources=application_sources,
        migration_ready=True,
        hard_filter_policy=hard_filter_policy,
        source_connector_overview=source_connector_overview,
    )


class ProductV1Handler(BaseHTTPRequestHandler):
    server_version = "DeepOceanProductV1/0.1"

    @property
    def frontend_dist(self) -> Path:
        return self.server.frontend_dist  # type: ignore[attr-defined]

    def _send_bytes(
        self,
        body: bytes,
        *,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self, payload: object, *, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        self._send_bytes(
            body,
            content_type="application/json; charset=utf-8",
            status=status,
        )

    def _serve_frontend(self, requested_path: str) -> None:
        root = self.frontend_dist.resolve()
        if not (root / "index.html").is_file():
            body = (
                "<!doctype html><html><body><h1>React build required</h1>"
                "<p>Build frontend/control-center and restart this server. "
                "The read-only API is available at <code>/api/v1/product-v1</code>.</p>"
                "</body></html>"
            ).encode("utf-8")
            self._send_bytes(
                body,
                content_type="text/html; charset=utf-8",
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        relative = requested_path.lstrip("/")
        candidate = (root / relative).resolve() if relative else root / "index.html"
        if root not in candidate.parents and candidate != root:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            candidate = root / "index.html"
        content_type = (
            mimetypes.guess_type(candidate.name)[0]
            or "application/octet-stream"
        )
        cache = (
            "public, max-age=31536000, immutable"
            if "/assets/" in requested_path
            else "no-cache"
        )
        self._send_bytes(
            candidate.read_bytes(),
            content_type=content_type,
            cache_control=cache,
        )

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json(
                {
                    "status": "ok",
                    "mode": "read_only",
                    "provider_calls": False,
                    "mutations": False,
                }
            )
            return
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
            try:
                self._send_json(load_source_connector_overview_payload())
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
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self._serve_frontend(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - explicit read-only boundary
        self._send_json(
            {
                "status": "blocked",
                "reason": "Product V1 API is read-only; operator actions require separate reviewed contracts.",
            },
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default=os.environ.get("PRODUCT_V1_UI_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PRODUCT_V1_UI_PORT", "8780")),
    )
    parser.add_argument(
        "--frontend-dist", type=Path, default=DEFAULT_FRONTEND_DIST
    )
    return parser


def run_server(args: argparse.Namespace) -> None:
    server = ThreadingHTTPServer((args.host, args.port), ProductV1Handler)
    server.frontend_dist = args.frontend_dist  # type: ignore[attr-defined]
    print(
        f"Deep Ocean Product V1 Control Center: http://{args.host}:{args.port}/"
    )
    print(
        "Boundary: read-only API, no provider call, no source activation, "
        "no application submission."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProduct V1 Control Center stopped by operator.")
    finally:
        server.server_close()


def main() -> None:
    run_server(build_parser().parse_args())


if __name__ == "__main__":
    main()
