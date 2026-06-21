# AGENTS.md

## Cursor Cloud specific instructions

FinalStrike is a single Python package (`finalstrike`) exposing a Typer CLI. `fixtures/sample-app/` is the integration test target repo (not a separate product). Python 3.12 is used.

### Environment
- Dependencies are installed into a project virtualenv at `.venv` (gitignored). Activate with `source .venv/bin/activate` or prefix commands with `.venv/bin/` (e.g. `.venv/bin/pytest`, `.venv/bin/finalstrike`). The update script keeps `.venv` in sync.
- The test suite needs a gitignored local secrets vault at `fixtures/sample-app/.finalstrike/secrets.env` containing fake values `OPENAI_API_KEY=fixture-test-key-not-real` and `SLACK_BOT_TOKEN=fixture-slack-token`. Without it, 6 tests in `tests/test_p1_context.py` fail. The update script recreates it if missing.

### Phase gaps (P5+)

Before starting P6+, run `finalstrike doctor --repo fixtures/sample-app` and read
`docs/PHASE_GAPS.md`. The fixture uses `acceptance-smoke.md` for P0–P5 work and
`acceptance-full.md` for future P6 demos; `capabilities.yaml` tracks what is
implemented vs planned.

### Lint / test / build / run
- Tests: `pytest -q` (config in `pyproject.toml` `testpaths = ["tests"]`). Run with the venv **activated** (`source .venv/bin/activate`) so `.venv/bin` is on `PATH`. The orchestrator's terminal-layer tests spawn a bare `pytest` subprocess, so invoking the suite as `.venv/bin/pytest` (without activation) leaves `pytest` off `PATH` and makes 3 tests in `tests/test_p3_runners.py` fail with `pytest: not found`.
- Lint: no linter is configured (dev deps are pytest only); there is nothing to run.
- Build/run the app: it is a CLI, not a server. Core commands: `finalstrike --version`, `finalstrike doctor --repo fixtures/sample-app`, `finalstrike validate-config --repo fixtures/sample-app`, `finalstrike plan --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance-smoke.md --dry-run`, `finalstrike plan ... --no-dry-run` (live LLM planner), and `finalstrike run --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance-smoke.md --layers api` (with services up). See `README.md` Quick start.
- Regenerate JSON schemas: `python -m finalstrike.config.export_schemas` (writes to `schemas/`; output is committed and currently up to date).
- The `fixtures/sample-app` server (integration target) runs via `python -m sample_app.server 8080` from inside `fixtures/sample-app/` and serves `GET /health` -> `200 ok`.

### Live LLM testing

- **Config** — `llm.base_url` and `llm.model` come from `finalstrike.yaml` (per `--repo`). `OPENAI_API_KEY` comes from that repo's `.finalstrike/secrets.env` (or process env when no vault key is set). The transport is a single OpenAI-compatible client (`finalstrike/providers/openai_compat.py`), so any gateway works by setting `base_url`/`model` (OpenAI, OpenRouter, LiteLLM, local Ollama, etc.). The committed fixture defaults to a local Ollama example (`http://localhost:11434/v1`, `llama3`).
- **Default CI** — `pytest -q` does not call a live LLM. Planner behavior is covered by committed cassettes in `tests/llm_recordings/` (`tests/test_p5_planner_integration.py`, marker `@pytest.mark.llm_cassette`). No real API key is required for the default suite.
- **Optional live tests** — `pytest -m requires_live_llm` runs structural planner checks against whatever endpoint is configured for the fixture repo. Gating uses `finalstrike.providers.live.assess_live_llm()` (probes `GET {base_url}/models` with the resolved key). `finalstrike doctor --repo …` reports the same as **Live LLM (P5)**. Refresh cassettes with `FINALSTRIKE_RECORD_LLM=1 pytest -m requires_live_llm tests/test_p5_planner_live.py::test_record_smoke_planner_cassette -q`. See `docs/PHASE_GAPS.md` and `tests/llm_recordings/README.md`.
- **GOTCHA (fixture vault vs live API)** — the secrets vault OVERRIDES process env: `load_repo_context(..., inject_secrets=True)` does `os.environ.update(secrets)`. Running live through `fixtures/sample-app` therefore uses the vault's fake `OPENAI_API_KEY` and will 401 against a remote API, even when a real `OPENAI_API_KEY` is exported. Do not change the committed fixture vault — `tests/test_p1_context.py::test_load_secrets_from_sample_app` asserts `OPENAI_API_KEY == "fixture-test-key-not-real"`. For live external-API runs, use a separate `--repo` (e.g. a throwaway dir under `/tmp`) with its own `finalstrike.yaml` (`llm:` block) and `.finalstrike/secrets.env` (real key).
- **GOTCHA (request params)** — some OpenAI models reject `max_tokens` and require `max_completion_tokens` instead. The current provider adapter does not set a token limit; if you hit HTTP 400 on that parameter, update `openai_compat.py` accordingly (reasoning models may also need a generous budget and non-default temperature).

### Pull requests

Use the structure in [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) for every PR. Fill in all four sections:

1. **What was changed** — brief description of what changed.
2. **Why we changed it** — motivation, problem solved, or trade-off.
3. **Validation** — tests and checks you ran (commands, scenarios, expected outcomes). Default suite: `source .venv/bin/activate && pytest -q`.
4. **How to test locally** — step-by-step instructions for reviewers, including setup, commands, and what success looks like.

Cloud agents should follow the same sections when creating or updating PR descriptions.
