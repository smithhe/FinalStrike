# Test layout

## Which repo to use

| Path | Role | Safe for deterministic LLM/config assertions? |
|------|------|--------------------------------------------------|
| `fixtures/sample-app/` (`FIXTURE_REPO`) | Integration target for CLI, env, doctor | **No** — developers may add gitignored `finalstrike.local.yaml` and real API keys |
| `tests/fixtures/cassette-smoke-v1/` (`CASSETTE_SMOKE_REPO`) | Frozen snapshot for planner cassettes | **Yes** — committed only; no local overlay |
| `tmp_path` | Unit tests with inline `finalstrike.yaml` | **Yes** — test controls all inputs |

## Rules

1. Do **not** assert `fixtures/sample-app` has no `finalstrike.local.yaml`.
2. Do **not** assert a specific `llm.model` or `llm.base_url` loaded from `FIXTURE_REPO` unless the test only checks `load_raw_config` (committed yaml) or uses `inject_secrets`/env overrides explicitly.
3. Do **not** assert exact secret values from `FIXTURE_REPO` (e.g. `fixture-test-key-not-real`); use `CASSETTE_SMOKE_REPO` or `tmp_path` for redaction/dry-run golden checks.
4. `@pytest.mark.requires_live_llm` tests **may** use `FIXTURE_REPO` intentionally — they exercise the developer's configured endpoint.

## Helpers

- `tests.support.cassette_repo.load_cassette_smoke_context()` — planner/cassette tests
- `load_raw_config(repo)` — committed `finalstrike.yaml` only (no local overlay)
