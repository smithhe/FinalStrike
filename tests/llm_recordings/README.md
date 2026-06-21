# LLM recordings (cassettes)

Committed request/response fixtures for **deterministic integration tests**
without calling a live LLM in default CI.

## Layout

```
llm_recordings/
  planner/
    smoke-v1/
      meta.yaml              # hashes for invalidation
      messages.json          # exact planner prompt messages
      responses.json         # raw LLM output(s), one per attempt
      plan.canonical.json    # normalized VerificationPlan golden file
  computer_use/              # P6+: same shape per UI scenario
```

## Default CI

Cassette replay tests run in the normal `pytest -q` suite — no Ollama required.

## Refresh a cassette (after prompt or acceptance changes)

When `assert_cassette_matches_context` fails, re-record from a machine with
Ollama (or another configured LLM) running:

```bash
export FINALSTRIKE_RECORD_LLM=1
pytest -m requires_ollama tests/test_p5_planner_live.py::test_record_smoke_planner_cassette -q
pytest tests/test_p5_planner_integration.py -q
git add tests/llm_recordings/
```

## Live structural checks (optional)

```bash
pytest -m requires_ollama tests/test_p5_planner_live.py -q
```

Live tests assert **structure** (acceptance + `capabilities.yaml` coverage),
not bitwise equality with the canonical plan.
