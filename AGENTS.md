# AGENTS.md

## Cursor Cloud specific instructions

FinalStrike is a single Python package (`finalstrike`) exposing a Typer CLI. `fixtures/sample-app/` is the integration test target repo (not a separate product). Python 3.12 is used.

### Environment
- Dependencies are installed into a project virtualenv at `.venv` (gitignored). Activate with `source .venv/bin/activate` or prefix commands with `.venv/bin/` (e.g. `.venv/bin/pytest`, `.venv/bin/finalstrike`). The update script keeps `.venv` in sync.
- The test suite needs a gitignored local secrets vault at `fixtures/sample-app/.finalstrike/secrets.env` containing fake values `OPENAI_API_KEY=fixture-test-key-not-real` and `SLACK_BOT_TOKEN=fixture-slack-token`. Without it, 6 tests in `tests/test_p1_context.py` fail. The update script recreates it if missing.

### Lint / test / build / run
- Tests: `pytest -q` (config in `pyproject.toml` `testpaths = ["tests"]`). Run with the venv **activated** (`source .venv/bin/activate`) so `.venv/bin` is on `PATH`. The orchestrator's terminal-layer tests spawn a bare `pytest` subprocess, so invoking the suite as `.venv/bin/pytest` (without activation) leaves `pytest` off `PATH` and makes 3 tests in `tests/test_p3_runners.py` fail with `pytest: not found`.
- Lint: no linter is configured (dev deps are pytest only); there is nothing to run.
- Build/run the app: it is a CLI, not a server. Core commands: `finalstrike --version`, `finalstrike validate-config --repo fixtures/sample-app`, and `finalstrike plan --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance.md --dry-run`. See `README.md` Quick start.
- Regenerate JSON schemas: `python -m finalstrike.config.export_schemas` (writes to `schemas/`; output is committed and currently up to date).
- The `fixtures/sample-app` server (integration target) runs via `python -m sample_app.server 8080` from inside `fixtures/sample-app/` and serves `GET /health` -> `200 ok`.
