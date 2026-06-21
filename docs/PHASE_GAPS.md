# Phase gaps and guardrails

Tracked gaps between completed phases (P0–P5) and upcoming work, with
guardrails so nothing is forgotten silently.

## Gap registry

| Gap | Resolves in | Guardrail |
|-----|-------------|-----------|
| Stub modules (`computer_use/`, `evidence/`, `reporters/`) | P6–P9 | `finalstrike doctor` lists unimplemented phases; `finalstrike.phase_status` registry |
| Fixture vs full acceptance criteria | P6 fixture extension | `acceptance-smoke.md` vs `acceptance-full.md`; `capabilities.yaml`; `tests/test_phase_guardrails.py` |
| LLM output consistency | P5+ ongoing | `tests/llm_recordings/` cassettes; `@pytest.mark.llm_cassette`; live structural tests with `@requires_ollama` |
| OS tools (FFmpeg, browser, xdotool/ydotool) | P6/P7 | `@pytest.mark.requires_platform_tools`; `doctor` checks binaries |
| HTML report template stub | P8 | `templates/report.html.j2` header comment; doctor lists P8 stub |

## Acceptance criteria files (fixture)

- **`acceptance-smoke.md`** — matches the current sample-app. Use for P0–P5.
- **`acceptance-full.md`** — task-list scenario for P6 demos. Fixture not built yet.
- **`capabilities.yaml`** — source of truth for implemented vs planned behavior.

When extending the fixture for P6, update `capabilities.yaml` first, then
move items from `planned` to `implemented`, then point demos at
`acceptance-full.md`.

## LLM integration testing (P5+)

Default CI uses **committed LLM cassettes** under `tests/llm_recordings/` so planner
behavior is deterministic without Ollama. Cassettes store prompt messages, raw
responses, and a canonical `VerificationPlan` golden file. Hash checks in
`meta.yaml` detect drift when prompts, acceptance files, or repo context change.

```bash
# Deterministic cassette replay (always in default pytest)
pytest tests/test_p5_planner_integration.py -q

# Optional live structural validation (needs Ollama)
pytest -m requires_ollama tests/test_p5_planner_live.py -q

# Refresh cassettes after prompt or acceptance changes
FINALSTRIKE_RECORD_LLM=1 pytest -m requires_ollama \
  tests/test_p5_planner_live.py::test_record_smoke_planner_cassette -q
```

Live tests assert **structure** (acceptance + `capabilities.yaml` coverage), not
bitwise equality with canonical plans. The same cassette layout extends to P6
computer-use action loops.

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

# Run only tests that need Ollama (skipped when unavailable)
pytest -m requires_ollama

# Run guardrail + cassette integration tests (always in default suite)
pytest tests/test_phase_guardrails.py tests/test_p5_planner_integration.py -q
```

## Before starting each phase

| Phase | Pre-flight |
|-------|------------|
| P5 | Ollama or OpenAI-compatible API for live checks; cassettes cover default CI |
| P6 | `doctor` shows ffmpeg + input tools; extend fixture or use smoke UI routes |
| P7 | P3+P4+P6 paths produce layer results; artifact dir layout from P3 |
| P8 | Replace `templates/report.html.j2` stub; sample `result.json` from a run |
