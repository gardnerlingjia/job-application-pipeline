"""Explicit, reviewed synchronization of existing discovery search terms only.

No profile/source creation or activation. All differences are treated as potentially
user-customized: applying requires the exact digest of a freshly reviewed plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from psycopg.rows import dict_row

from src.career_intelligence.market_discovery import load_market_discovery_config
from src.career_intelligence.moia_live_source import connect_database


def desired_profiles(config):
    return {
        f"{source.profile_prefix}_{profile.key}": {
            "source_name": source.source_name,
            "terms": sorted(set(profile.search_terms)),
        }
        for source in config.active_sources
        for profile in config.profiles
    }


def read_profiles(conn, names):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, profile_name, source_name, search_term, search_location, "
            "search_radius_km, offer_type, page_size, is_active, recurring_ingestion_enabled "
            "FROM search_profiles WHERE profile_name = ANY(%s) ORDER BY profile_name",
            (list(names),),
        )
        rows = cur.fetchall()
        for row in rows:
            cur.execute(
                "SELECT search_term, is_active FROM search_terms "
                "WHERE search_profile_id = %s ORDER BY search_term", (row["id"],),
            )
            row["terms"] = cur.fetchall()
    return rows


def matches_original_seed(name, row):
    seed = json.loads(Path("config/career_discovery_profile_seed.v1.json").read_text())
    baseline = seed["profiles"].get(name)
    return bool(baseline) and all(row.get(key) == value for key, value in baseline.items())


def build_plan(config, rows):
    desired = desired_profiles(config)
    current = {row["profile_name"]: row for row in rows}
    differences, blockers = [], []
    for name, target in desired.items():
        row = current.get(name)
        if row is None:
            blockers.append(f"{name}: missing; creation is outside synchronization scope")
            continue
        if row["source_name"] != target["source_name"] or row["search_term"]:
            blockers.append(f"{name}: source mismatch or legacy search_term; manual review required")
        active = sorted(t["search_term"] for t in row["terms"] if t["is_active"])
        if active != target["terms"]:
            differences.append({
                "profile_name": name, "before": active, "after": target["terms"],
                "add": sorted(set(target["terms"]) - set(active)),
                "deactivate": sorted(set(active) - set(target["terms"])),
                "customization_status": "matches_migration_109_seed" if matches_original_seed(name, row)
                else "customized_or_untracked; explicit approval required",
            })
    payload = {"schema_version": 1, "desired": desired, "current": rows,
               "differences": differences, "blockers": blockers}
    payload["approval_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def apply_plan(conn, config, approval_digest, *, seed_only=False):
    # Serialize term/profile changes, including concurrent inserts, before re-reading.
    # No external calls or user interaction occur while these short-lived locks are held.
    with conn.transaction():
        conn.execute("LOCK TABLE search_profiles, search_terms IN SHARE ROW EXCLUSIVE MODE")
        plan = build_plan(config, read_profiles(conn, desired_profiles(config)))
        if plan["blockers"] or approval_digest != plan["approval_digest"]:
            raise ValueError("Plan blocked or changed; regenerate and review the complete diff")
        if seed_only and any(change["customization_status"] != "matches_migration_109_seed"
                             for change in plan["differences"]):
            raise ValueError("Customized profiles require separate review and approval")
        ids = {row["profile_name"]: row["id"] for row in plan["current"]}
        for change in plan["differences"]:
            profile_id = ids[change["profile_name"]]
            conn.execute(
                "UPDATE search_terms SET is_active = FALSE WHERE search_profile_id = %s "
                "AND NOT (search_term = ANY(%s)) AND is_active = TRUE",
                (profile_id, change["after"]),
            )
            for term in change["after"]:
                conn.execute(
                    "INSERT INTO search_terms (search_profile_id, search_term, is_active) "
                    "VALUES (%s, %s, TRUE) ON CONFLICT (search_profile_id, search_term) "
                    "DO UPDATE SET is_active = TRUE WHERE search_terms.is_active = FALSE",
                    (profile_id, term),
                )
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve", metavar="SHA256", help="Apply the exact reviewed plan")
    parser.add_argument("--seed-only", action="store_true",
                        help="Refuse any changes to profiles not identical to migration 109")
    args = parser.parse_args()
    config = load_market_discovery_config()
    with connect_database() as conn:
        if args.approve:
            plan = apply_plan(conn, config, args.approve, seed_only=args.seed_only)
        else:
            conn.execute("SET TRANSACTION READ ONLY")
            plan = build_plan(config, read_profiles(conn, desired_profiles(config)))
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 1 if plan["blockers"] else 0




def assert_profile_intent(repository, profile):
    """Guard the generic ingestion entry point too, before connector construction."""
    if not profile.profile_name.startswith(("lingjia_market_stepstone_", "lingjia_market_ba_")):
        return
    target = desired_profiles(load_market_discovery_config()).get(profile.profile_name)
    actual = sorted({term.search_term for _, term in
                     repository.load_active_search_terms(profile.profile_name)})
    if (target is None or profile.source_name != target["source_name"]
            or actual != target["terms"] or profile.search_term):
        raise ValueError("Discovery search intent drift: review discovery_profile_sync before ingestion")


if __name__ == "__main__":
    raise SystemExit(main())
