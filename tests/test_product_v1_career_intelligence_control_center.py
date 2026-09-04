from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from scripts import run_product_v1_control_center as server


FRONTEND = Path("frontend/control-center/src/OperatorWorkspace.tsx")
WORKSPACE = Path("frontend/control-center/src/DemoApplicationWorkspace.tsx")
BRIDGE = Path("frontend/control-center/src/ApplicationWorkspaceEventBridge.tsx")


def _handler(path: str, payload: object | None = None):
    handler = object.__new__(server.ProductV1Handler)
    handler.path = path
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    handler.headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    handler.rfile = BytesIO(body)
    responses: list[tuple[dict[str, object], object]] = []

    def send_json(payload: dict[str, object], *, status=200) -> None:
        responses.append((payload, status))

    handler._send_json = send_json  # type: ignore[method-assign]
    return handler, responses


def test_product_payload_merges_career_intelligence_read_model(monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(
        server._base,
        "load_product_v1_payload",
        lambda: {
            "summary": {},
            "boundaries": {},
            "job_readiness": [{"silver_job_id": 42, "title": "Product row"}],
            "top_jobs": [{"silver_job_id": 42, "title": "Product row"}],
        },
    )
    monkeypatch.setattr(server, "_merge_structured_job_locations", lambda payload, rows: payload)
    monkeypatch.setattr(server, "_merge_observed_opportunities", lambda payload, rows: payload)
    monkeypatch.setattr(
        server,
        "_merge_job_review_labels",
        lambda payload, rows, capture_available: payload,
    )
    monkeypatch.setattr(server, "_merge_demo_origin_projection", lambda payload: payload)

    def load_career(payload):
        calls.append(payload)
        return {
            "available": True,
            "records": [],
            "by_silver_job_id": {},
            "summary": {"opportunity_count": 0, "joined_job_count": 0},
        }

    monkeypatch.setattr(server, "load_career_intelligence_control_center", load_career)
    monkeypatch.setattr(
        server.DatabaseConfig,
        "from_environment",
        lambda: _DatabaseConfig(),
    )
    monkeypatch.setattr(
        server.psycopg,
        "connect",
        lambda *args, **kwargs: _EmptyConnection(),
    )

    payload = server.load_product_v1_payload()

    assert calls and calls[0]["job_readiness"][0]["silver_job_id"] == 42
    assert payload["career_intelligence"]["available"] is True
    assert payload["summary"]["career_intelligence_opportunity_count"] == 0
    assert payload["boundaries"]["career_intelligence_does_not_automate_applications"] is True


def test_career_operator_state_post_route_calls_existing_persistence(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def set_state(*, source_file: str, state: str):
        calls.append((source_file, state))
        return {"states": {source_file: {"state": state}}}

    monkeypatch.setattr(server, "set_operator_state", set_state)
    handler, responses = _handler(
        server.CAREER_OPERATOR_STATE_ACTION_PATH,
        {"source_file": "silver-a.json", "state": "INTERESTED"},
    )

    handler.do_POST()

    assert calls == [("silver-a.json", "INTERESTED")]
    assert responses[0][0]["status"] == "applied"
    assert responses[0][0]["database_writes"] == 0
    assert responses[0][0]["product_authority"] is False
    assert int(responses[0][1]) == 200


def test_career_operator_state_post_rejects_invalid_state(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(server, "set_operator_state", lambda **kwargs: calls.append(1))
    handler, responses = _handler(
        server.CAREER_OPERATOR_STATE_ACTION_PATH,
        {"source_file": "silver-a.json", "state": "MAYBE"},
    )

    handler.do_POST()

    assert calls == []
    assert responses[0][0]["status"] == "blocked"
    assert "invalid operator state" in responses[0][0]["reason"]
    assert int(responses[0][1]) == 400


def test_frontend_renders_career_intelligence_controls_and_fields() -> None:
    text = FRONTEND.read_text(encoding="utf-8")

    assert 'type View = "overview" | "jobs" | "career"' in text
    assert "function CareerIntelligence" in text
    assert "opportunity_score" in text
    assert "recommendation" in text
    assert "operator_state" in text
    assert "career_lane_label" in text
    assert "constraint_action" in text
    assert "key_matched_capabilities" in text
    assert "network_access" in text
    assert "relationship_level" in text
    assert "minimumScore" in text
    assert "setOperatorState" in text
    assert "careerSort" in text


def test_frontend_workspace_bridge_accepts_career_selected_job() -> None:
    workspace = WORKSPACE.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")

    assert "discovery_job_readiness" in workspace
    assert "setSelectedId(detail.silverJobId)" in workspace
    assert "application-workspace?silver_job_id=${selectedId}" in workspace
    assert "generate_review_draft" in workspace
    assert "if (customEvent.detail?.silverJobId != null) return;" in bridge


class _EmptyCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return {"present": False}

    def fetchall(self):
        return []


class _EmptyConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return _EmptyCursor()


class _DatabaseConfig:
    def dsn(self):
        return "postgresql://example"
