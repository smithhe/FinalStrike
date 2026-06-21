# EvalForge P2/P3 Verification Report

**Date:** 2026-06-21  
**Branch:** `cursor/p2-p3-env-runners-c15a`  
**Environment:** Linux VM, Python 3.12.3

## Test suite

| Metric | Result |
|--------|--------|
| Command | `pytest -v --tb=short` |
| Tests | **60 passed**, 0 failed |
| Duration | ~18s |

## CLI demo (fixtures/sample-app)

| Step | Command | Result |
|------|---------|--------|
| Config validation | `evalforge validate-config --repo fixtures/sample-app` | ✓ valid |
| Env bootstrap | `evalforge env up --repo fixtures/sample-app` | ✓ ready (498ms) |
| Health probe | `curl http://127.0.0.1:8080/health` | **200** |
| Full run | `evalforge run --layers env,build,terminal --branch demo/p2-p3` | **status: passed** |
| Env teardown | `evalforge env down --repo fixtures/sample-app` | ✓ stopped |

## RunResult highlights (full run)

- **run_id:** `2026-06-21T00-48-11Z`
- **branch:** `demo/p2-p3` (metadata only)
- **env layer:** passed — install + 2 terminals + health OK
- **build layer:** passed — install command exit 0
- **terminal layer:** passed — **1 test passed**, 0 failed

## Files in this directory

| File | Description |
|------|-------------|
| [pytest-full.log](./pytest-full.log) | Complete verbose test output |
| [validate-config.log](./validate-config.log) | Config validation CLI output |
| [env-up.log](./env-up.log) | Environment bootstrap success |
| [health-check.txt](./health-check.txt) | curl health status |
| [run-full-layers.json](./run-full-layers.json) | Full RunResult JSON (env + build + terminal) |
| [env-down.log](./env-down.log) | Teardown confirmation |

These files are committed on the PR branch so links work from GitHub.
