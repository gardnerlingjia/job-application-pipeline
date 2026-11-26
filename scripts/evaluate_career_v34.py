"""Read-only, reproducible V3.4 comparisons. Reports never become pipeline inputs."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.career_intelligence.competency_qualification import (
    load_candidate_evidence, load_strategy, qualify_vacancy,
)
from src.career_intelligence.market_intelligence import (
    build_market_intelligence, load_inventory_rows, observation_description,
)
from src.config import get_database_config
from src.career_intelligence.classifier import strategy_context

FIXTURE = Path("tests/fixtures/career_intelligence/v34_evaluation.json")


def evaluate_cases(cases: list[dict], *, candidate_facts: Path | None = None) -> dict:
    strategy = load_strategy()
    candidate = load_candidate_evidence(strategy, candidate_facts)
    records = []
    for row in cases:
        q = qualify_vacancy(row, config=strategy, candidate=candidate)
        records.append({
            "id": row["id"], "kind": row.get("fixture_kind", "captured_source"),
            "title": row["title"], "company": row["company_name"],
            "source_url": row.get("source_url"), "expected": row.get("expected_status"),
            "actual": q["status"], "legacy_title_gate": q["title_gate"]["reason"],
            "legacy_strategy_transition": strategy_context(
                row["title"], row.get("description", ""))["transition"],
            "qualification": q,
        })
    labelled = [row for row in records if row["expected"]]
    plausible_labels = [row for row in zip(cases, records) if "expected_plausible" in row[0]]
    false_positive = [record["id"] for case, record in plausible_labels
                      if record["qualification"]["plausible_cross_industry"]
                      and not case["expected_plausible"]]
    false_negative = [record["id"] for case, record in plausible_labels
                      if not record["qualification"]["plausible_cross_industry"]
                      and case["expected_plausible"]]
    return {"case_count": len(records),
            "reviewed_paraphrases": sum(row["kind"] == "reviewed_paraphrase" for row in records),
            "synthetic_controls": sum(row["kind"] == "synthetic_control" for row in records),
            "status_disagreements": [row["id"] for row in labelled
                                     if row["actual"] != row["expected"]],
            "false_positives_on_curated_plausibility_labels": false_positive,
            "false_negatives_on_curated_plausibility_labels": false_negative,
            "limitations": "Curated paraphrases and synthetic controls are not population precision "
                           "or recall. Provisional profiles are not a complete verified CV.",
            "records": records}


def acceptance_funnel(preview: dict) -> dict:
    """Separate job evidence, candidate evidence and confirmed opportunity quality."""
    qualifications = [row["qualification"] for row in preview["vacancies"]]
    verified = {key for q in qualifications for match in q["competency_evidence"]
                for key in match["candidate_fact_keys"]
                if match["evidence_status"] == "cv_verified_professional"}
    return {
        "newly_discovered_vacancies_this_evaluation": 0,
        "discovery_explanation": "Read-only evaluation; no discovery run or vacancy writes.",
        "description_qualified_strong_fit": sum(q["status"] == "STRONG_TRANSFERABLE_FIT"
                                                for q in qualifications),
        "description_possible_fit_pending_clarification": sum(q["status"] == "POSSIBLE_FIT"
                                                               for q in qualifications),
        "plausible_cross_industry_clarification_candidates": sum(
            q["plausible_cross_industry"] for q in qualifications),
        "verified_candidate_fact_keys_matched": sorted(verified),
        "vacancies_with_provisional_competency_evidence": sum(
            any(m["evidence_status"] == "documented_profile_provisional"
                for m in q["competency_evidence"]) for q in qualifications),
        "vacancies_with_cv_evidence_pending_profile_approval": sum(
            any(m["evidence_status"] == "cv_supported_pending_profile_approval"
                for m in q["competency_evidence"]) for q in qualifications),
        "china_europe_cv_supported_pending_profile_approval": sum(
            q["china_europe"]["candidate_evidence_status"] == "cv_supported_pending_profile_approval"
            for q in qualifications),
        "china_europe_pending_verification": sum(
            q["china_europe"]["candidate_evidence_status"] == "pending_cv_verification"
            for q in qualifications),
        "opportunity_quality_change_vs_v33": {
            "confirmed_gain": None,
            "reason": "Additional description evidence and clarification candidates are visible; "
                      "a confirmed candidate-fit gain requires CV reconciliation and location "
                      "clarification. No comparable independently reviewed outcome baseline exists.",
            "historical_assessments_changed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--candidate-facts", type=Path)
    parser.add_argument("--calibration-baseline", type=Path)
    parser.add_argument("--live-inventory", action="store_true")
    parser.add_argument("--output", type=Path,
                        default=Path(".runtime/career_intelligence/v34/evaluation.json"))
    args = parser.parse_args(argv)
    report = {"evaluated_at": datetime.now(UTC).isoformat(), "strategy_version": "v3.4",
              "default_strategy": "v3.3", "production_activation_recommended": False,
              "fixture": evaluate_cases(json.loads(args.fixture.read_text())["cases"],
                                        candidate_facts=args.candidate_facts)}
    if args.live_inventory:
        with psycopg.connect(**get_database_config(),
                             options="-c default_transaction_read_only=on") as conn:
            rows = load_inventory_rows(conn)
        legacy = build_market_intelligence(rows)
        preview = build_market_intelligence(rows, strategy_version="v3.4",
                                            candidate_facts_path=args.candidate_facts)
        if args.calibration_baseline:
            baseline = json.loads(args.calibration_baseline.read_text(encoding="utf-8"))
            cohort_ids = set(baseline["union_ids"])
            indexed = {row["vacancy_id"]: row for row in preview["vacancies"]}
            cohort = [indexed[key] for key in sorted(cohort_ids) if key in indexed]
            new_leads = [row for row in preview["vacancies"]
                         if row["vacancy_id"] not in cohort_ids and
                         row["qualification"]["opportunity_review"]["judgment"] in {"PURSUE", "CLARIFY"}]
            report["calibration"] = {
                "baseline_possible": len(baseline["possible_ids"]),
                "baseline_china_relevant": len(baseline["china_ids"]),
                "overlap": len(baseline["overlap_ids"]), "distinct_cohort": len(cohort_ids),
                "reviewed": len(cohort), "missing_ids": sorted(cohort_ids - indexed.keys()),
                "judgments": dict(Counter(r["qualification"]["opportunity_review"]["judgment"]
                                           for r in cohort)),
                "cohort_records": cohort, "additional_clarification_leads": new_leads,
                "additional_leads_are_existing_vacancies_not_discoveries": True,
                "production_evidence_activated": False,
            }
        report["inventory"] = {
            "distinct_active_actual_vacancies": len(rows),
            "v33": legacy["summary"], "v34": preview["summary"],
            "acceptance_funnel": acceptance_funnel(preview),
            "industries": preview["industries"], "role_families": preview["role_families"],
            "geography": preview["geography"],
            "location_compatibility": dict(Counter(
                row["qualification"]["location"]["status"] for row in preview["vacancies"])),
            "candidate_verification_status": preview["candidate_verification_status"],
            "captured_description_count": sum(bool(observation_description(row)[0].strip())
                                               for row in rows),
            "specialist_requirements_needing_cv_review": sum(
                bool(row["qualification"]["specialist_gaps"]) for row in preview["vacancies"]),
            "plausible_cross_industry": [
                row for row in preview["vacancies"]
                if row["qualification"]["plausible_cross_industry"]],
            "title_gate_comparison_identical": legacy["summary"]["gate_counts"] ==
                                              preview["summary"]["gate_counts"],
            "assessments_performed": 0,
            "assessment_limitation": "Existing V3.3 automotive-specific transition rules remain "
                                    "unchanged and may underrate cross-industry delivery. No new "
                                    "weights, scores, WATCH/SKIP or operator changes.",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"output": str(args.output), "fixture_cases": report["fixture"]["case_count"],
                      "disagreements": report["fixture"]["status_disagreements"],
                      "inventory": {key: value for key, value in report.get("inventory", {}).items()
                                    if key in {"distinct_active_actual_vacancies", "v33", "v34",
                                               "location_compatibility"}}}, indent=2))
    return int(bool(report["fixture"]["status_disagreements"]))


if __name__ == "__main__":
    raise SystemExit(main())
