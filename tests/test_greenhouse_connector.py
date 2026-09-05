from __future__ import annotations

from src.connectors.base import SearchProfile, SearchTerm
from src.connectors.greenhouse import GreenhouseConnector


class FakeGreenhouseResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Senior Technical Program Manager",
                    "absolute_url": "https://job-boards.greenhouse.io/moia/jobs/12345",
                    "location": {"name": "Berlin"},
                    "content": "Lead technical mobility programs with data and robotics teams.",
                }
            ]
        }


def test_greenhouse_connector_fetches_board_jobs_without_live_network(monkeypatch) -> None:
    requested = []

    def fake_get(url: str, *, timeout: int):
        requested.append((url, timeout))
        return FakeGreenhouseResponse()

    monkeypatch.setattr("src.connectors.greenhouse.requests.get", fake_get)
    connector = GreenhouseConnector(board_token="moia")

    records, source_url = connector.fetch_jobs(
        SearchProfile(
            id=1,
            profile_name="moia_controlled_hannover_precision",
            source_name="greenhouse:moia",
            search_location="Berlin",
            search_radius_km=50,
            offer_type=None,
            page_size=25,
        ),
        SearchTerm(search_term="data", id=1),
    )

    assert requested == [
        ("https://boards-api.greenhouse.io/v1/boards/moia/jobs", 30)
    ]
    assert source_url == "https://boards-api.greenhouse.io/v1/boards/moia/jobs"
    assert len(records) == 1
    assert records[0].source_name == "greenhouse:moia"
    assert records[0].external_job_id == "12345"
    assert records[0].source_url == "https://job-boards.greenhouse.io/moia/jobs/12345"
    assert records[0].raw_data["board_token"] == "moia"
