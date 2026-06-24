# Sample App

Minimal fixture repository for FinalStrike integration testing.

This placeholder app provides a tiny HTTP API and static frontend so later phases can exercise environment orchestration, API checks, and UI verification without depending on an external repo.

## Acceptance criteria

| File | When to use |
|------|-------------|
| `acceptance-smoke.md` | P0–P4 (matches current app) |
| `acceptance-full.md` | Full fixture demo (Tiers 1–5 implemented) |
| `acceptance.md` | Index of the two files above |

`capabilities.yaml` lists implemented vs planned behavior. Update it when extending the fixture.

## Pre-flight

```bash
finalstrike doctor --repo fixtures/sample-app
```

See [docs/PHASE_GAPS.md](../../docs/PHASE_GAPS.md) for the full gap registry.

See [AGENTS.md](AGENTS.md) for service ports and smoke routes.
