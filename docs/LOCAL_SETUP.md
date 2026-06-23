# Local development setup

Follow this guide once per machine (or after pulling dependency changes) so
`pytest -q` and `finalstrike doctor` do not fail due to environment misconfiguration.

## Quick setup (recommended)

From the repository root:

```bash
./scripts/setup-dev.sh
source .venv/bin/activate
pytest -q
```

To **replace a broken `.venv`** (e.g. `pip: cannot execute: required file not found`
after moving the repo or upgrading Python):

```bash
./scripts/setup-dev.sh --recreate-venv
source .venv/bin/activate
pytest -q
```

## What the default test suite needs

| Requirement | Required for `pytest -q`? | Notes |
|-------------|---------------------------|-------|
| Python 3.11+ (3.12 recommended) | Yes | `python3 --version` |
| Project virtualenv at `.venv/` | Yes | Never use system `pip` on Debian/Ubuntu ([PEP 668](https://peps.python.org/pep-0668/)) |
| `pip install -e ".[dev]"` into `.venv` | Yes | Installs `finalstrike`, `pytest`, `mss`, etc. |
| Fixture secrets vault | For `doctor` only | `fixtures/sample-app/.finalstrike/secrets.env` must **exist** with `OPENAI_API_KEY` set (any value — real OpenAI key is fine) |
| `pytest` on `PATH` when running tests | Yes | **Activate** `.venv` before `pytest -q`, or use `.venv/bin/pytest` |
| Live LLM (Ollama, OpenAI, …) | No | Skipped; cassettes cover planner/computer-use in CI |
| Chrome/Chromium, `xdotool`, GUI display | No | Only for optional `@requires_platform_tools` tests |
| `ffmpeg` | No | Only for optional platform-tool tests |

**Expected default result:** `pytest -q` → all tests pass except a few **skipped**
(live LLM / platform tools when not configured). Example: `120 passed, 4 skipped`.

## Manual setup (step by step)

### 1. System packages (Debian/Ubuntu, once)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
# Match your Python minor version if needed, e.g.:
# sudo apt install -y python3.12-venv
```

### 2. Virtualenv — do not reuse a copied or stale `.venv`

```bash
cd /path/to/FinalStrike

# If .venv is missing OR pip/python inside it is broken:
rm -rf .venv
python3 -m venv .venv
```

Verify:

```bash
.venv/bin/python --version
.venv/bin/pip --version
```

If `pip` still fails, the venv was not created cleanly — delete `.venv` and retry
after installing `python3-venv`.

### 3. Install the package and dev dependencies

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Without activating:

```bash
.venv/bin/pip install -e ".[dev]"
```

### 4. Fixture secrets vault (`doctor` and live CLI)

`finalstrike doctor --repo fixtures/sample-app` expects a secrets file to exist.
The default test suite does **not** require specific fake key values — you may use
your real OpenAI (or other provider) API key here.

```bash
mkdir -p fixtures/sample-app/.finalstrike
cat > fixtures/sample-app/.finalstrike/secrets.env <<'EOF'
OPENAI_API_KEY=your-real-or-placeholder-key
SLACK_BOT_TOKEN=fixture-slack-token
EOF
```

`./scripts/setup-dev.sh` creates this file with placeholder values only when it is
missing; it never overwrites an existing vault.

### 5. Configure your LLM provider (optional — for live `plan` / `computer-use`)

**Do not edit committed `finalstrike.yaml` for provider experiments.** Use one of:

**A. Gitignored `finalstrike.local.yaml` (recommended)**

```bash
cp fixtures/sample-app/finalstrike.local.yaml.example \
   fixtures/sample-app/finalstrike.local.yaml
# Edit llm.base_url and llm.model — file is gitignored
```

**B. Keys in `.finalstrike/secrets.env`**

```bash
OPENAI_API_KEY=your-real-key
FINALSTRIKE_LLM_BASE_URL=[REDACTED]
FINALSTRIKE_LLM_MODEL=gpt-4o
```

Precedence: committed `finalstrike.yaml` → `finalstrike.local.yaml` →
`FINALSTRIKE_*` keys in secrets/env (highest).

Deterministic cassette tests use `tests/fixtures/cassette-smoke-v1/` only.

Optional `computer_use.llm` in either file overrides the vision/action model.

### 6. Run tests the intended way

**Activate the venv** (recommended):

```bash
source .venv/bin/activate
pytest -q
```

Some orchestrator tests spawn a bare `pytest` subprocess. If the venv is not
activated and `pytest` is not on your shell `PATH`, **3 tests** in
`tests/test_p3_runners.py` fail with `pytest: not found`. Using
`.venv/bin/pytest` without activation can cause the same failure.

### 6. Sanity check

```bash
source .venv/bin/activate
finalstrike --version
finalstrike doctor --repo fixtures/sample-app
pytest -q
```

Doctor should exit **0**. Warnings for stub modules, planned fixture work, or
skipped optional tools (live LLM, `ydotool`) are normal on a minimal dev machine.

## Troubleshooting

### `externally-managed-environment` when running `pip install`

You are using **system** pip. Create and use `.venv` (see step 2). Do not
`sudo pip install`.

### `.venv/bin/pip: cannot execute: required file not found`

The virtualenv is **broken** (often created on another machine or with a removed
Python). Fix:

```bash
rm -rf .venv
./scripts/setup-dev.sh
```

### `python3 -m venv .venv` fails

Install the venv module: `sudo apt install python3.12-venv` (adjust version).

### `pytest: not found` (3 failures in `test_p3_runners.py`)

```bash
source .venv/bin/activate
which pytest   # should show .../FinalStrike/.venv/bin/pytest
pytest -q
```

### Six failures in `test_p1_context.py` (secrets)

Ensure `fixtures/sample-app/.finalstrike/secrets.env` exists with an
`OPENAI_API_KEY` entry. The value may be your real API key.

## Testing computer-use locally (P6)

Default `pytest -q` replays committed action cassettes and does **not** drive
your desktop. To verify the real screenshot → vision LLM → OS input loop on a
GUI VM, follow the steps below.

### Prerequisites

| Requirement | Why |
|-------------|-----|
| **GUI session** with `DISPLAY` set (X11) or Wayland | Screenshots and window focus need a real desktop |
| **Google Chrome or Chromium** on `PATH` | `ui.browser: chromium` in `finalstrike.yaml` |
| **xdotool** (X11) or **ydotool** (Wayland) | Mouse/keyboard automation |
| **Vision-capable LLM** | Default fixture `llama3` via Ollama usually lacks image input — use `gpt-4o` or similar |
| **Fixture frontend on port 3000** | Smoke UI opens `http://localhost:3000/` |

Install platform tools on Debian/Ubuntu (once):

```bash
sudo apt update
sudo apt install -y chromium-browser xdotool
# or: google-chrome-stable, chromium, etc. — doctor checks the configured browser
```

Configure a vision model via gitignored overrides (see step 5 above). Example
`fixtures/sample-app/finalstrike.local.yaml`:

```yaml
llm:
  provider: openai_compat
  base_url: [REDACTED]
  model: gpt-4o
```

Optional: separate `computer_use.llm` block if the action model should differ
from the planner model (see `finalstrike.local.yaml.example`).

### End-to-end smoke run

From the repository root with `.venv` activated:

```bash
# 1. Confirm platform + LLM readiness
finalstrike doctor --repo fixtures/sample-app
# Expect OK or SKIP only for optional tools you are not using (e.g. ydotool on X11).
# Chrome/Chromium (P6), xdotool (P6), and Live LLM (P5) should be OK for a live run.

# 2. Start fixture API + static frontend (port 3000)
finalstrike env up --repo fixtures/sample-app

# Confirm services stayed up (env down should stop them, not report "already stopped")
finalstrike env down --repo fixtures/sample-app
# Expect: "[api] pid=... stopped" and "[frontend] pid=... stopped" — not "already stopped"
finalstrike env up --repo fixtures/sample-app

# 3a. Ad-hoc instruction (simplest)
finalstrike computer-use run --repo fixtures/sample-app \
  --instruction 'Open http://localhost:3000/ and verify the page title is "Sample App"'

# 3b. Or run the ac-2 UI step from a plan JSON
finalstrike plan --repo fixtures/sample-app \
  --acceptance fixtures/sample-app/acceptance-smoke.md --no-dry-run \
  > /tmp/smoke-plan.json

finalstrike computer-use run --repo fixtures/sample-app \
  --plan /tmp/smoke-plan.json --scenario-id ac-2

# 4. Stop services when finished
finalstrike env down --repo fixtures/sample-app
```

### What success looks like

- CLI prints `RunResult` JSON with `"status": "passed"` and exits **0**.
- Evidence is written under
  `fixtures/sample-app/.finalstrike/runs/<run_id>/`:
  - `screenshots/step-000.png`, `step-001.png`, … — one per loop step
  - `result.json` — full `RunResult` bundle

A failed run exits **1**; inspect `layers.ui.error` in `result.json` (and
stderr) for the root cause. Common failures:

- **Vision model not configured** — default Ollama `llama3` cannot read
  screenshots; set `gpt-4o` (or similar) in `finalstrike.local.yaml`.
- **Invalid action JSON** — the vision model returned text the parser could not
  use; retry with a model that supports `response_format: json_object` or check
  stderr for the validation message.
- **Page title still shows hostname** — Chromium may display `localhost` until the
  document title loads; FinalStrike polls window titles for up to 10s after launch
  and cross-checks WM titles when the vision model reports failure.
- **Reasoning models (o-series, etc.)** — some models reject custom `temperature`
  and only accept the provider default; FinalStrike omits `temperature` automatically
  when the API reports it is unsupported.
- **Platform tools** — missing Chrome/Chromium, `DISPLAY`, or `xdotool`.
- **`env down` reports "already stopped"** — terminal children outlived the shell
  wrapper pid recorded at `env up` (common with `shell=True` terminals). Re-run
  `env down` after upgrading FinalStrike (process-group teardown), or manually
  stop listeners on 3000/8080 (`fuser -k 3000/tcp 8080/tcp`). Success looks like
  `[api] pid=... stopped`, not `already stopped`.

Also inspect the last screenshots under `screenshots/` for visual context.

### Layered checks (without a live vision LLM)

These run in CI and are useful before attempting a live desktop run:

```bash
source .venv/bin/activate

# Unit tests — action parsing, loop logic, config (no GUI)
pytest -q tests/test_p6_computer_use.py

# Integration test — replays committed action cassette; needs xdotool + ffmpeg on PATH
pytest -q tests/test_p6_computer_use_integration.py
```

The integration test uses fake screenshot/input drivers but still requires
`xdotool` or `ydotool` and `ffmpeg` to be installed (see `@requires_platform_tools`
in `tests/conftest.py`).

### Further reading

- `docs/P6_APPROACH.md` — design decisions and scope
- `docs/PHASE_GAPS.md` — phase guardrails and cassette notes
- `fixtures/sample-app/AGENTS.md` — fixture-specific commands
