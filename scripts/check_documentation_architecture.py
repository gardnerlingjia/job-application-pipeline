#!/usr/bin/env python3
"""DOC-001L documentation information-architecture guard.

The guard checks the repository documentation shape after DOC-001L. It is
intentionally structural: it does not judge prose quality, but it prevents the
old flat docs/ surface from silently growing back.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

ALLOWED_TOP_LEVEL_DIRS = {
    "archive",
    "career-intelligence",
    "current",
    "decisions",
    "guides",
    "knowledge",
    "planning",
    "reference",
}

ALLOWED_TOP_LEVEL_FILES = {"README.md"}

REQUIRED_FILES = {
    "docs/README.md",
    "docs/current/product.md",
    "docs/current/architecture.md",
    "docs/current/pipeline.md",
    "docs/current/system-diagrams.md",
    "docs/current/governance.md",
    "docs/current/operations.md",
    "docs/guides/development-workflow.md",
    "docs/guides/operator-runbook.md",
    "docs/reference/database/schema_overview.md",
    "docs/reference/governance/governance_foundation.md",
    "docs/reference/security/search_intelligence_security_baseline.md",
    "docs/decisions/adr_status_table.md",
    "docs/decisions/adr/033_define_search_intelligence_safety_security_boundaries.md",
    "docs/planning/active/README.md",
    "docs/archive/planning/doc001j_link_reference_check.md",
    "docs/archive/source-analysis/stepstone_company_discovery_cycle.md",
}

FORBIDDEN_TOP_LEVEL_DIRS = {
    "adr",
    "architecture",
    "classification",
    "data_sources",
    "database",
    "design",
    "development",
    "governance",
    "observability",
    "operations",
    "project_state",
    "relevance",
    "reviews",
    "security",
    "source_analysis",
    "visualization",
}


@dataclass(frozen=True)
class DocumentationArchitectureReport:
    status: str
    top_level_dirs: list[str]
    unexpected_top_level_dirs: list[str]
    unexpected_top_level_files: list[str]
    forbidden_top_level_dirs_present: list[str]
    missing_required_files: list[str]

    @property
    def issue_count(self) -> int:
        return (
            len(self.unexpected_top_level_dirs)
            + len(self.unexpected_top_level_files)
            + len(self.forbidden_top_level_dirs_present)
            + len(self.missing_required_files)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "top_level_dirs": self.top_level_dirs,
            "unexpected_top_level_dirs": self.unexpected_top_level_dirs,
            "unexpected_top_level_files": self.unexpected_top_level_files,
            "forbidden_top_level_dirs_present": self.forbidden_top_level_dirs_present,
            "missing_required_files": self.missing_required_files,
            "issue_count": self.issue_count,
        }


def build_documentation_architecture_report(root: Path) -> DocumentationArchitectureReport:
    docs_dir = root / "docs"
    top_level_dirs = sorted(path.name for path in docs_dir.iterdir() if path.is_dir()) if docs_dir.exists() else []
    top_level_files = sorted(path.name for path in docs_dir.iterdir() if path.is_file()) if docs_dir.exists() else []

    unexpected_dirs = sorted(set(top_level_dirs) - ALLOWED_TOP_LEVEL_DIRS)
    unexpected_files = sorted(set(top_level_files) - ALLOWED_TOP_LEVEL_FILES)
    forbidden_present = sorted(set(top_level_dirs) & FORBIDDEN_TOP_LEVEL_DIRS)
    missing_required = sorted(path for path in REQUIRED_FILES if not (root / path).exists())

    issue_count = len(unexpected_dirs) + len(unexpected_files) + len(forbidden_present) + len(missing_required)

    return DocumentationArchitectureReport(
        status="pass" if issue_count == 0 else "fail",
        top_level_dirs=top_level_dirs,
        unexpected_top_level_dirs=unexpected_dirs,
        unexpected_top_level_files=unexpected_files,
        forbidden_top_level_dirs_present=forbidden_present,
        missing_required_files=missing_required,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DOC-001L documentation information architecture.")
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    report = build_documentation_architecture_report(Path(args.root).resolve())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"status={report.status}")
        print(f"top_level_dirs={','.join(report.top_level_dirs)}")
        print(f"issue_count={report.issue_count}")
        for key, value in report.to_dict().items():
            if isinstance(value, list) and value and key != "top_level_dirs":
                print(f"{key}:")
                for item in value:
                    print(f"- {item}")
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
