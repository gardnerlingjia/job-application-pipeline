"""Daily Career Intelligence refresh from the existing Silver layer."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import AbstractContextManager
from datetime import UTC, datetime
import errno
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

from src.career_intelligence.batch import RECOMMENDATION_GROUPS
from src.career_intelligence.ingest_silver import process_silver, positive_integer
from src.career_intelligence.operator_state import (
    DEFAULT_STATE_PATH,
    DISPLAY_STATES,
    load_state_payload,
    operator_state_counts,
    write_operator_radar,
)


DEFAULT_RUNTIME_DIR = Path(".runtime/career_intelligence")
DEFAULT_LOCK_STALE_SECONDS = 24 * 60 * 60


class DailyRunAlreadyActive(RuntimeError):
    """Raised when another local daily run holds the lock."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _pid_is_active(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class DailyRunLock(AbstractContextManager["DailyRunLock"]):
    def __init__(
        self,
        path: Path,
        *,
        stale_seconds: int = DEFAULT_LOCK_STALE_SECONDS,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.now = now
        self.acquired = False

    def __enter__(self) -> "DailyRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "created_at_utc": _iso(self.now()),
            "command": "python -m src.career_intelligence.daily",
        }
        content = json.dumps(payload, sort_keys=True) + "\n"

        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                self._clear_if_stale()
                try:
                    fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                except FileExistsError as exc:
                    raise DailyRunAlreadyActive(
                        f"Career Intelligence daily run already active: {self.path}"
                    ) from exc

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return self

    def _clear_if_stale(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            pid = int(payload.get("pid"))
            created_at = str(payload.get("created_at_utc"))
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            self.path.unlink(missing_ok=True)
            return

        age = (self.now() - created).total_seconds()
        if age >= self.stale_seconds or not _pid_is_active(pid):
            self.path.unlink(missing_ok=True)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.acquired:
            return None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
        return None


def log_path(runtime_dir: Path, started_at: datetime) -> Path:
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return runtime_dir / "logs" / f"daily_{stamp}.log"


def recommendation_counts(opportunities: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        item.get("recommendation")
        for item in opportunities
        if isinstance(item, dict)
    )
    return {group: counts.get(group, 0) for group in RECOMMENDATION_GROUPS}


def summary_lines(
    summary: dict[str, Any],
    *,
    exit_status: int,
    state_path: Path = DEFAULT_STATE_PATH,
) -> list[str]:
    errors = summary.get("errors", [])
    opportunities = summary.get("opportunities", [])
    opportunity_rows = opportunities if isinstance(opportunities, list) else []
    state_payload = load_state_payload(state_path)
    rec_counts = recommendation_counts(opportunity_rows)
    state_counts = operator_state_counts(opportunity_rows, state_payload)
    lines = [
        "Career Intelligence daily refresh",
        f"Silver jobs loaded: {int(summary.get('loaded', 0))}",
        f"Converted: {int(summary.get('converted', 0))}",
        f"Newly assessed: {int(summary.get('processed', 0))}",
        f"Already known/skipped: {int(summary.get('skipped_existing', 0))}",
        f"Errors: {len(errors) if isinstance(errors, list) else 0}",
    ]
    lines.extend(f"{group}: {rec_counts[group]}" for group in RECOMMENDATION_GROUPS)
    lines.extend(f"{state}: {state_counts[state]}" for state in DISPLAY_STATES)
    lines.append(f"Exit status: {exit_status}")
    return lines


def _log_summary(
    path: Path,
    *,
    started_at: datetime,
    finished_at: datetime,
    lines: list[str],
    errors: object,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_errors: list[dict[str, str]] = []
    if isinstance(errors, list):
        for error in errors:
            if not isinstance(error, dict):
                continue
            safe_errors.append(
                {
                    "record": str(error.get("record", "unknown")),
                    "error": str(error.get("error", "")),
                }
            )
    payload = {
        "started_at_utc": _iso(started_at),
        "finished_at_utc": _iso(finished_at),
        "exit_status": int(lines[-1].split(": ")[1]),
        "summary": lines[:-1],
        "errors": safe_errors,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_daily(
    *,
    results: Path = Path("jobs/results"),
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    state_path: Path = DEFAULT_STATE_PATH,
    limit: int = 100,
    source: str | None = None,
    ingestion: Callable[..., dict[str, Any]] | None = None,
    stale_lock_seconds: int = DEFAULT_LOCK_STALE_SECONDS,
) -> tuple[int, list[str], Path]:
    started_at = utc_now()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    current_log = log_path(runtime_dir, started_at)
    lock_file = runtime_dir / "daily.lock"
    ingestion = ingestion or process_silver

    try:
        with DailyRunLock(lock_file, stale_seconds=stale_lock_seconds):
            load_state_payload(state_path)
            summary = ingestion(results=results, limit=limit, source=source)
            opportunities = summary.get("opportunities", [])
            if not isinstance(opportunities, list):
                raise ValueError("Silver ingestion did not return opportunities")
            write_operator_radar(
                opportunities=opportunities,
                results=results,
                state_path=state_path,
            )
            errors = summary.get("errors", [])
            exit_status = 1 if isinstance(errors, list) and errors else 0
            lines = summary_lines(
                summary,
                exit_status=exit_status,
                state_path=state_path,
            )
            _log_summary(
                current_log,
                started_at=started_at,
                finished_at=utc_now(),
                lines=lines,
                errors=errors,
            )
            return exit_status, lines, current_log
    except DailyRunAlreadyActive as exc:
        lines = [
            "Career Intelligence daily refresh",
            f"Errors: 1",
            f"ERROR: {exc}",
            "Exit status: 2",
        ]
        _log_summary(
            current_log,
            started_at=started_at,
            finished_at=utc_now(),
            lines=lines,
            errors=[{"record": "daily.lock", "error": str(exc)}],
        )
        return 2, lines, current_log
    except Exception as exc:
        lines = [
            "Career Intelligence daily refresh",
            f"Errors: 1",
            f"ERROR: {exc}",
            "Exit status: 1",
        ]
        _log_summary(
            current_log,
            started_at=started_at,
            finished_at=utc_now(),
            lines=lines,
            errors=[{"record": "daily", "error": str(exc)}],
        )
        return 1, lines, current_log


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the daily Career Intelligence refresh from Silver."
    )
    parser.add_argument(
        "--source",
        help=(
            "Optional exact source name or source-family filter, "
            "e.g. personio:target or personio."
        ),
    )
    parser.add_argument("--limit", type=positive_integer, default=100)
    parser.add_argument("--results", type=Path, default=Path("jobs/results"))
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    exit_status, lines, path = run_daily(
        results=args.results,
        runtime_dir=args.runtime_dir,
        state_path=args.state_file,
        limit=args.limit,
        source=args.source,
    )
    for line in lines:
        print(line)
    print(f"Log: {path}")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
