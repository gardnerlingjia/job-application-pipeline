from __future__ import annotations

from pathlib import Path


def test_origin_pattern_promotion_taxonomy_migration_adds_semantic_columns() -> None:
    sql = Path("db/migrations/066_harden_origin_pattern_promotion_taxonomy.sql").read_text()

    assert "ADD COLUMN IF NOT EXISTS pattern_category" in sql
    assert "ADD COLUMN IF NOT EXISTS usage_scope" in sql
    assert "location_multi_signal" in sql
    assert "remote_work_signal" in sql
    assert "profile_ambiguous_signal" in sql
    assert "detail_url_discovery" in sql
    assert "listing_url_discovery" in sql


def test_origin_pattern_promotion_taxonomy_migration_keeps_historical_sql_stable() -> None:
    sql = Path("db/migrations/066_harden_origin_pattern_promotion_taxonomy.sql").read_text()

    assert "DROP VIEW IF EXISTS gold_origin_promoted_observation_patterns" not in sql
    assert "CREATE OR REPLACE VIEW gold_origin_promoted_observation_patterns" in sql


def test_origin_pattern_promotion_taxonomy_migration_repairs_flat_a2d_outputs() -> None:
    sql = Path("db/migrations/066_harden_origin_pattern_promotion_taxonomy.sql").read_text().lower()

    assert "pattern_type = 'remote_signal'" in sql
    assert "'+ weitere'" in sql
    assert "promotion_status = 'candidate'" in sql
    assert "pattern_type = 'profile_signal'" in sql
    assert "lower(pattern_value) = 'bi'" in sql


def test_origin_observed_pattern_taxonomy_repair_migration_covers_candidate_table_and_domain_signal() -> None:
    sql = Path("db/migrations/069_repair_origin_observed_pattern_taxonomy_columns.sql").read_text().lower()

    assert "alter table origin_observed_pattern_candidates" in sql
    assert "add column if not exists pattern_category" in sql
    assert "add column if not exists usage_scope" in sql
    assert "profile_domain_signal" in sql
    assert "data & analytics" in sql
    assert "pattern_type = 'structural_marker'" in sql
    assert "diagnostics only" in sql


def test_origin_pattern_candidate_taxonomy_repair_keeps_historical_sql_stable() -> None:
    sql = Path(
        "db/migrations/070_repair_origin_observed_pattern_candidate_taxonomy_columns.sql"
    ).read_text()

    assert "DROP VIEW IF EXISTS gold_origin_promoted_observation_patterns" not in sql
    assert "CREATE OR REPLACE VIEW gold_origin_promoted_observation_patterns" in sql
