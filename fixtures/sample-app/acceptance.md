# Acceptance criteria (fixture index)

| File | Use when | Fixture support |
|------|----------|-----------------|
| [acceptance-smoke.md](acceptance-smoke.md) | P0–P5 CLI runs and default integration tests | **Implemented** — health, landing page, `pytest -q` |
| [acceptance-full.md](acceptance-full.md) | P5+ LLM planner and P6 UI task-list demos | **Implemented** — Tier 1–3; detail view in `planned` |

`capabilities.yaml` `implemented` lists the full fixture surface. Smoke acceptance
covers a subset; live planner structural tests filter capabilities to match the
acceptance file in use.

**Default for tests and CLI examples:** `acceptance-smoke.md`.
