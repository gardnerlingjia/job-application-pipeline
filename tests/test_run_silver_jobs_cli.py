import pytest

import src.run_silver_jobs as run_silver_jobs
from src.run_silver_jobs import (
    build_parser,
    deduplicate_raw_job_ids,
    resolve_source_patterns,
)
from src.silver.repository import SilverJobRepository


def test_resolve_source_patterns_defaults_to_supported_sources() -> None:
    assert "enercity:%" in resolve_source_patterns(None)


def test_resolve_source_patterns_accepts_exact_enercity_source() -> None:
    assert resolve_source_patterns("enercity:discovery") == ["enercity:discovery"]


def test_resolve_source_patterns_accepts_enercity_family() -> None:
    assert resolve_source_patterns("enercity") == ["enercity:%"]


def test_ingestion_run_id_must_be_positive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--ingestion-run-id", "0"])

    assert exc_info.value.code == 2


def test_reprocess_raw_job_id_must_be_positive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--reprocess-raw-job-id", "0"])

    assert exc_info.value.code == 2


def test_deduplicate_raw_job_ids_preserves_order() -> None:
    assert deduplicate_raw_job_ids([2, 1, 2, 3, 1]) == [2, 1, 3]


def test_main_forwards_exact_source_and_ingestion_run(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRepository:
        def load_unprocessed_raw_jobs(
            self,
            limit: int,
            source_patterns: list[str],
            ingestion_run_id: int | None,
        ) -> list[dict]:
            captured.update(
                limit=limit,
                source_patterns=source_patterns,
                ingestion_run_id=ingestion_run_id,
            )
            return []

    monkeypatch.setattr(run_silver_jobs, "SilverJobRepository", FakeRepository)

    run_silver_jobs.main(
        [
            "--source",
            "computacenter:discovery",
            "--ingestion-run-id",
            "2596",
            "--limit",
            "3",
        ]
    )

    assert captured == {
        "limit": 3,
        "source_patterns": ["computacenter:discovery"],
        "ingestion_run_id": 2596,
    }


def test_main_reprocesses_explicit_raw_job_ids_with_source_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeRepository:
        def load_raw_jobs_by_ids(
            self,
            raw_job_ids: list[int],
            source_patterns: list[str] | None = None,
        ) -> list[dict]:
            captured.update(raw_job_ids=raw_job_ids, source_patterns=source_patterns)
            return []

    monkeypatch.setattr(run_silver_jobs, "SilverJobRepository", FakeRepository)

    with pytest.raises(SystemExit):
        run_silver_jobs.main(
            [
                "--source",
                "greenhouse:moia",
                "--reprocess-raw-job-id",
                "1",
                "--reprocess-raw-job-id",
                "2",
                "--reprocess-raw-job-id",
                "1",
            ]
        )

    assert captured == {
        "raw_job_ids": [1, 2],
        "source_patterns": ["greenhouse:moia"],
    }


def test_main_reprocess_rejects_ingestion_run_scope(monkeypatch) -> None:
    class FakeRepository:
        pass

    monkeypatch.setattr(run_silver_jobs, "SilverJobRepository", FakeRepository)

    with pytest.raises(SystemExit) as exc_info:
        run_silver_jobs.main(
            [
                "--ingestion-run-id",
                "17",
                "--reprocess-raw-job-id",
                "1",
            ]
        )

    assert str(exc_info.value) == (
        "--ingestion-run-id cannot be combined with --reprocess-raw-job-id"
    )


class RecordingCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[dict]:
        return []


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


def build_recording_repository() -> tuple[SilverJobRepository, RecordingCursor]:
    cursor = RecordingCursor()
    connection = RecordingConnection(cursor)
    repository = SilverJobRepository.__new__(SilverJobRepository)
    repository.get_connection = lambda: connection
    return repository, cursor


def test_repository_composes_source_and_ingestion_run_filters() -> None:
    repository, cursor = build_recording_repository()

    repository.load_unprocessed_raw_jobs(
        limit=3,
        source_patterns=["computacenter:discovery"],
        ingestion_run_id=2596,
    )

    assert "r.source_name = %s" in cursor.sql
    assert "r.ingestion_run_id = %s" in cursor.sql
    assert cursor.params == ("computacenter:discovery", 2596, 3)


def test_repository_preserves_source_only_selection() -> None:
    repository, cursor = build_recording_repository()

    repository.load_unprocessed_raw_jobs(
        limit=3,
        source_patterns=["computacenter:discovery"],
    )

    assert "r.source_name = %s" in cursor.sql
    assert "r.ingestion_run_id = %s" not in cursor.sql
    assert cursor.params == ("computacenter:discovery", 3)


def test_repository_loads_explicit_raw_job_ids_without_processed_filter() -> None:
    repository, cursor = build_recording_repository()

    repository.load_raw_jobs_by_ids(
        raw_job_ids=[1, 2],
        source_patterns=["greenhouse:moia"],
    )

    assert "r.id = ANY(%s::bigint[])" in cursor.sql
    assert "LEFT JOIN silver_jobs" not in cursor.sql
    assert "LEFT JOIN silver_processing_decisions" not in cursor.sql
    assert "r.source_name = %s" in cursor.sql
    assert cursor.params == ([1, 2], "greenhouse:moia")


def test_main_includes_employer_origin_with_strong_description_and_empty_matches(
    monkeypatch,
    capsys,
) -> None:
    raw_job = {
        "id": 8301,
        "source_name": "greenhouse:moia",
        "external_job_id": "71001",
        "source_url": "https://boards.greenhouse.io/moia/jobs",
        "raw_data": {
            "board_token": "moia",
            "job": {
                "id": 71001,
                "title": "Unsolicited Application - Business (all genders)",
                "absolute_url": "https://boards.greenhouse.io/moia/jobs/71001",
                "location": {"name": "Berlin"},
                "content": (
                    "This employer-origin vacancy invites candidates to submit an "
                    "unsolicited application for future teams in Berlin."
                ),
                "first_published": "2026-09-01T10:00:00Z",
            },
        },
    }
    decisions: list[dict] = []
    writes: list[dict] = []

    class FakeRepository:
        def load_unprocessed_raw_jobs(self, **kwargs):
            return [raw_job]

        def record_processing_decision(self, **kwargs) -> None:
            decisions.append(kwargs)

    monkeypatch.setattr(run_silver_jobs, "SilverJobRepository", FakeRepository)

    def fake_writer(repo, *, silver_job, raw_job) -> int:
        writes.append(silver_job)
        return 8801

    monkeypatch.setattr(
        run_silver_jobs,
        "write_silver_job_with_successfactors_locations",
        fake_writer,
    )

    run_silver_jobs.main(["--source", "greenhouse:moia"])

    assert writes[0]["title"] == "Unsolicited Application - Business (all genders)"
    assert decisions == [
        {
            "raw_job_id": 8301,
            "decision": "included",
            "reason": "relevant_for_silver",
            "role_matches": [],
            "skill_matches": [],
            "accessibility_matches": ["berlin"],
        }
    ]
    assert "Silver job written: raw_job_id=8301" in capsys.readouterr().out


def test_main_reprocess_updates_previously_skipped_raw_job(monkeypatch, capsys) -> None:
    raw_job = {
        "id": 1,
        "source_name": "greenhouse:moia",
        "external_job_id": "71001",
        "source_url": "https://boards.greenhouse.io/moia/jobs",
        "raw_data": {
            "board_token": "moia",
            "job": {
                "id": 71001,
                "title": "Unsolicited Application - Business (all genders)",
                "absolute_url": "https://boards.greenhouse.io/moia/jobs/71001",
                "location": {"name": "Berlin"},
                "content": (
                    "This employer-origin vacancy invites candidates to submit an "
                    "unsolicited application for future teams in Berlin."
                ),
            },
        },
    }
    decisions: list[dict] = []
    writes: list[dict] = []

    class FakeRepository:
        def load_unprocessed_raw_jobs(self, **kwargs):
            raise AssertionError("explicit reprocess must not use unprocessed selection")

        def load_raw_jobs_by_ids(self, **kwargs):
            assert kwargs == {
                "raw_job_ids": [1],
                "source_patterns": ["greenhouse:moia"],
            }
            return [raw_job]

        def record_processing_decision(self, **kwargs) -> None:
            decisions.append(kwargs)

    monkeypatch.setattr(run_silver_jobs, "SilverJobRepository", FakeRepository)

    def fake_writer(repo, *, silver_job, raw_job) -> int:
        writes.append(silver_job)
        return 8801

    monkeypatch.setattr(
        run_silver_jobs,
        "write_silver_job_with_successfactors_locations",
        fake_writer,
    )

    run_silver_jobs.main(
        [
            "--source",
            "greenhouse:moia",
            "--reprocess-raw-job-id",
            "1",
        ]
    )

    assert writes[0]["raw_job_id"] == 1
    assert decisions[0]["decision"] == "included"
    assert decisions[0]["role_matches"] == []
    assert decisions[0]["skill_matches"] == []
    output = capsys.readouterr().out
    assert "Explicit Silver reprocess requested for raw_job_id(s): 1" in output
    assert "Transformed raw jobs: 1" in output
