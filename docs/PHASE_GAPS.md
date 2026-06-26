# Operational guardrails

> **Not the work backlog.** MVP planning, status, and ticket-level exit criteria live in **[Jira epic FS-4](https://smithingsolutions.atlassian.net/browse/FS-4)**. This file covers runtime guardrails, test markers, and setup gotchas. Architecture reference: `PLAN.html` (may lag Jira).

## Runtime gap registry

Code-level gaps between what is implemented today and what upcoming Jira stories will deliver — not the Jira backlog itself.

| Gap | Resolves in | Guardrail |
|-----|-------------|-----------|
| LLM output consistency | P5+ ongoing | `tests/llm_recordings/` cassettes; `@pytest.mark.llm_cassette`; live structural tests with `@requires_live_llm` |
| OS tools (FFmpeg, browser, xdotool/ydotool) | [FS-12](https://smithingsolutions.atlassian.net/browse/FS-12)/[FS-13](https://smithingsolutions.atlassian.net/browse/FS-13) (P6/P7) | `@pytest.mark.requires_platform_tools`; `doctor` checks binaries |

## Acceptance criteria files (fixture)

- **`acceptance-smoke.md`** — matches the current smoke subset (health, landing page, tests). Use for P0–P5 default runs.
- **`acceptance-full.md`** — Tiers 1–5 task-list scenario (fixture complete; `capabilities.yaml` `planned` empty).
- **`capabilities.yaml`** — maps **fixture** behavior only (implemented vs planned for the sample-app integration target). Not the product backlog. Fixture is complete (`planned: {}`).

When extending the fixture, update `capabilities.yaml` first, then move items
from `planned` to `implemented`, then point demos at `acceptance-full.md`.

## LLM integration testing (P5+)

Default CI uses **committed LLM cassettes** under `tests/llm_recordings/` so planner
behavior is deterministic without a live LLM. Cassettes store prompt messages, raw
responses, and a canonical `VerificationPlan` golden file. Hash checks in
`meta.yaml` detect drift when prompts, acceptance files, or repo context change.

```bash
# Deterministic cassette replay (always in default pytest)
pytest tests/test_p5_planner_integration.py -q

# Optional live structural validation (needs configured llm.base_url + credentials)
pytest -m requires_live_llm tests/test_p5_planner_live.py -q

# Refresh cassettes after prompt or acceptance changes
FINALSTRIKE_RECORD_LLM=1 pytest -m requires_live_llm \
  tests/test_p5_planner_live.py::test_record_smoke_planner_cassette -q
FINALSTRIKE_RECORD_LLM=1 pytest -m requires_live_llm \
  tests/test_p5_planner_live.py::test_record_full_planner_cassette -q
```

Live tests assert the planner returns a **valid multi-layer plan** for the
configured endpoint. Scoped capability checks use only items referenced in the
acceptance file under test (same as smoke). **Exhaustive** acceptance and
`capabilities.yaml` coverage is enforced by committed cassettes in default
`pytest -q`, not by live LLM runs. Computer-use action cassettes live under
`tests/llm_recordings/computer_use/` with the same replay pattern.

## Computer-use (P6)

P6 uses **Approach A** (custom desktop loop: screenshot → vision LLM → OS input).
The loop is exposed as a standalone command; full `run --layers ui` wiring is in P10 ([FS-15](https://smithingsolutions.atlassian.net/browse/FS-15)).

**Required on the GUI VM:**

- **Google Chrome or Chromium** — set `ui.browser` to `chromium` (default) or
  `chrome` in `finalstrike.yaml`. FinalStrike does not use the OS default browser;
  one of these binaries must be on `PATH` (`doctor` reports `Chrome/Chromium (P6)`).
- **xdotool** (X11) or **ydotool** (Wayland) for mouse/keyboard input.
- A real display session (`DISPLAY` or Wayland).

Optional `computer_use.llm` block overrides the planner `llm` config for the
vision/action model (must support image input). When omitted, the planner `llm`
block is used.

```bash
# Smoke UI scenario from a plan JSON (cassette-friendly in tests)
finalstrike computer-use run --repo fixtures/sample-app \
  --plan /path/to/plan.json --scenario-id ac-2

# Ad-hoc instruction (unified server on port 8080)
finalstrike computer-use run --repo fixtures/sample-app \
  --instruction 'Open http://localhost:8080/ and verify the page title is "Sample App"'
```

Per-step screenshots are written under `.finalstrike/runs/<run_id>/screenshots/`.
[Full desktop video recording is deferred to P7](https://smithingsolutions.atlassian.net/browse/FS-13).

**Local E2E workflow** (GUI VM, `env up`, doctor checks, expected artifacts):
[docs/LOCAL_SETUP.md § Testing computer-use locally](LOCAL_SETUP.md#testing-computer-use-locally-p6).

See `docs/P6_APPROACH.md` for Approach A vs B notes and future host-app/plugin work.

## LLM planner (P5)

The planner uses the OpenAI Python SDK with a configurable `base_url`. Set
`OPENAI_API_KEY` in `.finalstrike/secrets.env` for remote APIs; local Ollama
at `http://localhost:11434/v1` uses a placeholder key automatically.

```bash
# Dry-run: merged context only (no LLM call)
finalstrike plan --repo fixtures/sample-app \
  --acceptance fixtures/sample-app/acceptance-smoke.md --dry-run

# Live plan: VerificationPlan JSON on stdout
finalstrike plan --repo fixtures/sample-app \
  --acceptance fixtures/sample-app/acceptance-smoke.md --no-dry-run
```

Example `llm` blocks in `finalstrike.yaml`:

```yaml
# OpenAI API
llm:
  provider: openai_compat
  base_url: https://api.openai.com/v1
  model: gpt-4o

# Ollama (local)
llm:
  provider: openai_compat
  base_url: http://localhost:11434/v1
  model: llama3

# LiteLLM / OpenRouter / other gateway
llm:
  provider: openai_compat
  base_url: http://localhost:4000/v1
  model: anthropic/claude-sonnet-4-20250514
```

## Commands

```bash
# Surface all guardrails (secrets, PATH, fixture gaps, optional P6+ deps)
finalstrike doctor --repo fixtures/sample-app

# Run only tests that need a configured live LLM (skipped when unavailable)
pytest -m requires_live_llm

# Run guardrail + cassette integration tests (always in default suite)
pytest tests/test_phase_guardrails.py tests/test_p5_planner_integration.py -q
```

## Before implementing a Jira story

1. Open the story under [FS-4](https://smithingsolutions.atlassian.net/browse/FS-4) for scope and exit criteria.
2. Run `finalstrike doctor --repo fixtures/sample-app`.
3. For UI work: confirm Chrome/Chromium + input tools on the GUI VM.
4. For planner changes: run or refresh LLM cassettes as needed.
