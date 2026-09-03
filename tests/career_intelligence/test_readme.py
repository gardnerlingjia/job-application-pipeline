from pathlib import Path


README = Path("docs/career-intelligence/README.md")


def test_readme_documents_v12_silver_ingestion_contract():
    text = README.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "V1.2 adds Silver-layer ingestion" in text
    assert "python -m src.career_intelligence.ingest_silver" in text
    assert "source_name + external_job_id" in text
    assert "silver_ingestion_provenance.json" in text
    assert "does not define a description column" in text
    assert "never trigger applications" in normalized


def test_readme_documents_v13_daily_runner_contract():
    text = README.read_text(encoding="utf-8")

    assert "V1.3 adds a local daily runner" in text
    assert "python -m src.career_intelligence.daily" in text
    assert ".runtime/career_intelligence/logs/daily_*.log" in text
    assert "macos-launchd.example.plist" in text
    assert "launchctl unload" in text
