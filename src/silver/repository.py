import json

import psycopg
from psycopg.rows import dict_row

from src.config import get_database_config


class SilverJobRepository:
    def __init__(self) -> None:
        self.connection_config = get_database_config()

    def get_connection(self):
        return psycopg.connect(
            **self.connection_config,
            row_factory=dict_row,
        )

    def _load_unprocessed_raw_jobs(
        self,
        *,
        limit: int,
        source_patterns: list[str] | None,
        ingestion_run_id: int | None,
        enforce_read_only: bool,
    ) -> tuple[list[dict], str | None]:
        source_patterns = source_patterns or []

        filters: list[str] = []
        params: list[object] = []

        if source_patterns:
            source_clauses = []

            for pattern in source_patterns:
                if "%" in pattern:
                    source_clauses.append("r.source_name LIKE %s")
                else:
                    source_clauses.append("r.source_name = %s")

                params.append(pattern)

            filters.append("(" + " OR ".join(source_clauses) + ")")

        if ingestion_run_id is not None:
            if ingestion_run_id <= 0:
                raise ValueError("ingestion_run_id must be a positive integer")
            filters.append("r.ingestion_run_id = %s")
            params.append(ingestion_run_id)

        filter_sql = ""
        if filters:
            filter_sql = "AND " + " AND ".join(filters)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                transaction_read_only: str | None = None
                if enforce_read_only:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SHOW transaction_read_only")
                    row = cur.fetchone()
                    transaction_read_only = (
                        str(row["transaction_read_only"]) if row else None
                    )
                    if transaction_read_only != "on":
                        raise RuntimeError(
                            "Silver preflight transaction is not read-only"
                        )

                cur.execute(
                    f"""
                    SELECT
                        r.id,
                        r.source_name,
                        r.external_job_id,
                        r.source_url,
                        r.raw_data
                    FROM raw_jobs r
                    LEFT JOIN silver_jobs s
                        ON s.raw_job_id = r.id
                    LEFT JOIN silver_processing_decisions d
                        ON d.raw_job_id = r.id
                    WHERE s.id IS NULL
                      AND d.id IS NULL
                      {filter_sql}
                    ORDER BY r.id
                    LIMIT %s;
                    """,
                    (*params, limit),
                )

                return list(cur.fetchall()), transaction_read_only

    def load_unprocessed_raw_jobs(
        self,
        limit: int = 100,
        source_patterns: list[str] | None = None,
        ingestion_run_id: int | None = None,
    ) -> list[dict]:
        rows, _ = self._load_unprocessed_raw_jobs(
            limit=limit,
            source_patterns=source_patterns,
            ingestion_run_id=ingestion_run_id,
            enforce_read_only=False,
        )
        return rows

    def load_raw_jobs_by_ids(
        self,
        raw_job_ids: list[int],
        source_patterns: list[str] | None = None,
    ) -> list[dict]:
        if not raw_job_ids:
            return []

        if any(raw_job_id <= 0 for raw_job_id in raw_job_ids):
            raise ValueError("raw_job_ids must be positive integers")

        source_patterns = source_patterns or []
        filters: list[str] = ["r.id = ANY(%s::bigint[])"]
        params: list[object] = [raw_job_ids]

        if source_patterns:
            source_clauses = []

            for pattern in source_patterns:
                if "%" in pattern:
                    source_clauses.append("r.source_name LIKE %s")
                else:
                    source_clauses.append("r.source_name = %s")

                params.append(pattern)

            filters.append("(" + " OR ".join(source_clauses) + ")")

        filter_sql = " AND ".join(filters)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        r.id,
                        r.source_name,
                        r.external_job_id,
                        r.source_url,
                        r.raw_data
                    FROM raw_jobs r
                    WHERE {filter_sql}
                    ORDER BY r.id;
                    """,
                    tuple(params),
                )

                return list(cur.fetchall())

    def preview_unprocessed_raw_jobs(
        self,
        limit: int = 100,
        source_patterns: list[str] | None = None,
        ingestion_run_id: int | None = None,
    ) -> tuple[list[dict], str]:
        rows, transaction_read_only = self._load_unprocessed_raw_jobs(
            limit=limit,
            source_patterns=source_patterns,
            ingestion_run_id=ingestion_run_id,
            enforce_read_only=True,
        )
        if transaction_read_only is None:
            raise RuntimeError("Missing transaction read-only proof")
        return rows, transaction_read_only

    def upsert_silver_job(self, job: dict) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO silver_jobs (
                        raw_job_id,
                        source_name,
                        external_job_id,
                        source_url,
                        title,
                        company_name,
                        city,
                        postal_code,
                        country,
                        publication_date,
                        normalized_title,
                        normalized_company_name,
                        normalized_location,
                        canonical_status,
                        canonical_source_type,
                        canonical_key_candidate
                    )
                    VALUES (
                        %(raw_job_id)s,
                        %(source_name)s,
                        %(external_job_id)s,
                        %(source_url)s,
                        %(title)s,
                        %(company_name)s,
                        %(city)s,
                        %(postal_code)s,
                        %(country)s,
                        %(publication_date)s,
                        %(normalized_title)s,
                        %(normalized_company_name)s,
                        %(normalized_location)s,
                        %(canonical_status)s,
                        %(canonical_source_type)s,
                        %(canonical_key_candidate)s
                    )
                    ON CONFLICT (raw_job_id)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        external_job_id = EXCLUDED.external_job_id,
                        source_url = EXCLUDED.source_url,
                        title = EXCLUDED.title,
                        company_name = EXCLUDED.company_name,
                        city = EXCLUDED.city,
                        postal_code = EXCLUDED.postal_code,
                        country = EXCLUDED.country,
                        publication_date = EXCLUDED.publication_date,
                        normalized_title = EXCLUDED.normalized_title,
                        normalized_company_name = EXCLUDED.normalized_company_name,
                        normalized_location = EXCLUDED.normalized_location,
                        canonical_status = EXCLUDED.canonical_status,
                        canonical_source_type = EXCLUDED.canonical_source_type,
                        canonical_key_candidate = EXCLUDED.canonical_key_candidate,
                        normalized_at = NOW(),
                        updated_at = NOW();
                    """,
                    job,
                )

            conn.commit()

    def backfill_canonicalization_fields(self) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE silver_jobs
                    SET
                        normalized_title = NULLIF(
                            regexp_replace(lower(trim(COALESCE(title, ''))), '\\s+', ' ', 'g'),
                            ''
                        ),
                        normalized_company_name = NULLIF(
                            regexp_replace(lower(trim(COALESCE(company_name, ''))), '\\s+', ' ', 'g'),
                            ''
                        ),
                        normalized_location = NULLIF(
                            concat_ws(
                                ' | ',
                                NULLIF(regexp_replace(lower(trim(COALESCE(city, ''))), '\\s+', ' ', 'g'), ''),
                                NULLIF(regexp_replace(lower(trim(COALESCE(postal_code, ''))), '\\s+', ' ', 'g'), ''),
                                NULLIF(regexp_replace(lower(trim(COALESCE(country, ''))), '\\s+', ' ', 'g'), '')
                            ),
                            ''
                        ),
                        canonical_status = COALESCE(canonical_status, 'discovery_only'),
                        canonical_source_type = COALESCE(canonical_source_type, 'unknown'),
                        canonical_key_candidate = NULLIF(
                            concat_ws(
                                ' :: ',
                                NULLIF(regexp_replace(lower(trim(COALESCE(company_name, ''))), '\\s+', ' ', 'g'), ''),
                                NULLIF(regexp_replace(lower(trim(COALESCE(title, ''))), '\\s+', ' ', 'g'), ''),
                                NULLIF(
                                    concat_ws(
                                        ' | ',
                                        NULLIF(regexp_replace(lower(trim(COALESCE(city, ''))), '\\s+', ' ', 'g'), ''),
                                        NULLIF(regexp_replace(lower(trim(COALESCE(postal_code, ''))), '\\s+', ' ', 'g'), ''),
                                        NULLIF(regexp_replace(lower(trim(COALESCE(country, ''))), '\\s+', ' ', 'g'), '')
                                    ),
                                    ''
                                )
                            ),
                            ''
                        ),
                        updated_at = NOW()
                    WHERE canonical_key_candidate IS NULL;
                    """
                )
                updated_count = cur.rowcount

            conn.commit()

        return updated_count

    def record_processing_decision(
        self,
        raw_job_id: int,
        decision: str,
        reason: str | None = None,
        role_matches: list[str] | None = None,
        skill_matches: list[str] | None = None,
        accessibility_matches: list[str] | None = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO silver_processing_decisions (
                        raw_job_id,
                        decision,
                        reason,
                        role_matches,
                        skill_matches,
                        accessibility_matches
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::jsonb,
                        %s::jsonb
                    )
                    ON CONFLICT (raw_job_id)
                    DO UPDATE SET
                        decision = EXCLUDED.decision,
                        reason = EXCLUDED.reason,
                        role_matches = EXCLUDED.role_matches,
                        skill_matches = EXCLUDED.skill_matches,
                        accessibility_matches = EXCLUDED.accessibility_matches,
                        decided_at = NOW();
                    """,
                    (
                        raw_job_id,
                        decision,
                        reason,
                        json.dumps(role_matches or []),
                        json.dumps(skill_matches or []),
                        json.dumps(accessibility_matches or []),
                    ),
                )

            conn.commit()
