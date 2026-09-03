from __future__ import annotations

from pathlib import Path

from scripts.check_documentation_architecture import build_documentation_architecture_report

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_doc001l_current_repository_uses_target_docs_top_level_structure() -> None:
    report = build_documentation_architecture_report(ROOT)

    assert report.status == "pass"
    assert report.top_level_dirs == [
        "archive",
        "career-intelligence",
        "current",
        "decisions",
        "guides",
        "knowledge",
        "planning",
        "reference",
    ]
    assert report.issue_count == 0


def test_doc001l_readme_explains_artifact_level_rule() -> None:
    text = _read("docs/README.md")

    assert "current/" in text
    assert "guides/" in text
    assert "reference/" in text
    assert "decisions/" in text
    assert "planning/" in text
    assert "archive/" in text
    assert "The documentation architecture applies to files, not only folders" in text


def test_doc001l_root_readme_points_to_new_documentation_surface() -> None:
    text = _read("README.md")

    assert "docs/current/product.md" in text
    assert "docs/current/architecture.md" in text
    assert "docs/guides/development-workflow.md" in text
    assert "docs/source_analysis/" not in text
    assert "docs/architecture/" not in text


def test_doc001l_generated_connector_docs_use_active_planning_source_candidates() -> None:
    source_paths = [
        "src/search_intelligence/approval_gated_connector_build.py",
        "src/search_intelligence/employer_origin_connector_generation.py",
        "scripts/run_employer_origin_connector_artifact_generator.py",
        "scripts/run_employer_origin_agent_chain.py",
        "scripts/run_employer_origin_connector_registration_plan_agent.py",
        "scripts/run_employer_origin_registration_execution_plan_agent.py",
    ]

    for path in source_paths:
        text = _read(path)
        assert "docs/planning/active/source-candidates" in text
        assert "docs/source_analysis" not in text
