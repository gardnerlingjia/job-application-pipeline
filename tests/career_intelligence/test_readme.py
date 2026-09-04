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


def test_readme_documents_v14_operator_workflow_contract():
    text = README.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "V1.4-lite adds persistent local operator" in text
    assert "python -m src.career_intelligence.operator_state list" in text
    assert "--state INTERESTED" in text
    assert ".runtime/career_intelligence/operator_state.json" in text
    assert "The default radar omits `DISMISSED`" in text
    assert "canonical operator workflow" in text
    assert "lower-level V1.2 recommendation radar" in text
    assert "remove `.runtime/career_intelligence/operator_state.json`" in normalized


def test_readme_documents_v20_control_center_contract():
    text = README.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "V2.0 projects Career Intelligence into the existing Product V1" in text
    assert "`source_file` back to `silver_job_id`" in text
    assert "Product V1 ranking" in normalized
    assert "Top-5 semantics" in normalized
    assert "network_access" in text
    assert "operator_state.py` persistence logic" in text
    assert "Application Workspace with that job selected" in text
    assert "Scores are never fabricated" in normalized


def test_readme_documents_v21_source_strategy_contract():
    text = README.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "V2.1 adds Lingjia Gardner's source strategy" in text
    assert "config/career_source_strategy.yaml" in text
    assert "Tier A contains strategic employer sources" in text
    assert "source role: `employer_origin` or `discovery`" in text
    assert "Employer-origin sources remain preferred evidence" in text
    assert "discovery sources may identify opportunities" in normalized.casefold()
    assert "Existing generic/demo sources remain visible" in text
    assert "does not activate or crawl sources automatically" in normalized


def test_readme_documents_v22_adaptive_source_contract():
    text = README.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "V2.2 adds adaptive source discovery" in normalized
    assert "config/career_adaptive_source_rules.yaml" in text
    assert ".runtime/career_intelligence/adaptive_source_state.json" in text
    assert "Employers already present in the curated strategy are not duplicated" in normalized
    assert "Candidate action buttons write only adaptive source state" in normalized
    assert "never downgrade a configured source automatically" in normalized
