# FinalStrike

A standalone Python orchestrator that mirrors **only the testing workflow** of Cursor cloud agents — environment bootstrap, build/lint gates, terminal tests, API checks, and computer-use UI verification — running on self-hosted GUI VMs and producing Cursor-parity evidence bundles.

## Architecture

FinalStrike is an **orchestrator + evidence recorder**, not a test framework. It runs the same commands a Cursor cloud agent would run, uses an LLM to translate acceptance criteria into a verification plan, drives the UI like computer-use does, and packages proof.

```
CLI → Config Loader → AC Parser → LLM Test Planner
                          ↓
    Env Orchestrator → Build/Lint → Terminal Tests → API Checks → Computer-Use
                          ↓
              Evidence Recorder → Gap Analyzer → HTML Report
```

### Components

| Component | Responsibility |
|-----------|----------------|
| **CLI** | Typer entrypoints (`validate-config`, `plan`, `run`, `env`) |
| **Config Loader** | `finalstrike.yaml`, `AGENTS.md`, `.cursor/environment.json`, secrets vault |
| **LLM Test Planner** | Acceptance criteria → structured `VerificationPlan` via OpenAI-compatible API |
| **Env Orchestrator** | `environment.json` install/terminals, health-check polling |
| **Command Runners** | Build/lint, terminal tests (pytest first), HTTP API checks |
| **Computer-Use Executor** | Screenshot + a11y → LLM action → OS input → evidence |
| **Evidence Recorder** | Desktop video, per-step screenshots, `RunResult` JSON |
| **Reporters** | HTML report (primary), Slack bot (deferred) |

Full design, data models, and phased implementation plan: **[PLAN.html](PLAN.html)**.

## Quick start

Requires Python 3.11+ (3.12 recommended). On Debian/Ubuntu-based systems, install into a project virtualenv — system `pip` is blocked by [PEP 668](https://peps.python.org/pep-0668/).

```bash
# Create and activate a virtualenv (once per machine)
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Run the test suite (needs fixture secrets; see Development below)
pytest -q
```

With the venv activated, try the CLI:

```bash
# Validate fixture repo config
finalstrike validate-config --repo fixtures/sample-app

# Dry-run plan: merged config + acceptance criteria (no LLM yet)
finalstrike plan --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance-smoke.md --dry-run

# Start fixture services (install + terminals + health check)
finalstrike env up --repo fixtures/sample-app
finalstrike env down --repo fixtures/sample-app

# Run build + terminal + API layers; prints RunResult JSON
finalstrike run --repo fixtures/sample-app \
  --acceptance fixtures/sample-app/acceptance-smoke.md \
  --layers env,build,terminal,api

# Accept criteria from stdin (e.g. piped PR body)
echo "## AC\n- item" | finalstrike plan --repo fixtures/sample-app --acceptance-stdin --dry-run

# Export JSON schemas from Pydantic models
python -m finalstrike.config.export_schemas
```

Without activating the venv, prefix commands with `.venv/bin/` (e.g. `.venv/bin/finalstrike`, `.venv/bin/pytest`).

### Development

- Dependencies live in `.venv` (gitignored). Re-run `pip install -e ".[dev]"` after pulling dependency changes.
- If `python3 -m venv` fails, install the venv package for your Python version (e.g. `sudo apt install python3.12-venv`).
- Tests expect a local secrets vault at `fixtures/sample-app/.finalstrike/secrets.env` (gitignored):

  ```
  OPENAI_API_KEY=fixture-test-key-not-real
  SLACK_BOT_TOKEN=fixture-slack-token
  ```

  Without it, 6 tests in `tests/test_p1_context.py` fail.

## Project layout

```
finalstrike/          # Python package
fixtures/sample-app/  # Integration test target repo
schemas/            # Exported JSON schemas
tests/              # Unit and integration tests
PLAN.html           # Implementation plan
```

## Status

**Phase 0 (P0)** — project foundation: package scaffold, Pydantic models, JSON schemas, `validate-config` CLI, and fixture repo.

**Phase 1 (P1)** — config and context loading: `finalstrike.yaml`, `AGENTS.md`, `.cursor/environment.json`, secrets vault, acceptance criteria, and `finalstrike plan --dry-run`.

**Phase 2 (P2)** — environment orchestrator: `finalstrike env up/down`, install/terminals from `environment.json`, HTTP health polling, process teardown.

**Phase 3 (P3)** — build/lint and terminal test runners: `finalstrike run --layers`, pytest output parsing, `RunResult` JSON written under `.finalstrike/runs/`.

**Gap guardrails** — `finalstrike doctor`, `docs/PHASE_GAPS.md`, `acceptance-smoke.md` / `acceptance-full.md`, and `capabilities.yaml` keep P4+ prerequisites visible.

See [PLAN.html](PLAN.html) section 8 for the full phase roadmap.

## License

FinalStrike is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0). You may use, modify, and distribute the software for **noncommercial purposes** at no charge (personal use, hobby projects, education, charities, government, and similar uses — see [LICENSE](LICENSE) for full terms).

**Commercial use** requires a separate paid license. Contact the project maintainer to obtain commercial terms.
