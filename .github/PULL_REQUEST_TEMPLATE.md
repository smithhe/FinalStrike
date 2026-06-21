## What was changed

<!-- Brief summary of the change (1–3 sentences). What behavior, files, or workflows changed? -->



## Why we changed it

<!-- Motivation, problem being solved, or trade-off accepted. Link issues if applicable. -->



## Validation

<!-- Tests and checks you ran to confirm the change works. Be specific (commands, scenarios, expected results). -->

- [ ] `source .venv/bin/activate && pytest -q`
- [ ] Other:



## Local environment setup

<!-- Include this section when reviewers need to run tests or the CLI. Delete if not applicable. -->

Reviewers need a correctly configured dev environment before the steps below will work.
Full guide: [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md).

```bash
# From repo root — creates .venv, installs deps, fixture secrets.env
./scripts/setup-dev.sh

# If .venv/bin/pip fails ("required file not found"), use:
# ./scripts/setup-dev.sh --recreate-venv

source .venv/bin/activate   # required: subprocess tests need pytest on PATH
pytest -q                   # expect passes; a few skips (live LLM / GUI tools) is OK
finalstrike doctor --repo fixtures/sample-app
```

**Do not** run bare `pip install` on Debian/Ubuntu (PEP 668). **Do not** copy `.venv` from another machine.



## How to test locally

<!-- Step-by-step instructions for this PR's changes. Assume setup above is done. -->

```bash
source .venv/bin/activate
# PR-specific commands here, e.g.:
# pytest -q tests/test_p6_computer_use.py
# finalstrike computer-use run --repo fixtures/sample-app ...
```

**Expected result:**

<!-- What should the reviewer see if everything works? -->
