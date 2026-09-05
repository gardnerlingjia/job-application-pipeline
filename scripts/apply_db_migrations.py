from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import get_database_config  # noqa: E402


DEFAULT_MIGRATIONS_DIR = Path("db/migrations")
MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")
TRACKING_MIGRATION_KEY = "054_create_schema_migrations.sql"
GREENHOUSE_STRIPE_REPAIR_MIGRATION_KEY = "018_replace_greenhouse_wildcard_search_terms.sql"
FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY = (
    "026_create_false_negative_intelligence_foundation.sql"
)
ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY = (
    "066_harden_origin_pattern_promotion_taxonomy.sql"
)
ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY = (
    "070_repair_origin_observed_pattern_candidate_taxonomy_columns.sql"
)
PRODUCT_V1_POLICY_MIGRATION_KEY = "078_activate_product_v1_operator_policy.sql"
COMPATIBLE_HISTORICAL_CHECKSUMS = {
    FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY: {
        # Original 026 used timestamptz::date in an index expression. Existing
        # databases that successfully tracked that historical file remain valid,
        # while fresh installs use the immutable UTC date expression now in git.
        "b864d49394e8a4f1b58b72a032f85fa02b8250cb9794d2052b0609b00b2b105b",
        # Temporary local V2.3 fresh-init repair checksum. Migration 108 repairs
        # the index back to date-level uniqueness without rerunning 026.
        "df35b6c84908b2ee374a42a863e12dc382a84b10ce4930db769bb43f9560062e",
    },
    ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY: {
        # Temporary local V2.3 fresh-init repair checksum that added a DROP VIEW.
        # The committed runner now applies that drop as an execution precondition.
        "a4b3e30667dd3793d9b66bcb76c61f3eb1361e30c8ee994780c78be247e1953e",
    },
    ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY: {
        # Temporary local V2.3 fresh-init repair checksum that added a DROP VIEW.
        # The committed runner now applies that drop as an execution precondition.
        "1b1d869f91110c6a21d3151f512dc9adcad5802374e9d754e100b03cb288c3c5",
    },
}
PRODUCT_V1_VIEW_RESET_SQL = """
DROP VIEW IF EXISTS gold_product_v1_application_readiness;
DROP VIEW IF EXISTS gold_product_v1_top_jobs;
DROP VIEW IF EXISTS gold_product_v1_job_readiness;
"""
ORIGIN_PROMOTED_PATTERN_VIEW_RESET_SQL = """
DROP VIEW IF EXISTS gold_origin_promoted_observation_patterns;
"""


@dataclass(frozen=True)
class MigrationFile:
    migration_key: str
    version_number: int
    filename: str
    path: Path
    checksum_sha256: str


@dataclass(frozen=True)
class TrackedMigration:
    migration_key: str
    version_number: int
    filename: str
    checksum_sha256: str
    execution_status: str
    execution_mode: str
    applied_by: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_migration_file(path: Path) -> MigrationFile | None:
    match = MIGRATION_RE.match(path.name)
    if not match:
        return None

    return MigrationFile(
        migration_key=path.name,
        version_number=int(match.group(1)),
        filename=path.name,
        path=path,
        checksum_sha256=sha256_file(path),
    )


def discover_migration_files(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[MigrationFile]:
    migrations: list[MigrationFile] = []

    for path in migrations_dir.glob("*.sql"):
        parsed = parse_migration_file(path)
        if parsed is not None:
            migrations.append(parsed)

    return sorted(migrations, key=lambda item: (item.version_number, item.filename))


def connect(*, autocommit: bool = False) -> psycopg.Connection[Any]:
    return psycopg.connect(
        **get_database_config(),
        row_factory=dict_row,
        autocommit=autocommit,
    )


def schema_migrations_exists(conn: psycopg.Connection[Any]) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'schema_migrations'
            ) AS exists;
            """
        )
        row = cur.fetchone()

    return bool(row and row["exists"])


def load_tracked_migrations(conn: psycopg.Connection[Any]) -> dict[str, TrackedMigration]:
    if not schema_migrations_exists(conn):
        return {}

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                migration_key,
                version_number,
                filename,
                checksum_sha256,
                execution_status,
                execution_mode,
                applied_by
            FROM schema_migrations
            ORDER BY version_number, filename;
            """
        )
        rows = cur.fetchall()

    return {
        row["migration_key"]: TrackedMigration(
            migration_key=row["migration_key"],
            version_number=int(row["version_number"]),
            filename=row["filename"],
            checksum_sha256=row["checksum_sha256"],
            execution_status=row["execution_status"],
            execution_mode=row["execution_mode"],
            applied_by=row["applied_by"],
        )
        for row in rows
    }


def checksum_mismatches(
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
) -> list[tuple[MigrationFile, TrackedMigration]]:
    mismatches: list[tuple[MigrationFile, TrackedMigration]] = []

    for migration in migrations:
        existing = tracked.get(migration.migration_key)
        if (
            existing
            and existing.execution_status != "failed"
            and existing.checksum_sha256 != migration.checksum_sha256
            and existing.checksum_sha256
            not in COMPATIBLE_HISTORICAL_CHECKSUMS.get(migration.migration_key, set())
        ):
            mismatches.append((migration, existing))

    return mismatches


def pending_migrations(
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
) -> list[MigrationFile]:
    return [
        migration
        for migration in migrations
        if migration.migration_key not in tracked
        or tracked[migration.migration_key].execution_status == "failed"
    ]


def select_exact_pending_migration(
    *,
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
    migration_key: str,
    require_sole_pending: bool,
) -> tuple[MigrationFile, str]:
    matches = [migration for migration in migrations if migration.migration_key == migration_key]
    if len(matches) != 1:
        raise ValueError(f"Exact migration key must resolve once: {migration_key}")

    target = matches[0]
    if migration_key in tracked:
        return target, "already_applied"

    pending = pending_migrations(migrations, tracked)
    pending_keys = [migration.migration_key for migration in pending]
    if require_sole_pending and pending_keys != [migration_key]:
        raise RuntimeError(
            "Exact migration requires sole pending target; "
            f"target={migration_key} pending={pending_keys}"
        )
    if migration_key not in pending_keys:
        raise RuntimeError(f"Exact migration is not pending: {migration_key}")

    return target, "pending"


def insert_tracking_row(
    conn: psycopg.Connection[Any],
    migration: MigrationFile,
    *,
    execution_status: str,
    execution_mode: str,
    applied_by: str,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO schema_migrations (
                migration_key,
                version_number,
                filename,
                checksum_sha256,
                execution_status,
                execution_mode,
                applied_by,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (migration_key)
            DO UPDATE SET
                checksum_sha256 = EXCLUDED.checksum_sha256,
                execution_status = EXCLUDED.execution_status,
                execution_mode = EXCLUDED.execution_mode,
                applied_by = EXCLUDED.applied_by,
                error_message = EXCLUDED.error_message,
                applied_at = NOW(),
                updated_at = NOW();
            """,
            (
                migration.migration_key,
                migration.version_number,
                migration.filename,
                migration.checksum_sha256,
                execution_status,
                execution_mode,
                applied_by,
                error_message,
            ),
        )


def print_status(
    *,
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
    table_exists: bool,
) -> None:
    mismatches = checksum_mismatches(migrations, tracked)
    pending = pending_migrations(migrations, tracked)

    print("S7Y DB Migration Tracking Status")
    print(f"tracking_table_exists: {str(table_exists).lower()}")
    print(f"migration_files: {len(migrations)}")
    print(f"tracked_migrations: {len(tracked)}")
    print(f"pending_migrations: {len(pending)}")
    print(f"checksum_mismatches: {len(mismatches)}")

    if not table_exists:
        print("next: run --apply to execute the schema_migrations bootstrap migration first")
        return

    if mismatches:
        print("---")
        print("Checksum mismatches:")
        for migration, existing in mismatches:
            print(
                f"- {migration.filename}: tracked={existing.checksum_sha256} "
                f"current={migration.checksum_sha256}"
            )

    if pending:
        print("---")
        print("Pending migrations:")
        for migration in pending[:25]:
            print(f"- {migration.filename}")
        if len(pending) > 25:
            print(f"- ... {len(pending) - 25} more")


def ensure_no_checksum_mismatches(
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
) -> None:
    mismatches = checksum_mismatches(migrations, tracked)
    if mismatches:
        details = ", ".join(migration.filename for migration, _ in mismatches)
        raise ValueError(f"Checksum mismatch for tracked migration(s): {details}")


def bootstrap_existing(
    *,
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
    applied_by: str,
) -> int:
    ensure_no_checksum_mismatches(migrations, tracked)

    inserted = 0
    with connect() as conn:
        if not schema_migrations_exists(conn):
            raise RuntimeError("schema_migrations table does not exist. Apply the tracking migration first.")

        with conn.transaction():
            current = load_tracked_migrations(conn)
            for migration in migrations:
                if migration.migration_key in current:
                    continue

                insert_tracking_row(
                    conn,
                    migration,
                    execution_status="bootstrapped",
                    execution_mode="manual_bootstrap",
                    applied_by=applied_by,
                )
                inserted += 1

    return inserted


def _tracking_migration(migrations: list[MigrationFile]) -> MigrationFile:
    matches = [
        migration
        for migration in migrations
        if migration.migration_key == TRACKING_MIGRATION_KEY
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Tracking migration must resolve once: {TRACKING_MIGRATION_KEY}"
        )
    return matches[0]


def bootstrap_schema_migrations_if_needed(
    *,
    migrations: list[MigrationFile],
    applied_by: str,
) -> bool:
    tracking = _tracking_migration(migrations)
    with connect() as conn:
        if schema_migrations_exists(conn):
            return False

        sql = tracking.path.read_text(encoding="utf-8")
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql)
            insert_tracking_row(
                conn,
                tracking,
                execution_status="success",
                execution_mode="script_apply",
                applied_by=applied_by,
            )

    print(f"applied: {tracking.filename}")
    return True


def prepare_historical_migration_dependencies(
    conn: psycopg.Connection[Any],
    migration: MigrationFile,
) -> None:
    """Recreate historical pre-tracking seed state needed by old repair migrations."""

    if migration.migration_key == PRODUCT_V1_POLICY_MIGRATION_KEY:
        with conn.cursor() as cur:
            cur.execute(PRODUCT_V1_VIEW_RESET_SQL)
        return

    if migration.migration_key in {
        ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY,
        ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY,
    }:
        with conn.cursor() as cur:
            cur.execute(ORIGIN_PROMOTED_PATTERN_VIEW_RESET_SQL)
        return

    if migration.migration_key == GREENHOUSE_STRIPE_REPAIR_MIGRATION_KEY:
        with conn.cursor() as cur:
            cur.execute(
                """
            INSERT INTO search_profiles (
                profile_name,
                source_name,
                search_term,
                search_location,
                search_radius_km,
                offer_type,
                page_size,
                is_active
            )
            VALUES (
                'greenhouse_stripe',
                'greenhouse:stripe',
                NULL,
                'global',
                0,
                NULL,
                100,
                TRUE
            )
            ON CONFLICT (profile_name) DO NOTHING;
            """
            )


def execute_migration_sql(migration: MigrationFile) -> None:
    sql = migration.path.read_text(encoding="utf-8")

    with connect(autocommit=True) as conn:
        if not schema_migrations_exists(conn):
            raise RuntimeError("schema_migrations table does not exist. Apply the tracking migration first.")

        prepare_historical_migration_dependencies(conn, migration)
        with conn.cursor() as cur:
            cur.execute(sql)


def record_migration_success(
    migration: MigrationFile,
    *,
    execution_mode: str,
    applied_by: str,
) -> None:
    with connect() as conn:
        if not schema_migrations_exists(conn):
            raise RuntimeError("schema_migrations table does not exist. Apply the tracking migration first.")

        with conn.transaction():
            insert_tracking_row(
                conn,
                migration,
                execution_status="success",
                execution_mode=execution_mode,
                applied_by=applied_by,
            )


def apply_pending(
    *,
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
    applied_by: str,
) -> int:
    ensure_no_checksum_mismatches(migrations, tracked)
    bootstrap_applied = bootstrap_schema_migrations_if_needed(
        migrations=migrations,
        applied_by=applied_by,
    )
    if bootstrap_applied:
        with connect() as conn:
            tracked = load_tracked_migrations(conn)
        ensure_no_checksum_mismatches(migrations, tracked)

    pending = pending_migrations(migrations, tracked)
    applied = 1 if bootstrap_applied else 0

    for migration in pending:
        try:
            execute_migration_sql(migration)
            record_migration_success(
                migration,
                execution_mode="script_apply",
                applied_by=applied_by,
            )
            applied += 1
            print(f"applied: {migration.filename}")
        except Exception as exc:
            with connect() as conn:
                if schema_migrations_exists(conn):
                    with conn.transaction():
                        insert_tracking_row(
                            conn,
                            migration,
                            execution_status="failed",
                            execution_mode="script_apply",
                            applied_by=applied_by,
                            error_message=str(exc),
                        )

            raise

    return applied


def apply_exact_migration(
    *,
    migrations: list[MigrationFile],
    tracked: dict[str, TrackedMigration],
    migration_key: str,
    applied_by: str,
    require_sole_pending: bool,
) -> str:
    ensure_no_checksum_mismatches(migrations, tracked)
    target, state = select_exact_pending_migration(
        migrations=migrations,
        tracked=tracked,
        migration_key=migration_key,
        require_sole_pending=require_sole_pending,
    )
    if state == "already_applied":
        return state

    with connect() as conn:
        if not schema_migrations_exists(conn):
            raise RuntimeError("schema_migrations table does not exist. Apply the tracking migration first.")

        current = load_tracked_migrations(conn)
        ensure_no_checksum_mismatches(migrations, current)
        target, state = select_exact_pending_migration(
            migrations=migrations,
            tracked=current,
            migration_key=migration_key,
            require_sole_pending=require_sole_pending,
        )
        if state == "already_applied":
            return state

    execute_migration_sql(target)
    record_migration_success(
        target,
        execution_mode="script_apply_exact",
        applied_by=applied_by,
    )

    return "applied"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track and apply DB migrations with checksum validation.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--bootstrap-existing", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--apply-exact", metavar="MIGRATION_KEY")
    parser.add_argument("--require-sole-pending", action="store_true")
    parser.add_argument("--applied-by", default="local")
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    migrations = discover_migration_files(args.migrations_dir)

    with connect() as conn:
        table_exists = schema_migrations_exists(conn)
        tracked = load_tracked_migrations(conn)

    if args.status:
        print_status(migrations=migrations, tracked=tracked, table_exists=table_exists)
        return

    if args.bootstrap_existing:
        inserted = bootstrap_existing(
            migrations=migrations,
            tracked=tracked,
            applied_by=args.applied_by,
        )
        print(f"bootstrapped_migrations: {inserted}")
        return

    if args.apply:
        applied = apply_pending(
            migrations=migrations,
            tracked=tracked,
            applied_by=args.applied_by,
        )
        print(f"applied_migrations: {applied}")
        return

    if args.apply_exact:
        exact_status = apply_exact_migration(
            migrations=migrations,
            tracked=tracked,
            migration_key=args.apply_exact,
            applied_by=args.applied_by,
            require_sole_pending=args.require_sole_pending,
        )
        print(f"exact_migration: {args.apply_exact}")
        print(f"exact_migration_status: {exact_status}")


if __name__ == "__main__":
    main()
