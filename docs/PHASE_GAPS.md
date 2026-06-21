# Phase gaps and guardrails

Tracked gaps between completed phases (P0–P3) and upcoming work, with
guardrails so nothing is forgotten silently.

## Gap registry

| Gap | Resolves in | Guardrail |
|-----|-------------|-----------|
| Stub modules (`planner/`, `runners/api.py`, `computer_use/`, `evidence/`, `reporters/`) | P4–P9 | `finalstrike doctor` lists unimplemented phases; `finalstrike.phase_status` registry |
| Fixture vs full acceptance criteria | P5/P6 fixture extension | `acceptance-smoke.md` vs `acceptance-full.md`; `capabilities.yaml`; `tests/test_phase_guardrails.py` |
| LLM endpoint for live planner tests | P5 | `@pytest.mark.requires_ollama`; `doctor` checks `localhost:11434` |
| OS tools (FFmpeg, browser, xdotool/ydotool) | P6/P7 | `@pytest.mark.requires_platform_tools`; `doctor` checks binaries |
| HTML report template stub | P8 | `templates/report.html.j2` header comment; doctor lists P8 stub |

## Acceptance criteria files (fixture)

- **`acceptance-smoke.md`** — matches the current sample-app. Use for P0–P4.
- **`acceptance-full.md`** — task-list scenario for P5+ demos. Fixture not built yet.
- **`capabilities.yaml`** — source of truth for implemented vs planned behavior.

When extending the fixture for P5/P6, update `capabilities.yaml` first, then
move items from `planned` to `implemented`, then point demos at
`acceptance-full.md`.

## Commands

```bash
# Surface all guardrails (secrets, PATH, fixture gaps, optional P5+ deps)
finalstrike doctor --repo fixtures/sample-app

# Run only tests that need Ollama (skipped when unavailable)
pytest -m requires_ollama

# Run guardrail tests (always in default suite)
pytest tests/test_phase_guardrails.py -q
```

## Before starting each phase

| Phase | Pre-flight |
|-------|------------|
| P4 | Use `acceptance-smoke.md`; health checks in `capabilities.yaml`; optional `--plan` for extra API steps |
| P5 | Ollama or OpenAI-compatible API running; `doctor` green for LLM |
| P6 | `doctor` shows ffmpeg + input tools; extend fixture or use smoke UI routes |
| P7 | P3+P4+P6 paths produce layer results; artifact dir layout from P3 |
| P8 | Replace `templates/report.html.j2` stub; sample `result.json` from a run |
