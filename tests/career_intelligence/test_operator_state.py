import json

import pytest

from src.career_intelligence.batch import RESULT_FIELDS
from src.career_intelligence.operator_state import (
    VALID_STATES,
    format_state_rows,
    list_operator_states,
    load_state_payload,
    operator_state_counts,
    opportunities_with_state,
    render_operator_radar,
    set_operator_state,
    state_for_opportunity,
)


def opportunity(
    source_file,
    *,
    company="Example",
    title="Role",
    recommendation="EXPLORE",
    score=70,
):
    return {
        "schema_version": 1,
        "source_file": source_file,
        "company": company,
        "title": title,
        "career_lane": "data",
        "career_lane_label": "Data",
        "opportunity_score": score,
        "recommendation": recommendation,
        "constraint_action": "CLEAR",
        "risks": [],
        "key_matched_capabilities": [],
    }


def test_default_operator_state_is_new():
    payload = load_state_payload()
    assert state_for_opportunity(opportunity("silver-a.json"), payload) == "NEW"


@pytest.mark.parametrize("state", VALID_STATES)
def test_setting_each_valid_state(tmp_path, state):
    path = tmp_path / "operator_state.json"

    payload = set_operator_state(
        source_file="silver-a.json",
        state=state,
        path=path,
    )

    assert payload["states"]["silver-a.json"]["state"] == state
    assert load_state_payload(path)["states"]["silver-a.json"]["state"] == state


def test_invalid_state_is_rejected_without_creating_state_file(tmp_path):
    path = tmp_path / "operator_state.json"

    with pytest.raises(ValueError, match="invalid operator state"):
        set_operator_state(source_file="silver-a.json", state="MAYBE", path=path)

    assert not path.exists()


def test_state_survives_daily_rerun_style_reload(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-a.json", state="INTERESTED", path=path)

    first = load_state_payload(path)
    second = load_state_payload(path)

    assert state_for_opportunity(opportunity("silver-a.json"), first) == "INTERESTED"
    assert state_for_opportunity(opportunity("silver-a.json"), second) == "INTERESTED"


def test_state_survives_silver_reingestion_for_same_source_file(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-stable.json", state="REVIEWED", path=path)

    refreshed = opportunity(
        "silver-stable.json",
        company="Renamed Example",
        title="Refreshed Role",
        score=95,
    )

    assert state_for_opportunity(refreshed, load_state_payload(path)) == "REVIEWED"


def test_dismissed_omitted_from_default_radar(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-dismissed.json", state="DISMISSED", path=path)
    payload = load_state_payload(path)

    radar = render_operator_radar(
        [
            opportunity("silver-new.json", title="Visible"),
            opportunity("silver-dismissed.json", title="Hidden"),
        ],
        payload,
    )

    assert "Visible" in radar
    assert "Hidden" not in radar
    assert "## DISMISSED" not in radar


def test_dismissed_included_in_explicit_full_radar(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-dismissed.json", state="DISMISSED", path=path)

    radar = render_operator_radar(
        [opportunity("silver-dismissed.json", title="Hidden")],
        load_state_payload(path),
        include_dismissed=True,
    )

    assert "## DISMISSED" in radar
    assert "Hidden" in radar


def test_interested_is_prioritized_after_new_and_before_reviewed(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-interested.json", state="INTERESTED", path=path)
    set_operator_state(source_file="silver-reviewed.json", state="REVIEWED", path=path)

    radar = render_operator_radar(
        [
            opportunity("silver-reviewed.json", title="Reviewed", score=100),
            opportunity("silver-interested.json", title="Interested", score=10),
            opportunity("silver-new.json", title="New", score=50),
        ],
        load_state_payload(path),
    )

    assert radar.index("## NEW") < radar.index("New")
    assert radar.index("New") < radar.index("## INTERESTED")
    assert radar.index("Interested") < radar.index("## REVIEWED")
    assert radar.index("Reviewed") > radar.index("## REVIEWED")


def test_deterministic_sorting_within_state_and_recommendation():
    opportunities = [
        opportunity("c.json", company="Beta", title="B", score=80),
        opportunity("b.json", company="Alpha", title="Z", score=80),
        opportunity("a.json", company="Alpha", title="A", score=90),
    ]

    text = format_state_rows(list_operator_states_from_rows(opportunities))

    assert text.index("a.json") < text.index("b.json") < text.index("c.json")


def test_malformed_state_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "operator_state.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        set_operator_state(source_file="silver-a.json", state="INTERESTED", path=path)

    assert path.read_text(encoding="utf-8") == "{broken"


def test_atomic_state_write_failure_preserves_existing_file(tmp_path, monkeypatch):
    from src.career_intelligence import operator_state

    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-a.json", state="NEW", path=path)
    before = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(operator_state.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        set_operator_state(source_file="silver-a.json", state="DISMISSED", path=path)

    assert path.read_bytes() == before


def test_operator_state_does_not_modify_opportunities_schema(tmp_path):
    opportunities_path = tmp_path / "opportunities.json"
    opportunities_path.write_text(
        json.dumps([opportunity("silver-a.json")], indent=2) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-a.json", state="INTERESTED", path=state_path)

    rows = list_operator_states(
        opportunities_path=opportunities_path,
        state_path=state_path,
    )

    persisted = json.loads(opportunities_path.read_text(encoding="utf-8"))
    assert set(persisted[0]) == RESULT_FIELDS - {"explanation"}
    assert rows[0]["operator_state"] == "INTERESTED"


def test_operator_state_counts_include_dismissed_current_opportunities(tmp_path):
    path = tmp_path / "operator_state.json"
    set_operator_state(source_file="silver-dismissed.json", state="DISMISSED", path=path)

    assert operator_state_counts(
        [opportunity("silver-new.json"), opportunity("silver-dismissed.json")],
        load_state_payload(path),
    ) == {
        "NEW": 1,
        "REVIEWED": 0,
        "INTERESTED": 0,
        "DISMISSED": 1,
    }


def test_cli_set_and_list_commands_share_state_file(tmp_path, capsys):
    from src.career_intelligence import operator_state

    opportunities_path = tmp_path / "opportunities.json"
    opportunities_path.write_text(
        json.dumps([opportunity("silver-a.json", title="Listed Role")]) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "operator_state.json"

    set_exit = operator_state.main(
        [
            "--state-file",
            str(state_path),
            "set",
            "--source-file",
            "silver-a.json",
            "--state",
            "INTERESTED",
        ]
    )
    list_exit = operator_state.main(
        [
            "--state-file",
            str(state_path),
            "list",
            "--opportunities",
            str(opportunities_path),
        ]
    )

    output = capsys.readouterr().out
    assert set_exit == 0
    assert list_exit == 0
    assert "silver-a.json: INTERESTED" in output
    assert "INTERESTED | EXPLORE | 70 | Example | Listed Role | silver-a.json" in output


def test_state_for_missing_opportunity_survives_listing(tmp_path):
    opportunities_path = tmp_path / "opportunities.json"
    opportunities_path.write_text(
        json.dumps([opportunity("current.json")]) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "operator_state.json"
    set_operator_state(source_file="missing-today.json", state="REVIEWED", path=state_path)

    list_operator_states(opportunities_path=opportunities_path, state_path=state_path)

    payload = load_state_payload(state_path)
    assert payload["states"]["missing-today.json"]["state"] == "REVIEWED"


def list_operator_states_from_rows(opportunities):
    payload = {"schema_version": 1, "states": {}}
    return opportunities_with_state(opportunities, payload)
