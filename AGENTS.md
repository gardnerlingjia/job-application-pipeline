# Repository Guidelines

## Project Structure & Module Organization

Python code lives in `src/`, with domain modules under `src/search_intelligence/` and `src/career_intelligence/`. Operator scripts and checks belong in `scripts/`. Keep tests in `tests/` and reusable inputs in `tests/fixtures/`. Database assets live in `db/`, configuration in `config/`, and the React/Vite UI in `frontend/control-center/`. Treat `docs/current/` as system truth, `docs/guides/` as procedures, `docs/reference/` as contracts, and `docs/archive/` as historical. Files in `exports/` and `runs/` are generated outputs.

## Build, Test, and Development Commands

- `python -m pip install -r requirements-dev.txt` installs runtime and test dependencies.
- `python -m pytest -q` runs the complete Python suite configured by `pytest.ini`.
- `ruff check .` applies the repository's conservative Python correctness checks.
- `git diff --check` detects whitespace errors before committing.
- `cd frontend/control-center && npm install && npm run dev` starts the UI on `127.0.0.1:5173` (Node 22+).
- `cd frontend/control-center && npm run build` type-checks and creates the production Vite build.

## Coding Style & Naming Conventions

Use four-space Python indentation, helpful type hints, and a 100-character line limit. Ruff targets Python 3.12 and checks critical `pycodestyle` and Pyflakes rules. Use `snake_case` for Python functions, modules, fixtures, and tests; use `PascalCase` for React components and `camelCase` for TypeScript functions and variables. Preserve established domain terminology and contract identifiers.

## Testing Guidelines

Pytest discovers `tests/test_*.py`. Add deterministic, fast tests for behavior changes and avoid live third-party requests; use local fixtures instead. Contract tests protect migrations, documentation anchors, and fail-closed behavior, so update them deliberately. No numeric coverage threshold is configured, but affected paths need focused regression coverage.

## Commit & Pull Request Guidelines

Never commit on `main`; use a branch such as `feature/origin-retry-policy`. History favors concise imperative subjects, sometimes prefixed by a work-item ID: `REL-004: make published releases visible in GitHub`. Stage explicit files, run tests and `git diff --check`, then inspect the staged diff. PRs should explain behavior, link the work item, list validation, and include screenshots for UI changes. Use squash merges and delete merged branches.

## Security & Configuration

Do not commit private candidate facts, credentials, or local environment files. Start sensitive configuration from templates such as `config/examples/private_candidate_fact_profile.template.json`. Keep acquisition defensive, auditable, and dry-run-first; reports and exports must not become authoritative pipeline inputs.
