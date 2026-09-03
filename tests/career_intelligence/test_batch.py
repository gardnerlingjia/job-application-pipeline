import json

from src.career_intelligence.batch import (
    RESULT_FIELDS,
    SCHEMA_VERSION,
    process_batch,
)


def write_job(path, company="MOIA", title="Program Manager", description="Berlin program"):
    path.write_text(
        json.dumps({"company": company, "title": title, "description": description}),
        encoding="utf-8",
    )


def fake_assessment(company, title, description, *, score=70, recommendation="EXPLORE"):
    return {
        "company_name": company,
        "title": title,
        "career_lane": "technology_programs",
        "career_lane_label": "Technology Programs",
        "opportunity_score": score,
        "recommendation": recommendation,
        "constraint_action": "CLEAR",
        "hard_skips": [],
        "high_risks": [],
        "reviews": [],
        "matched_capabilities": [],
    }


def batch_paths(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return inbox, tmp_path / "processed", tmp_path / "results"


def test_successful_batch_processing_and_exact_schema(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "moia.json")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 1
    assert not (inbox / "moia.json").exists()
    assert (processed / "moia.json").exists()
    result = summary["opportunities"][0]
    assert set(result) == RESULT_FIELDS
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["source_file"] == "moia.json"


def test_malformed_json_does_not_stop_batch(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    (inbox / "broken.json").write_text("{broken", encoding="utf-8")
    write_job(inbox / "valid.json")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 1
    assert summary["errors"][0]["file"] == "broken.json"
    assert (inbox / "broken.json").exists()
    assert (processed / "valid.json").exists()


def test_missing_required_fields_are_reported(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    (inbox / "missing.json").write_text(json.dumps({"company": "MOIA"}), encoding="utf-8")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert "title, description" in summary["errors"][0]["error"]
    assert (inbox / "missing.json").exists()


def test_whitespace_only_required_fields_are_rejected(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "blank.json", title=" \n\t")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert "title" in summary["errors"][0]["error"]
    assert (inbox / "blank.json").exists()


def test_non_object_json_is_rejected(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    (inbox / "array.json").write_text(json.dumps(["not", "a", "job"]), encoding="utf-8")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert "JSON object" in summary["errors"][0]["error"]
    assert (inbox / "array.json").exists()


def test_new_empty_inbox_writes_empty_outputs(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)

    summary = process_batch(inbox, processed, results)

    assert summary["opportunities"] == []
    assert json.loads((results / "opportunities.json").read_text()) == []
    radar = (results / "opportunity_radar.md").read_text()
    assert "## APPLY_NOW" in radar
    assert "## SKIP" in radar


def test_empty_rerun_preserves_prior_outputs_byte_for_byte(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "first.json")
    process_batch(inbox, processed, results)
    json_before = (results / "opportunities.json").read_bytes()
    radar_before = (results / "opportunity_radar.md").read_bytes()

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert (results / "opportunities.json").read_bytes() == json_before
    assert (results / "opportunity_radar.md").read_bytes() == radar_before


def test_non_empty_runs_merge_into_cumulative_results(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "first.json", company="First")
    process_batch(inbox, processed, results)
    write_job(inbox / "second.json", company="Second")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 1
    assert {item["source_file"] for item in summary["opportunities"]} == {
        "first.json",
        "second.json",
    }
    persisted = json.loads((results / "opportunities.json").read_text())
    assert len(persisted) == 2


def test_processed_destination_collision_preserves_source(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    processed.mkdir()
    write_job(inbox / "same.json", company="Inbox")
    write_job(processed / "same.json", company="Existing")
    existing = (processed / "same.json").read_bytes()

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert summary["errors"][0]["file"] == "same.json"
    assert (inbox / "same.json").exists()
    assert (processed / "same.json").read_bytes() == existing


def test_duplicate_source_in_results_is_not_added_again(tmp_path):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "same.json")
    process_batch(inbox, processed, results)
    write_job(inbox / "same.json")

    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert len(summary["opportunities"]) == 1
    assert (inbox / "same.json").exists()


def test_source_is_preserved_when_result_projection_fails(tmp_path, monkeypatch):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "job.json")

    def fail_projection(assessment, source_file):
        raise RuntimeError("projection failed")

    monkeypatch.setattr("src.career_intelligence.batch._result_record", fail_projection)
    summary = process_batch(inbox, processed, results)

    assert summary["processed"] == 0
    assert "projection failed" in summary["errors"][0]["error"]
    assert (inbox / "job.json").exists()
    assert not (processed / "job.json").exists()


def test_results_are_ranked_by_score(tmp_path, monkeypatch):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(inbox / "low.json", company="Low")
    write_job(inbox / "high.json", company="High")

    def assess(company, title, description):
        return fake_assessment(company, title, description, score=90 if company == "High" else 40)

    monkeypatch.setattr("src.career_intelligence.batch.assess_opportunity", assess)
    summary = process_batch(inbox, processed, results)

    assert [item["company"] for item in summary["opportunities"]] == ["High", "Low"]


def test_equal_scores_sort_by_company_then_title_case_insensitively(tmp_path, monkeypatch):
    inbox, processed, results = batch_paths(tmp_path)
    jobs = [("z.json", "beta", "A"), ("a.json", "Alpha", "Z"), ("m.json", "alpha", "a")]
    for filename, company, title in jobs:
        write_job(inbox / filename, company=company, title=title)

    monkeypatch.setattr(
        "src.career_intelligence.batch.assess_opportunity",
        lambda company, title, description: fake_assessment(company, title, description),
    )
    summary = process_batch(inbox, processed, results)

    assert [(item["company"], item["title"]) for item in summary["opportunities"]] == [
        ("alpha", "a"),
        ("Alpha", "Z"),
        ("beta", "A"),
    ]


def test_radar_groups_recommendations_and_sorts_scores(tmp_path, monkeypatch):
    inbox, processed, results = batch_paths(tmp_path)
    for company in ("Apply Low", "Watch", "Apply High"):
        write_job(inbox / f"{company}.json", company=company)
    scores = {
        "Apply Low": (82, "APPLY_NOW"),
        "Watch": (50, "WATCH"),
        "Apply High": (95, "APPLY_NOW"),
    }

    def assess(company, title, description):
        score, recommendation = scores[company]
        return fake_assessment(
            company,
            title,
            description,
            score=score,
            recommendation=recommendation,
        )

    monkeypatch.setattr("src.career_intelligence.batch.assess_opportunity", assess)
    process_batch(inbox, processed, results)
    radar = (results / "opportunity_radar.md").read_text()

    assert radar.index("Apply High") < radar.index("Apply Low") < radar.index("## NETWORK_FIRST")
    assert radar.index("## WATCH") < radar.index("Watch") < radar.index("## SKIP")


def test_radar_normalizes_and_escapes_markdown_text(tmp_path, monkeypatch):
    inbox, processed, results = batch_paths(tmp_path)
    write_job(
        inbox / "markdown.json",
        company="ACME *Mobility*\nGroup",
        title="[Lead]  Program_Manager",
    )
    monkeypatch.setattr(
        "src.career_intelligence.batch.assess_opportunity",
        lambda company, title, description: fake_assessment(company, title, description),
    )

    process_batch(inbox, processed, results)
    radar = (results / "opportunity_radar.md").read_text()

    assert r"ACME \*Mobility\* Group" in radar
    assert r"\[Lead\] Program\_Manager" in radar
    assert "ACME *Mobility*\nGroup" not in radar
