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

Architecture and data models: **[PLAN.html](PLAN.html)** (reference). **Backlog and status:** [Jira epic FS-4](https://smithingsolutions.atlassian.net/browse/FS-4).

## Quick start

Requires Python 3.11+ (3.12 recommended). **First-time setup:** see **[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)** (venv, fixture secrets, common failures).

```bash
# One-command bootstrap (from repo root)
./scripts/setup-dev.sh
source .venv/bin/activate
pytest -q
```

On Debian/Ubuntu, system `pip` is blocked by [PEP 668](https://peps.python.org/pep-0668/) — always use the project `.venv`. If `.venv/bin/pip` fails with "required file not found", run `./scripts/setup-dev.sh --recreate-venv`.

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# See docs/LOCAL_SETUP.md for the fixture secrets vault (required for pytest)
```

With the venv activated, try the CLI:

```bash
# Validate fixture repo config
finalstrike validate-config --repo fixtures/sample-app

# Dry-run plan: merged config + acceptance criteria (no LLM yet)
finalstrike plan --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance-smoke.md --dry-run

# Live plan: LLM produces VerificationPlan JSON (needs configured llm.base_url + OPENAI_API_KEY)
finalstrike plan --repo fixtures/sample-app --acceptance fixtures/sample-app/acceptance-smoke.md --no-dry-run

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

See **[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)** for the full checklist (venv, secrets vault, `pytest` on `PATH`, troubleshooting).

- Run `./scripts/setup-dev.sh` after clone or when `.venv` is broken; `./scripts/setup-dev.sh --recreate-venv` forces a fresh virtualenv.
- Dependencies live in `.venv` (gitignored). Re-run setup or `pip install -e ".[dev]"` after pulling dependency changes.
- **Activate** the venv before `pytest -q` so subprocess-based tests find `pytest` on `PATH` (see LOCAL_SETUP.md).
- Tests require `fixtures/sample-app/.finalstrike/secrets.env` with an `OPENAI_API_KEY` entry for `doctor` (any value — real keys are fine). The setup script creates placeholders only when the file is missing.
- Default `pytest -q` uses committed cassettes (`tests/fixtures/cassette-smoke-v1/`). For live OpenAI/Ollama/etc., use gitignored `finalstrike.local.yaml` or `FINALSTRIKE_LLM_*` in secrets — not committed `finalstrike.yaml`.

## Project layout

```
finalstrike/          # Python package
fixtures/sample-app/  # Integration test target repo
schemas/            # Exported JSON schemas
tests/              # Unit and integration tests
PLAN.html           # Architecture reference (planning lives in Jira FS-4)
```

## Status

**P0–P6 are implemented** (foundation through Linux computer-use spike). The sample-app fixture is complete (`capabilities.yaml` has no planned items).

**Remaining MVP work** (P7 evidence, P8 HTML report, P9 Slack, P10 full orchestrator, P11/P12 platform ports, CI) is tracked in **[Jira epic FS-4](https://smithingsolutions.atlassian.net/browse/FS-4)**. Read the assigned story there before implementing — not `PLAN.html`.

Operational guardrails (cassettes, `doctor`, VM prerequisites): `docs/PHASE_GAPS.md`. Architecture reference: [PLAN.html](PLAN.html).

## License

FinalStrike is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0). You may use, modify, and distribute the software for **noncommercial purposes** at no charge (personal use, hobby projects, education, charities, government, and similar uses — see [LICENSE](LICENSE) for full terms).

**Commercial use** requires a separate paid license. Contact the project maintainer to obtain commercial terms.
