from pathlib import Path

import pytest

from scripts.apply_db_migrations import (
    FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY,
    ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY,
    ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY,
    MigrationFile,
    TrackedMigration,
    apply_pending,
    build_parser,
    bootstrap_schema_migrations_if_needed,
    checksum_mismatches,
    discover_migration_files,
    parse_migration_file,
    pending_migrations,
    prepare_historical_migration_dependencies,
    select_exact_pending_migration,
)


def test_parse_migration_file_uses_filename_as_key(tmp_path: Path) -> None:
    migration = tmp_path / "004_example.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")

    parsed = parse_migration_file(migration)

    assert parsed is not None
    assert parsed.version_number == 4
    assert parsed.filename == "004_example.sql"
    assert parsed.migration_key == "004_example.sql"
    assert len(parsed.checksum_sha256) == 64


def test_discover_migrations_tolerates_duplicate_version_numbers(tmp_path: Path) -> None:
    (tmp_path / "004_b.sql").write_text("SELECT 2;\n", encoding="utf-8")
    (tmp_path / "004_a.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "005_c.sql").write_text("SELECT 3;\n", encoding="utf-8")

    filenames = [migration.filename for migration in discover_migration_files(tmp_path)]

    assert filenames == ["004_a.sql", "004_b.sql", "005_c.sql"]


def test_pending_migrations_uses_migration_key_not_version_number(tmp_path: Path) -> None:
    first = tmp_path / "004_a.sql"
    second = tmp_path / "004_b.sql"
    first.write_text("SELECT 1;\n", encoding="utf-8")
    second.write_text("SELECT 2;\n", encoding="utf-8")

    migrations = discover_migration_files(tmp_path)
    tracked = {
        migrations[0].migration_key: TrackedMigration(
            migration_key=migrations[0].migration_key,
            version_number=migrations[0].version_number,
            filename=migrations[0].filename,
            checksum_sha256=migrations[0].checksum_sha256,
            execution_status="bootstrapped",
            execution_mode="manual_bootstrap",
            applied_by="test",
        )
    }

    assert [migration.filename for migration in pending_migrations(migrations, tracked)] == ["004_b.sql"]


def test_failed_tracked_migration_remains_pending_for_retry(tmp_path: Path) -> None:
    migration = tmp_path / "018_retry.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")
    parsed = parse_migration_file(migration)
    assert parsed is not None
    tracked = {
        parsed.migration_key: TrackedMigration(
            migration_key=parsed.migration_key,
            version_number=parsed.version_number,
            filename=parsed.filename,
            checksum_sha256="0" * 64,
            execution_status="failed",
            execution_mode="script_apply",
            applied_by="test",
        )
    }

    assert pending_migrations([parsed], tracked) == [parsed]
    assert checksum_mismatches([parsed], tracked) == []


def test_checksum_mismatch_detects_changed_tracked_file(tmp_path: Path) -> None:
    migration = tmp_path / "010_example.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")
    parsed = parse_migration_file(migration)
    assert parsed is not None

    tracked = {
        parsed.migration_key: TrackedMigration(
            migration_key=parsed.migration_key,
            version_number=parsed.version_number,
            filename=parsed.filename,
            checksum_sha256="0" * 64,
            execution_status="bootstrapped",
            execution_mode="manual_bootstrap",
            applied_by="test",
        )
    }

    mismatches = checksum_mismatches([parsed], tracked)

    assert mismatches == [(parsed, tracked[parsed.migration_key])]


def test_legacy_checksum_compatibility_accepts_original_026_checksum() -> None:
    current = _migration(FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY, 26)
    tracked = {
        current.migration_key: TrackedMigration(
            migration_key=current.migration_key,
            version_number=current.version_number,
            filename=current.filename,
            checksum_sha256=(
                "b864d49394e8a4f1b58b72a032f85fa02b8250cb9794d2052b0609b00b2b105b"
            ),
            execution_status="success",
            execution_mode="script_apply",
            applied_by="previous",
        )
    }

    assert checksum_mismatches([current], tracked) == []
    assert pending_migrations([current], tracked) == []


@pytest.mark.parametrize(
    ("migration_key", "compatible_checksum"),
    (
        (
            FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY,
            "df35b6c84908b2ee374a42a863e12dc382a84b10ce4930db769bb43f9560062e",
        ),
        (
            ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY,
            "a4b3e30667dd3793d9b66bcb76c61f3eb1361e30c8ee994780c78be247e1953e",
        ),
        (
            ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY,
            "1b1d869f91110c6a21d3151f512dc9adcad5802374e9d754e100b03cb288c3c5",
        ),
    ),
)
def test_temporary_v23_checksums_are_explicitly_compatible(
    migration_key: str,
    compatible_checksum: str,
) -> None:
    current = _migration(migration_key, int(migration_key[:3]))
    tracked = {
        current.migration_key: TrackedMigration(
            migration_key=current.migration_key,
            version_number=current.version_number,
            filename=current.filename,
            checksum_sha256=compatible_checksum,
            execution_status="success",
            execution_mode="script_apply",
            applied_by="local",
        )
    }

    assert checksum_mismatches([current], tracked) == []
    assert pending_migrations([current], tracked) == []


def test_legacy_checksum_compatibility_remains_narrow() -> None:
    current = _migration("027_other.sql", 27)
    tracked = {
        current.migration_key: TrackedMigration(
            migration_key=current.migration_key,
            version_number=current.version_number,
            filename=current.filename,
            checksum_sha256=(
                "b864d49394e8a4f1b58b72a032f85fa02b8250cb9794d2052b0609b00b2b105b"
            ),
            execution_status="success",
            execution_mode="script_apply",
            applied_by="previous",
        )
    }

    assert checksum_mismatches([current], tracked) == [(current, tracked[current.migration_key])]


def test_exact_migration_selects_only_requested_pending_file(tmp_path: Path) -> None:
    target = tmp_path / "101_target.sql"
    target.write_text("SELECT 101;\n", encoding="utf-8")
    migrations = discover_migration_files(tmp_path)

    selected, state = select_exact_pending_migration(
        migrations=migrations,
        tracked={},
        migration_key="101_target.sql",
        require_sole_pending=True,
    )

    assert selected.filename == "101_target.sql"
    assert state == "pending"


def test_exact_migration_refuses_unresolved_target(tmp_path: Path) -> None:
    (tmp_path / "101_target.sql").write_text("SELECT 101;\n", encoding="utf-8")
    migrations = discover_migration_files(tmp_path)

    with pytest.raises(ValueError, match="must resolve once"):
        select_exact_pending_migration(
            migrations=migrations,
            tracked={},
            migration_key="999_missing.sql",
            require_sole_pending=True,
        )


def test_exact_migration_refuses_additional_pending_files_when_required(tmp_path: Path) -> None:
    (tmp_path / "100_other.sql").write_text("SELECT 100;\n", encoding="utf-8")
    (tmp_path / "101_target.sql").write_text("SELECT 101;\n", encoding="utf-8")
    migrations = discover_migration_files(tmp_path)

    with pytest.raises(RuntimeError, match="sole pending target"):
        select_exact_pending_migration(
            migrations=migrations,
            tracked={},
            migration_key="101_target.sql",
            require_sole_pending=True,
        )


def test_exact_migration_reports_already_applied_without_reselecting_pending(tmp_path: Path) -> None:
    target = tmp_path / "101_target.sql"
    target.write_text("SELECT 101;\n", encoding="utf-8")
    migrations = discover_migration_files(tmp_path)
    parsed = migrations[0]
    tracked = {
        parsed.migration_key: TrackedMigration(
            migration_key=parsed.migration_key,
            version_number=parsed.version_number,
            filename=parsed.filename,
            checksum_sha256=parsed.checksum_sha256,
            execution_status="success",
            execution_mode="script_apply_exact",
            applied_by="test",
        )
    }

    selected, state = select_exact_pending_migration(
        migrations=migrations,
        tracked=tracked,
        migration_key="101_target.sql",
        require_sole_pending=True,
    )

    assert selected.filename == "101_target.sql"
    assert state == "already_applied"


def test_parser_exposes_exact_apply_and_sole_pending_guard() -> None:
    args = build_parser().parse_args(
        [
            "--apply-exact",
            "101_create_job_review_relevance_label_events.sql",
            "--require-sole-pending",
            "--applied-by",
            "ml-pilot-001b",
        ]
    )

    assert args.apply_exact == "101_create_job_review_relevance_label_events.sql"
    assert args.require_sole_pending is True
    assert args.applied_by == "ml-pilot-001b"


def test_script_uses_shared_database_config() -> None:
    text = Path("scripts/apply_db_migrations.py").read_text(encoding="utf-8")

    assert "from src.config import get_database_config" in text
    assert "get_database_config()" in text
    assert "psycopg.connect(" in text
    assert "os.environ[" not in text


def test_script_adds_repo_root_for_direct_invocation() -> None:
    text = Path("scripts/apply_db_migrations.py").read_text(encoding="utf-8")

    assert "REPO_ROOT = Path(__file__).resolve().parents[1]" in text
    assert "sys.path.insert(0, str(REPO_ROOT))" in text


def test_status_on_empty_db_points_to_apply_not_bootstrap_existing(capsys) -> None:
    from scripts.apply_db_migrations import print_status

    print_status(migrations=[], tracked={}, table_exists=False)

    output = capsys.readouterr().out
    assert "tracking_table_exists: false" in output
    assert "run --apply" in output
    assert "bootstrap existing" not in output.lower()


def test_empty_db_apply_bootstraps_tracking_then_executes_remaining_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "001_first.sql": "CREATE TABLE first_table (id integer);\n",
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            "055_after_tracking.sql": "CREATE TABLE after_table (id integer);\n",
        },
    )
    state = _DbState()
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    applied = apply_pending(migrations=migrations, tracked={}, applied_by="local")

    assert applied == 3
    assert state.executed_migrations == [
        "054_create_schema_migrations.sql",
        "001_first.sql",
        "055_after_tracking.sql",
    ]
    assert set(state.tracked) == {
        "001_first.sql",
        "054_create_schema_migrations.sql",
        "055_after_tracking.sql",
    }
    assert all(row["execution_status"] == "success" for row in state.tracked.values())
    assert all(row["execution_mode"] == "script_apply" for row in state.tracked.values())
    assert all(len(row["checksum_sha256"]) == 64 for row in state.tracked.values())


def test_empty_db_apply_prepares_legacy_greenhouse_profile_before_018(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "018_replace_greenhouse_wildcard_search_terms.sql": (
                "SELECT 1 FROM search_profiles "
                "WHERE profile_name = 'greenhouse_stripe';\n"
            ),
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
        },
    )
    state = _DbState()
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    assert apply_pending(migrations=migrations, tracked={}, applied_by="local") == 2

    assert state.search_profiles["greenhouse_stripe"] == "greenhouse:stripe"
    assert state.executed_migrations == [
        "054_create_schema_migrations.sql",
        "018_replace_greenhouse_wildcard_search_terms.sql",
    ]


def test_failed_018_tracking_row_is_retried_without_checksum_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "018_replace_greenhouse_wildcard_search_terms.sql": (
                "SELECT 1 FROM search_profiles "
                "WHERE profile_name = 'greenhouse_stripe';\n"
            ),
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
        },
    )
    failed = next(
        migration
        for migration in migrations
        if migration.migration_key == "018_replace_greenhouse_wildcard_search_terms.sql"
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="local")
    tracked = {
        tracking.migration_key: _tracked_from_row(state.tracked[tracking.migration_key]),
        failed.migration_key: TrackedMigration(
            migration_key=failed.migration_key,
            version_number=failed.version_number,
            filename=failed.filename,
            checksum_sha256="0" * 64,
            execution_status="failed",
            execution_mode="script_apply",
            applied_by="local",
        ),
    }
    state.tracked[failed.migration_key] = {
        "migration_key": failed.migration_key,
        "version_number": failed.version_number,
        "filename": failed.filename,
        "checksum_sha256": "0" * 64,
        "execution_status": "failed",
        "execution_mode": "script_apply",
        "applied_by": "local",
    }
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    assert apply_pending(migrations=migrations, tracked=tracked, applied_by="local") == 1

    assert state.executed_migrations == ["018_replace_greenhouse_wildcard_search_terms.sql"]
    assert state.tracked[failed.migration_key]["execution_status"] == "success"
    assert state.tracked[failed.migration_key]["checksum_sha256"] == failed.checksum_sha256


def test_schema_migrations_bootstrap_executes_tracking_migration_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "001_first.sql": "CREATE TABLE first_table (id integer);\n",
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
        },
    )
    state = _DbState()
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    assert bootstrap_schema_migrations_if_needed(
        migrations=migrations,
        applied_by="local",
    ) is True

    assert state.executed_migrations == ["054_create_schema_migrations.sql"]
    assert state.tracked["054_create_schema_migrations.sql"]["execution_status"] == "success"


def test_apply_is_idempotent_after_all_migrations_tracked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "001_first.sql": "CREATE TABLE first_table (id integer);\n",
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
        },
    )
    state = _DbState()
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    first = apply_pending(migrations=migrations, tracked={}, applied_by="local")
    tracked = {
        key: _tracked_from_row(row)
        for key, row in state.tracked.items()
    }
    state.executed_migrations.clear()
    second = apply_pending(migrations=migrations, tracked=tracked, applied_by="local")

    assert first == 2
    assert second == 0
    assert state.executed_migrations == []


def test_existing_initialized_db_still_applies_pending_without_rebootstrapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            "055_after_tracking.sql": "CREATE TABLE after_table (id integer);\n",
        },
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="previous")
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )
    tracked = {
        key: _tracked_from_row(row)
        for key, row in state.tracked.items()
    }

    applied = apply_pending(migrations=migrations, tracked=tracked, applied_by="local")

    assert applied == 1
    assert state.executed_migrations == ["055_after_tracking.sql"]
    assert state.tracked["055_after_tracking.sql"]["applied_by"] == "local"


def test_migration_sql_executes_in_autocommit_mode_for_internal_transactions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            "055_internal_transaction.sql": "BEGIN;\nSELECT 55;\nCOMMIT;\n",
        },
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="previous")
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )
    tracked = {
        key: _tracked_from_row(row)
        for key, row in state.tracked.items()
    }

    applied = apply_pending(migrations=migrations, tracked=tracked, applied_by="local")

    assert applied == 1
    assert state.executed_migrations == ["055_internal_transaction.sql"]
    assert state.autocommit_by_sql["055_internal_transaction.sql"] is True
    assert state.tracked["055_internal_transaction.sql"]["execution_status"] == "success"


def test_product_v1_policy_migration_resets_managed_views_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            "077_create_product_v1_monolith_foundation.sql": "SELECT 77;\n",
            "078_activate_product_v1_operator_policy.sql": "SELECT 78;\n",
        },
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    foundation = next(
        migration
        for migration in migrations
        if migration.migration_key == "077_create_product_v1_monolith_foundation.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="previous")
    state.track(foundation, applied_by="previous")
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )
    tracked = {
        key: _tracked_from_row(row)
        for key, row in state.tracked.items()
    }

    applied = apply_pending(migrations=migrations, tracked=tracked, applied_by="local")

    assert applied == 1
    assert state.product_v1_view_reset_count == 1
    assert state.event_log == [
        "reset_product_v1_views",
        "078_activate_product_v1_operator_policy.sql",
        "track:078_activate_product_v1_operator_policy.sql:success",
    ]


@pytest.mark.parametrize(
    "migration_key",
    (
        ORIGIN_PATTERN_TAXONOMY_MIGRATION_KEY,
        ORIGIN_PATTERN_CANDIDATE_TAXONOMY_REPAIR_MIGRATION_KEY,
    ),
)
def test_origin_pattern_migrations_reset_changed_view_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    migration_key: str,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            migration_key: (
                "CREATE OR REPLACE VIEW "
                "gold_origin_promoted_observation_patterns AS SELECT 1;\n"
            ),
        },
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="previous")
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )
    tracked = {
        key: _tracked_from_row(row)
        for key, row in state.tracked.items()
    }

    applied = apply_pending(migrations=migrations, tracked=tracked, applied_by="local")

    assert applied == 1
    assert state.origin_pattern_view_reset_count == 1
    assert state.event_log == [
        "reset_origin_pattern_view",
        migration_key,
        f"track:{migration_key}:success",
    ]


def test_existing_db_with_original_026_checksum_does_not_rerun_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = tmp_path / FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY
    migration_path.write_text("SELECT 26;\n", encoding="utf-8")
    tracking_path = tmp_path / "054_create_schema_migrations.sql"
    tracking_path.write_text(
        "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n",
        encoding="utf-8",
    )
    migrations = discover_migration_files(tmp_path)
    current = parse_migration_file(migration_path)
    assert current is not None
    tracking = parse_migration_file(tracking_path)
    assert tracking is not None
    state = _DbState(table_exists=True)
    tracked = {
        current.migration_key: TrackedMigration(
            migration_key=current.migration_key,
            version_number=current.version_number,
            filename=current.filename,
            checksum_sha256=(
                "b864d49394e8a4f1b58b72a032f85fa02b8250cb9794d2052b0609b00b2b105b"
            ),
            execution_status="success",
            execution_mode="script_apply",
            applied_by="previous",
        ),
        tracking.migration_key: TrackedMigration(
            migration_key=tracking.migration_key,
            version_number=tracking.version_number,
            filename=tracking.filename,
            checksum_sha256=tracking.checksum_sha256,
            execution_status="success",
            execution_mode="script_apply",
            applied_by="previous",
        ),
    }
    state.tracked[current.migration_key] = {
        "migration_key": current.migration_key,
        "version_number": current.version_number,
        "filename": current.filename,
        "checksum_sha256": tracked[current.migration_key].checksum_sha256,
        "execution_status": "success",
        "execution_mode": "script_apply",
        "applied_by": "previous",
    }
    state.track(tracking, applied_by="previous")
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    assert apply_pending(migrations=migrations, tracked=tracked, applied_by="local") == 0
    assert state.executed_migrations == []


def test_existing_db_with_compatible_026_checksum_still_runs_forward_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations = _write_migrations(
        tmp_path,
        {
            FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY: "SELECT 26;\n",
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
            "108_repair_market_evidence_observation_day_unique_index.sql": (
                "DROP INDEX IF EXISTS idx_market_evidence_observation_unique;\n"
            ),
        },
    )
    foundation = next(
        migration
        for migration in migrations
        if migration.migration_key == FALSE_NEGATIVE_FOUNDATION_MIGRATION_KEY
    )
    tracking = next(
        migration
        for migration in migrations
        if migration.migration_key == "054_create_schema_migrations.sql"
    )
    state = _DbState(table_exists=True)
    state.track(tracking, applied_by="previous")
    tracked = {
        foundation.migration_key: TrackedMigration(
            migration_key=foundation.migration_key,
            version_number=foundation.version_number,
            filename=foundation.filename,
            checksum_sha256=(
                "df35b6c84908b2ee374a42a863e12dc382a84b10ce4930db769bb43f9560062e"
            ),
            execution_status="success",
            execution_mode="script_apply",
            applied_by="local",
        ),
        tracking.migration_key: _tracked_from_row(state.tracked[tracking.migration_key]),
    }
    state.tracked[foundation.migration_key] = {
        "migration_key": foundation.migration_key,
        "version_number": foundation.version_number,
        "filename": foundation.filename,
        "checksum_sha256": tracked[foundation.migration_key].checksum_sha256,
        "execution_status": "success",
        "execution_mode": "script_apply",
        "applied_by": "local",
    }
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    assert apply_pending(migrations=migrations, tracked=tracked, applied_by="local") == 1
    assert state.executed_migrations == [
        "108_repair_market_evidence_observation_day_unique_index.sql"
    ]


def test_bootstrap_existing_still_refuses_fresh_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.apply_db_migrations import bootstrap_existing

    migrations = _write_migrations(
        tmp_path,
        {
            "054_create_schema_migrations.sql": (
                "CREATE TABLE IF NOT EXISTS schema_migrations (id integer);\n"
            ),
        },
    )
    state = _DbState()
    monkeypatch.setattr(
        "scripts.apply_db_migrations.connect",
        _fake_connect(state),
    )

    with pytest.raises(RuntimeError, match="schema_migrations table does not exist"):
        bootstrap_existing(migrations=migrations, tracked={}, applied_by="local")


def test_historical_dependency_preparation_is_limited_to_018() -> None:
    state = _DbState(table_exists=True)
    conn = _FakeConnection(state)
    migration = _migration("019_other.sql", 19)

    prepare_historical_migration_dependencies(conn, migration)

    assert state.search_profiles == {}


class _DbState:
    def __init__(self, *, table_exists: bool = False) -> None:
        self.table_exists = table_exists
        self.tracked: dict[str, dict[str, object]] = {}
        self.executed_migrations: list[str] = []
        self.autocommit_by_sql: dict[str, bool] = {}
        self.event_log: list[str] = []
        self.product_v1_view_reset_count = 0
        self.origin_pattern_view_reset_count = 0
        self.search_profiles: dict[str, str] = {}

    def track(self, migration, *, applied_by: str) -> None:
        self.tracked[migration.migration_key] = {
            "migration_key": migration.migration_key,
            "version_number": migration.version_number,
            "filename": migration.filename,
            "checksum_sha256": migration.checksum_sha256,
            "execution_status": "success",
            "execution_mode": "script_apply",
            "applied_by": applied_by,
        }


class _FakeConnection:
    def __init__(self, state: _DbState, *, autocommit: bool = False) -> None:
        self.state = state
        self.autocommit = autocommit

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def transaction(self):
        return self

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.state, autocommit=self.autocommit)


class _FakeCursor:
    def __init__(self, state: _DbState, *, autocommit: bool = False) -> None:
        self.state = state
        self.autocommit = autocommit
        self.fetchone_row = None
        self.fetchall_rows: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params=None) -> None:
        normalized = " ".join(sql.split())
        if "SELECT EXISTS" in normalized and "schema_migrations" in normalized:
            self.fetchone_row = {"exists": self.state.table_exists}
            return
        if normalized.startswith("SELECT migration_key"):
            self.fetchall_rows = list(self.state.tracked.values())
            return
        if normalized.startswith("INSERT INTO schema_migrations"):
            assert params is not None
            (
                migration_key,
                version_number,
                filename,
                checksum_sha256,
                execution_status,
                execution_mode,
                applied_by,
                _error_message,
            ) = params
            self.state.tracked[migration_key] = {
                "migration_key": migration_key,
                "version_number": version_number,
                "filename": filename,
                "checksum_sha256": checksum_sha256,
                "execution_status": execution_status,
                "execution_mode": execution_mode,
                "applied_by": applied_by,
            }
            self.state.event_log.append(f"track:{migration_key}:{execution_status}")
            return
        if normalized.startswith("DROP VIEW IF EXISTS gold_product_v1_application_readiness"):
            self.state.product_v1_view_reset_count += 1
            self.state.event_log.append("reset_product_v1_views")
            return
        if normalized.startswith("DROP VIEW IF EXISTS gold_origin_promoted_observation_patterns"):
            self.state.origin_pattern_view_reset_count += 1
            self.state.event_log.append("reset_origin_pattern_view")
            return
        if normalized.startswith("INSERT INTO search_profiles"):
            self.state.search_profiles.setdefault("greenhouse_stripe", "greenhouse:stripe")
            return

        migration_name = sql.split("-- migration:", maxsplit=1)[1].strip().split()[0]
        if (
            migration_name == "078_activate_product_v1_operator_policy.sql"
            and self.state.product_v1_view_reset_count == 0
        ):
            raise RuntimeError("Product V1 managed views were not reset before 078")
        if "greenhouse_stripe" in sql and "greenhouse_stripe" not in self.state.search_profiles:
            raise RuntimeError("Expected active Greenhouse profile not found")
        self.state.executed_migrations.append(migration_name)
        self.state.event_log.append(migration_name)
        self.state.autocommit_by_sql[migration_name] = self.autocommit
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in sql:
            self.state.table_exists = True

    def fetchone(self):
        return self.fetchone_row

    def fetchall(self):
        return self.fetchall_rows


def _write_migrations(tmp_path: Path, files: dict[str, str]):
    for filename, sql in files.items():
        (tmp_path / filename).write_text(
            f"-- migration: {filename}\n{sql}",
            encoding="utf-8",
        )
    return discover_migration_files(tmp_path)


def _fake_connect(state: _DbState):
    def connect_fake(**kwargs):
        return _FakeConnection(state, autocommit=kwargs.get("autocommit", False))

    return connect_fake


def _tracked_from_row(row: dict[str, object]) -> TrackedMigration:
    return TrackedMigration(
        migration_key=str(row["migration_key"]),
        version_number=int(row["version_number"]),
        filename=str(row["filename"]),
        checksum_sha256=str(row["checksum_sha256"]),
        execution_status=str(row["execution_status"]),
        execution_mode=str(row["execution_mode"]),
        applied_by=str(row["applied_by"]),
    )


def _migration(filename: str, version: int) -> MigrationFile:
    return MigrationFile(
        migration_key=filename,
        version_number=version,
        filename=filename,
        path=Path(filename),
        checksum_sha256="a" * 64,
    )
