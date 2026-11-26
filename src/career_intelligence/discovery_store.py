"""Persistence and conservative identity rules for V3 vacancy observations."""
from __future__ import annotations

from hashlib import sha256
from datetime import UTC, datetime
import json
import re
from typing import Any, Mapping
from psycopg.rows import tuple_row

from src.career_intelligence.source_adapters import canonical_url


def normalize_identity_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def vacancy_keys(record: Mapping[str, Any]) -> tuple[str, str | None]:
    source = str(record.get("source_name") or "")
    source_id = str(record.get("external_job_id") or "").strip()
    source_key = sha256(f"{source}\0{source_id}".encode()).hexdigest()
    url = canonical_url(str(record.get("source_url") or ""))
    canonical = "url:" + sha256(url.encode()).hexdigest() if url else None
    return source_key, canonical


def cautious_alias(record: Mapping[str, Any]) -> str | None:
    parts = [normalize_identity_text(record.get(key))
             for key in ("company_name", "title", "location")]
    if not all(parts):
        return None
    return "ctl:" + sha256("|".join(parts).encode()).hexdigest()


def content_hash(record: Mapping[str, Any]) -> str:
    keys = ("title", "company_name", "description", "source_url")
    # BA location results are query-dependent facets: a city-scoped query may
    # return only the matching address for a posting with several locations.
    if record.get("source_name") != "bundesagentur_fuer_arbeit":
        keys += ("location",)
    data = {key: record.get(key) for key in keys}
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def change_event(previous_hash: str | None, current_hash: str,
                 lifecycle: str = "active") -> str | None:
    if lifecycle != "active":
        return "reappeared"
    if previous_hash and previous_hash != current_hash:
        return "changed"
    return None


def parse_source_time(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            # Lever timestamps are milliseconds since epoch.
            return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def register_configured_sources(conn: Any, employer_config: Mapping[str, Any]) -> None:
    """Upsert configured and unresolved target sources without claiming health."""
    with conn.transaction():
        with conn.cursor() as cur:
            for group, active in (("sources", True), ("targets", False)):
                for source in employer_config.get(group, []):
                    provider = str(source.get("ats") or "unknown")
                    board = source.get("board_id")
                    key = f"{provider}:{board}" if board else (
                        "unverified:" + normalize_identity_text(source.get("employer"))
                    )
                    is_active = bool(active and source.get("active"))
                    access = str(source.get("access_status") or "unverified")
                    cur.execute("""INSERT INTO career_discovery_sources
                        (source_key,employer_name,provider,board_id,geographic_scope,
                         configured,authorized,active,access_status,health_status)
                        VALUES (%s,%s,%s,%s,%s::jsonb,TRUE,%s,%s,%s,'unknown')
                        ON CONFLICT(source_key) DO UPDATE SET
                        employer_name=EXCLUDED.employer_name,provider=EXCLUDED.provider,
                        board_id=EXCLUDED.board_id,geographic_scope=EXCLUDED.geographic_scope,
                        configured=TRUE,authorized=EXCLUDED.authorized,active=EXCLUDED.active,
                        access_status=EXCLUDED.access_status,updated_at=NOW()""",
                        (key, source.get("employer"), provider, board,
                         json.dumps(source.get("regions") or []), access == "public_board",
                         is_active, access))


def record_run(conn: Any, *, source_key: str, employer: str | None, provider: str,
               board_id: str | None, geographic_scope: list[str], authorized: bool,
               active: bool, access_status: str, telemetry: Mapping[str, Any],
               records: list[dict[str, Any]], run_group_id: str,
               snapshot_complete: bool = False,
               status: str = "succeeded") -> dict[str, int]:
    """Persist source health, one run, all source observations and new/change events."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO career_discovery_sources
                (source_key, employer_name, provider, board_id, geographic_scope,
                 configured, authorized, active, access_status, last_retrieval_at,
                 last_success_at, health_status, updated_at)
                VALUES (%s,%s,%s,%s,%s::jsonb,TRUE,%s,%s,%s,NOW(),
                    CASE WHEN %s IN ('succeeded','partial') THEN NOW() ELSE NULL END,
                    %s,NOW())
                ON CONFLICT (source_key) DO UPDATE SET employer_name=EXCLUDED.employer_name,
                provider=EXCLUDED.provider, board_id=EXCLUDED.board_id,
                geographic_scope=EXCLUDED.geographic_scope, configured=TRUE,
                authorized=EXCLUDED.authorized, active=EXCLUDED.active,
                access_status=EXCLUDED.access_status, last_retrieval_at=NOW(),
                last_success_at=CASE WHEN EXCLUDED.health_status IN ('healthy','partial')
                    THEN NOW() ELSE career_discovery_sources.last_success_at END,
                health_status=EXCLUDED.health_status, updated_at=NOW() RETURNING id""",
                (source_key, employer, provider, board_id, json.dumps(geographic_scope),
                 authorized, active, access_status, status,
                 "healthy" if status == "succeeded" else "partial" if status == "partial" else "failed"))
            source_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO career_discovery_runs
                (source_id, source_key, run_group_id, query_text, geographic_scope, status,
                 queries_attempted, pages_requested, pages_retrieved, raw_results,
                 unique_vacancies, cross_source_duplicates, parse_failures,snapshot_complete,
                 retrieval_errors, completed_at)
                VALUES (%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s::jsonb,NOW()) RETURNING id""",
                (source_id, source_key, run_group_id, telemetry.get("query_text"),
                 telemetry.get("geographic_scope"), status,
                 telemetry.get("queries_attempted", 1), telemetry.get("pages_requested", 0),
                 telemetry.get("pages_retrieved", 0), telemetry.get("raw_results", len(records)),
                 telemetry.get("parse_failures", 0), bool(snapshot_complete and status == "succeeded"),
                 json.dumps(telemetry.get("retrieval_errors", []))))
            run_id = cur.fetchone()[0]
            unique = duplicates = 0
            seen_vacancy_ids: set[int] = set()
            for record in records:
                source_identity, canonical_key = vacancy_keys(record)
                alias = cautious_alias(record)
                digest = content_hash(record)
                # Source IDs are definitive within a provider. URL/metadata aliases
                # are only allowed to join a different source/provider.
                found = None
                source_job_id = str(record.get("external_job_id") or "").strip()
                if source_job_id:
                    cur.execute("""SELECT v.id,v.content_sha256,v.lifecycle_status
                        FROM career_discovery_source_identities i
                        JOIN career_discovery_vacancies v ON v.id=i.vacancy_id
                        WHERE i.source_key=%s AND i.source_job_id=%s""",
                        (source_key, source_job_id))
                    found = cur.fetchone()
                if not found and source_job_id:
                    cur.execute("""SELECT v.id, v.content_sha256, v.lifecycle_status
                    FROM career_discovery_observations o
                    JOIN career_discovery_vacancies v ON v.id=o.vacancy_id
                    WHERE o.source_key=%s AND o.source_job_id=%s
                    ORDER BY o.observed_at DESC LIMIT 1""",
                    (source_key, source_job_id))
                    found = cur.fetchone()
                if not found and canonical_key:
                    cur.execute("""SELECT v.id,v.content_sha256,v.lifecycle_status
                        FROM career_discovery_vacancy_aliases a
                        JOIN career_discovery_vacancies v ON v.id=a.vacancy_id
                        WHERE a.alias_key=%s AND NOT EXISTS
                          (SELECT 1 FROM career_discovery_observations o
                           WHERE o.vacancy_id=v.id AND o.source_key=%s)""",
                        (canonical_key, source_key))
                    found = cur.fetchone()
                if not found and alias:
                    cur.execute("""SELECT v.id,v.content_sha256,v.lifecycle_status
                        FROM career_discovery_vacancy_aliases a
                        JOIN career_discovery_vacancies v ON v.id=a.vacancy_id
                        WHERE a.alias_key=%s AND NOT EXISTS
                          (SELECT 1 FROM career_discovery_observations o
                           WHERE o.vacancy_id=v.id AND o.source_key=%s)""",
                        (alias, source_key))
                    found = cur.fetchone()
                if found:
                    vacancy_id, old_hash, lifecycle = found
                    cur.execute("SELECT removed_at FROM career_discovery_source_vacancy_state WHERE source_key=%s AND vacancy_id=%s", (source_key, vacancy_id))
                    previous_presence = cur.fetchone()
                    was_removed = bool(previous_presence and previous_presence[0])
                    if vacancy_id not in seen_vacancy_ids:
                        unique += 1
                    seen_vacancy_ids.add(vacancy_id)
                    previous_source_hash = None
                    if source_job_id:
                        cur.execute("""SELECT o.content_sha256
                            FROM career_discovery_observations o
                            LEFT JOIN career_discovery_runs prior_run ON prior_run.id=o.run_id
                            WHERE o.source_key=%s AND o.source_job_id=%s
                              AND prior_run.run_group_id IS DISTINCT FROM %s::uuid
                            ORDER BY o.observed_at DESC LIMIT 1""",
                            (source_key, source_job_id, run_group_id))
                        previous = cur.fetchone()
                        previous_source_hash = previous[0] if previous else None
                    event = "reappeared" if was_removed else change_event(previous_source_hash, digest, lifecycle)
                    prior_updated_at = None
                    if source_job_id:
                        cur.execute("""SELECT o.source_updated_at FROM career_discovery_observations o
                            JOIN career_discovery_runs prior_run ON prior_run.id=o.run_id
                            WHERE o.source_key=%s AND o.source_job_id=%s AND o.source_updated_at IS NOT NULL
                              AND prior_run.run_group_id IS DISTINCT FROM %s::uuid
                            ORDER BY o.observed_at DESC LIMIT 1""", (source_key, source_job_id, run_group_id))
                        prior_time = cur.fetchone()
                        prior_updated_at = prior_time[0] if prior_time else None
                    current_updated_at = parse_source_time(record.get("source_updated_at"))
                    if (record.get("source_name") == "bundesagentur_fuer_arbeit"
                            and prior_updated_at and current_updated_at):
                        event = ("reappeared" if was_removed else
                                 "changed" if current_updated_at > prior_updated_at else None)
                    cur.execute("""UPDATE career_discovery_vacancies v SET company_name=%s,title=%s,
                        location_text=%s,locations=(SELECT COALESCE(jsonb_agg(DISTINCT place ORDER BY place),'[]'::jsonb)
                            FROM jsonb_array_elements_text(COALESCE(v.locations,'[]'::jsonb)||%s::jsonb) AS x(place)),
                        vacancy_type=%s,
                        canonical_url=%s,content_sha256=%s,last_seen_at=NOW(),
                        publication_at=COALESCE(%s,publication_at),
                        source_updated_at=COALESCE(%s,source_updated_at),
                        lifecycle_status='active',removal_confirmed_at=NULL WHERE id=%s""",
                        (record.get("company_name") or "", record.get("title") or "",
                         record.get("location") or "", json.dumps(record.get("locations") or ([record.get("location")] if record.get("location") else [])),
                         record.get("vacancy_type") or "actual_vacancy", record.get("source_url"), digest,
                         parse_source_time(record.get("publication_date")),
                         parse_source_time(record.get("source_updated_at")), vacancy_id))
                    if event:
                        cur.execute("""INSERT INTO career_discovery_events
                            (vacancy_id,run_id,run_group_id,event_type,previous_content_sha256,
                             current_content_sha256) VALUES (%s,%s,%s::uuid,%s,%s,%s)
                            ON CONFLICT (vacancy_id,run_group_id,event_type)
                            WHERE run_group_id IS NOT NULL DO NOTHING""",
                            (vacancy_id, run_id, run_group_id, event, previous_source_hash, digest))
                else:
                    cur.execute("""INSERT INTO career_discovery_vacancies
                        (canonical_key,company_name,title,location_text,canonical_url,content_sha256,
                         publication_at,source_updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        ("source:" + source_identity, record.get("company_name") or "", record.get("title") or "",
                         record.get("location") or "", record.get("source_url"), digest,
                         parse_source_time(record.get("publication_date")),
                         parse_source_time(record.get("source_updated_at"))))
                    vacancy_id = cur.fetchone()[0]
                    if vacancy_id not in seen_vacancy_ids:
                        unique += 1
                    seen_vacancy_ids.add(vacancy_id)
                    if canonical_key:
                        cur.execute("INSERT INTO career_discovery_vacancy_aliases (alias_key,vacancy_id,alias_type) VALUES (%s,%s,'canonical_url') ON CONFLICT (alias_key) DO NOTHING", (canonical_key, vacancy_id))
                    if alias:
                        cur.execute("""INSERT INTO career_discovery_vacancy_aliases
                            (alias_key,vacancy_id,alias_type) VALUES (%s,%s,'company_title_location')
                            ON CONFLICT (alias_key) DO NOTHING""", (alias, vacancy_id))
                    cur.execute("""UPDATE career_discovery_vacancies SET locations=%s::jsonb,
                        vacancy_type=%s WHERE id=%s""", (json.dumps(record.get("locations") or
                        ([record.get("location")] if record.get("location") else [])),
                        record.get("vacancy_type") or "actual_vacancy", vacancy_id))
                    cur.execute("""INSERT INTO career_discovery_events
                        (vacancy_id,run_id,run_group_id,event_type,current_content_sha256)
                        VALUES (%s,%s,%s::uuid,'new',%s)
                        ON CONFLICT (vacancy_id,run_group_id,event_type)
                        WHERE run_group_id IS NOT NULL DO NOTHING""", (vacancy_id, run_id, run_group_id, digest))
                if source_job_id:
                    cur.execute("""INSERT INTO career_discovery_source_identities
                        (source_key,source_job_id,vacancy_id)
                        VALUES (%s,%s,%s) ON CONFLICT (source_key,source_job_id)
                        DO UPDATE SET vacancy_id=EXCLUDED.vacancy_id""",
                        (source_key, source_job_id, vacancy_id))
                cur.execute("""INSERT INTO career_discovery_source_vacancy_state
                    (source_key,vacancy_id,last_seen_at,consecutive_complete_absences,removed_at)
                    VALUES (%s,%s,NOW(),0,NULL) ON CONFLICT(source_key,vacancy_id)
                    DO UPDATE SET last_seen_at=NOW(),consecutive_complete_absences=0,
                    removed_at=NULL""", (source_key, vacancy_id))
                cur.execute("""INSERT INTO career_discovery_observations
                    (vacancy_id,source_id,run_id,source_key,source_job_id,source_url,
                     query_text,geographic_scope,source_published_at,source_updated_at,
                     content_sha256,raw_payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (vacancy_id, source_id, run_id, source_key,
                     str(record.get("external_job_id") or ""), record.get("source_url"),
                     telemetry.get("query_text"), telemetry.get("geographic_scope"),
                     parse_source_time(record.get("publication_date")),
                     parse_source_time(record.get("source_updated_at")), digest,
                     json.dumps(record.get("raw") or {}, default=str)))
            # Cross-source duplicates are records matched to a vacancy already
            # observed by a different source; same-source repeat queries are excluded.
            cur.execute("""SELECT COUNT(*) FROM career_discovery_observations o
                JOIN career_discovery_observations prior ON prior.vacancy_id=o.vacancy_id
                    AND prior.source_key<>o.source_key AND prior.observed_at<o.observed_at
                WHERE o.run_id=%s""", (run_id,))
            duplicates = cur.fetchone()[0]
            cur.execute("UPDATE career_discovery_runs SET unique_vacancies=%s,cross_source_duplicates=%s WHERE id=%s", (unique, duplicates, run_id))
            if snapshot_complete and status == "succeeded":
                cur.execute("""UPDATE career_discovery_source_vacancy_state
                    SET consecutive_complete_absences=consecutive_complete_absences+1,
                        removed_at=CASE WHEN consecutive_complete_absences+1 >= 2 THEN NOW() ELSE removed_at END
                    WHERE source_key=%s AND last_seen_at <
                        (SELECT started_at FROM career_discovery_runs WHERE id=%s)
                      AND removed_at IS NULL
                    RETURNING vacancy_id,consecutive_complete_absences,removed_at""",
                    (source_key, run_id))
                for vacancy_id, missing_count, removed_at in cur.fetchall():
                    if missing_count != 2 or removed_at is None:
                        continue
                    cur.execute("""INSERT INTO career_discovery_events
                        (vacancy_id,run_id,run_group_id,event_type,details)
                        VALUES (%s,%s,%s::uuid,'removed',%s::jsonb)
                        ON CONFLICT (vacancy_id,run_group_id,event_type)
                        WHERE run_group_id IS NOT NULL DO NOTHING""",
                        (vacancy_id, run_id, run_group_id, json.dumps({"source_key": source_key,
                            "confirmation": "two_complete_snapshots"})))
                    cur.execute("SELECT COUNT(*) FROM career_discovery_source_vacancy_state WHERE vacancy_id=%s AND removed_at IS NULL", (vacancy_id,))
                    if cur.fetchone()[0] == 0:
                        cur.execute("UPDATE career_discovery_vacancies SET lifecycle_status='removed',removal_confirmed_at=NOW() WHERE id=%s", (vacancy_id,))
    return {"run_id": run_id, "unique_vacancies": unique, "duplicates": duplicates}


def finalize_run_group(conn: Any, run_group_id: str) -> None:
    """Set aggregate source health after all queries in this run group finish."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""UPDATE career_discovery_sources s SET health_status =
                CASE WHEN x.failed=0 AND x.partial=0 THEN 'healthy'
                     WHEN x.succeeded>0 OR x.partial>0 THEN 'partial' ELSE 'failed' END,
                updated_at=NOW()
                FROM (SELECT source_key,
                    COUNT(*) FILTER (WHERE status='failed') AS failed,
                    COUNT(*) FILTER (WHERE status='partial') AS partial,
                    COUNT(*) FILTER (WHERE status='succeeded') AS succeeded
                    FROM career_discovery_runs WHERE run_group_id=%s
                    GROUP BY source_key) x
                WHERE s.source_key=x.source_key""", (run_group_id,))


def load_monitoring_summary(conn: Any) -> dict[str, Any]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("""SELECT s.source_key,s.employer_name,s.provider,s.board_id,
            s.geographic_scope,s.configured,s.authorized,s.active,s.access_status,
            s.health_status,s.last_retrieval_at,s.last_success_at,
            COALESCE(g.queries_attempted,0),COALESCE(g.pages_requested,0),
            COALESCE(g.pages_retrieved,0),COALESCE(g.raw_results,0),
            COALESCE(m.unique_vacancies,0),COALESCE(m.cross_source_duplicates,0),
            COALESCE(g.parse_failures,0),COALESCE(g.retrieval_errors,'[]'::jsonb)
            FROM career_discovery_sources s LEFT JOIN LATERAL
            (SELECT * FROM career_discovery_runs x WHERE x.source_key=s.source_key
             ORDER BY started_at DESC LIMIT 1) r ON TRUE
            LEFT JOIN LATERAL (SELECT SUM(x.queries_attempted) AS queries_attempted,
             SUM(x.pages_requested) AS pages_requested,SUM(x.pages_retrieved) AS pages_retrieved,
             SUM(x.raw_results) AS raw_results,
             SUM(x.parse_failures) AS parse_failures,
             jsonb_agg(x.retrieval_errors) FILTER (WHERE x.retrieval_errors <> '[]'::jsonb) AS retrieval_errors
             FROM career_discovery_runs x WHERE x.run_group_id=r.run_group_id
                AND x.source_key=s.source_key) g ON TRUE
            LEFT JOIN LATERAL (SELECT COUNT(DISTINCT COALESCE(i.vacancy_id,o.vacancy_id))
                FILTER (WHERE v.vacancy_type='actual_vacancy') AS unique_vacancies,
             COUNT(DISTINCT COALESCE(i.vacancy_id,o.vacancy_id)) FILTER (WHERE EXISTS (
                SELECT 1 FROM career_discovery_observations other
                LEFT JOIN career_discovery_source_identities oi
                  ON oi.source_key=other.source_key AND oi.source_job_id=other.source_job_id
                WHERE COALESCE(oi.vacancy_id,other.vacancy_id)=COALESCE(i.vacancy_id,o.vacancy_id)
                  AND other.source_key<>s.source_key
             )) AS cross_source_duplicates
             FROM career_discovery_runs x JOIN career_discovery_observations o ON o.run_id=x.id
             LEFT JOIN career_discovery_source_identities i
               ON i.source_key=o.source_key AND i.source_job_id=o.source_job_id
             JOIN career_discovery_vacancies v ON v.id=COALESCE(i.vacancy_id,o.vacancy_id)
             WHERE x.run_group_id=r.run_group_id AND x.source_key=s.source_key) m ON TRUE
             ORDER BY s.provider,s.employer_name""")
        fields = ["source_key","employer_name","provider","board_id","geographic_scope",
                  "configured","authorized","active","access_status","health_status",
                  "last_retrieval_at","last_success_at","queries_attempted","pages_requested","pages_retrieved",
                  "raw_results","unique_vacancies","cross_source_duplicates","parse_failures",
                  "retrieval_errors"]
        sources = [dict(zip(fields, row)) for row in cur.fetchall()]
        cur.execute("""SELECT e.event_type,v.company_name,v.title,
            COALESCE(o.source_key,e.details->>'source_key') AS source_key,
            v.publication_at,v.source_updated_at,v.first_seen_at,v.last_seen_at,
            e.occurred_at FROM career_discovery_events e
            JOIN career_discovery_vacancies v ON v.id=e.vacancy_id
            LEFT JOIN career_discovery_observations o ON o.run_id=e.run_id
                AND o.vacancy_id=e.vacancy_id
            JOIN career_discovery_runs r ON r.id=e.run_id
            WHERE r.run_group_id=(SELECT run_group_id FROM career_discovery_runs
                ORDER BY started_at DESC LIMIT 1)
            ORDER BY e.occurred_at DESC,e.id DESC LIMIT 50""")
        event_fields = ["event_type","company_name","title","source_key","publication_at",
                        "source_updated_at","first_seen_at","last_seen_at","occurred_at"]
        events = [dict(zip(event_fields, row)) for row in cur.fetchall()]
        cur.execute("""SELECT r.source_key,r.query_text,r.geographic_scope,r.status,
            r.queries_attempted,r.pages_requested,r.pages_retrieved,r.raw_results,
            r.unique_vacancies,r.cross_source_duplicates,r.parse_failures,
            r.snapshot_complete,r.started_at,r.completed_at,r.retrieval_errors
            FROM career_discovery_runs r ORDER BY r.started_at DESC,r.id DESC LIMIT 50""")
        history_fields = ["source_key","query_text","geographic_scope","status",
            "queries_attempted","pages_requested","pages_retrieved","raw_results",
            "unique_vacancies","cross_source_duplicates","parse_failures","snapshot_complete","started_at",
            "completed_at","retrieval_errors"]
        history = [dict(zip(history_fields, row)) for row in cur.fetchall()]
        cur.execute("""SELECT v.id,v.locations,v.location_text
            FROM career_discovery_vacancies v
            WHERE v.vacancy_type='actual_vacancy' AND v.lifecycle_status<>'removed'""")
        geo_rows = cur.fetchall()
        cur.execute("""SELECT DISTINCT v.company_name,v.title,v.vacancy_type,
            COALESCE(i.source_key,o.source_key) AS source_key,
            COALESCE(i.source_job_id,o.source_job_id) AS source_job_id,
            COALESCE(o.source_url,v.canonical_url) AS source_url
            FROM career_discovery_vacancies v
            LEFT JOIN career_discovery_source_identities i ON i.vacancy_id=v.id
            LEFT JOIN career_discovery_observations o ON o.vacancy_id=v.id
            WHERE v.vacancy_type<>'actual_vacancy'
            ORDER BY v.company_name,v.title""")
        board_entries = [dict(zip(("company_name","title","vacancy_type","source_key",
            "source_job_id","source_url"), row)) for row in cur.fetchall()]
    def category(text: str) -> str:
        value = text.casefold()
        if any(term in value for term in ("berlin", "germany", "deutschland", "hamburg", "munich", "münchen", "frankfurt", "stuttgart", "cologne", "köln", "düsseldorf", "dortmund", "planegg", "dornstadt", "schönefeld")):
            return "Germany"
        if any(term in value for term in ("united states", "usa", "u.s.", "california", "mountain view", "san francisco", "new york", "seattle", "texas", "washington")):
            return "US"
        if any(term in value for term in ("united kingdom", "uk", "london", "france", "paris", "netherlands", "amsterdam", "sweden", "stockholm", "switzerland", "zurich", "zürich", "austria", "vienna", "denmark", "copenhagen", "belgium", "brussels", "spain", "madrid", "italy", "milan", "poland", "warsaw", "finland", "norway", "ireland", "portugal")):
            return "Other Europe"
        if any(term in value for term in ("japan", "fukuoka", "singapore", "canada", "india", "taiwan", "australia", "china")):
            return "Other international"
        return "Unknown location"
    counts = {name: {"vacancy_count": 0, "location_count": 0} for name in
              ("Germany", "Other Europe", "US", "Other international", "Unknown location")}
    berlin_ids: set[int] = set()
    all_locations = 0
    for vacancy_id, locations, fallback in geo_rows:
        texts = locations if isinstance(locations, list) else []
        texts = list(dict.fromkeys(str(item) for item in texts if item))
        if not texts and fallback:
            texts = [str(fallback)]
        all_locations += len(texts)
        buckets = {category(text) for text in texts} or {"Unknown location"}
        for bucket in buckets:
            counts[bucket]["vacancy_count"] += 1
        for text in texts:
            counts[category(text)]["location_count"] += 1
            if "berlin" in text.casefold():
                berlin_ids.add(vacancy_id)
    counts["Germany"]["berlin_vacancy_count"] = len(berlin_ids)
    geographic = {"overall_vacancy_count": len(geo_rows), "location_count": all_locations,
                  "categories": counts,
                  "note": "Vacancy counts by region can overlap when one vacancy lists multiple regional locations; overall counts are distinct. Berlin is included in Germany."}
    result = {"sources": sources, "events": events, "history": history,
            "last_run_at": max((run["completed_at"] for run in history
                                if run["completed_at"]), default=None),
            "http_requests": None,
            "geographic_distribution": geographic,
            "employer_board_entries": board_entries}
    return json.loads(json.dumps(result, default=lambda value:
                                 value.isoformat() if hasattr(value, "isoformat") else str(value)))
