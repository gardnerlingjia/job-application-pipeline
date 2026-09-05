from pathlib import Path


MIGRATION = Path("db/migrations/026_create_false_negative_intelligence_foundation.sql")
REPAIR_MIGRATION = Path(
    "db/migrations/108_repair_market_evidence_observation_day_unique_index.sql"
)


def test_market_evidence_unique_index_uses_immutable_seen_timestamp_expression() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    unique_index = sql[
        sql.index("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_evidence_observation_unique"):
        sql.index("CREATE OR REPLACE VIEW candidate_market_evidence_summary")
    ]

    assert "source_seen_at::date" not in unique_index
    assert "observed_at::date" not in unique_index
    assert "coalesce(source_seen_at, observed_at) AT TIME ZONE 'UTC'" in unique_index
    assert "::date" in unique_index


def test_false_negative_foundation_preserves_observational_boundaries() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS market_evidence" in sql
    assert "CREATE OR REPLACE VIEW candidate_market_evidence_summary" in sql
    assert "CREATE TABLE IF NOT EXISTS false_negative_risk_snapshots" in sql


def test_market_evidence_day_unique_index_repair_is_forward_migration() -> None:
    sql = REPAIR_MIGRATION.read_text(encoding="utf-8")

    assert "DROP INDEX IF EXISTS idx_market_evidence_observation_unique" in sql
    assert "CREATE UNIQUE INDEX idx_market_evidence_observation_unique" in sql
    assert "coalesce(source_seen_at, observed_at) AT TIME ZONE 'UTC'" in sql
    assert "::date" in sql
