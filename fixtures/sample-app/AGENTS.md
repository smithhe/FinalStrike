# Sample App — FinalStrike fixture

Minimal API + static frontend used for FinalStrike integration testing.

## Services

| Service  | Port | Notes                    |
|----------|------|--------------------------|
| API      | 8080 | `GET /health`, `GET/POST /api/tasks` |
| Frontend | 3000 | Static HTML pages (`/`, `/tasks.html`) |

## Smoke routes

- UI: `http://localhost:3000/` — landing page with title "Sample App"
- UI: `http://localhost:3000/tasks.html` — task list page with title "Sample App — Tasks"
- API: `http://localhost:8080/health`
- API: `http://localhost:8080/api/tasks` — list tasks (`GET`) or create (`POST` JSON `{title, description?}`)

## Computer-use (P6)

UI verification requires **Google Chrome or Chromium** on the GUI VM (`ui.browser`
in `finalstrike.yaml`), **xdotool** (X11) or **ydotool** (Wayland), and a
**vision-capable LLM**. Run `finalstrike doctor --repo .` to confirm
`Chrome/Chromium (P6)` and input tools.

Full step-by-step setup (platform packages, LLM overrides, evidence paths):
**[docs/LOCAL_SETUP.md § Testing computer-use locally](../../docs/LOCAL_SETUP.md#testing-computer-use-locally-p6)**.

```bash
# Start API + frontend (frontend serves static/ on port 3000)
finalstrike env up --repo .

# Live smoke UI — needs vision model in finalstrike.local.yaml or secrets
finalstrike computer-use run --repo . \
  --instruction 'Open http://localhost:3000/ and verify the page title is "Sample App"'

# Evidence: .finalstrike/runs/<run_id>/screenshots/ and result.json
finalstrike env down --repo .
```

## LLM configuration (live runs)

Committed `finalstrike.yaml` keeps the Ollama **example** defaults. For OpenAI or
another gateway, use **gitignored** overrides — do not commit provider changes to
`finalstrike.yaml`:

```bash
cp finalstrike.local.yaml.example finalstrike.local.yaml
# edit llm.base_url and llm.model
```

Or set `FINALSTRIKE_LLM_BASE_URL` / `FINALSTRIKE_LLM_MODEL` in
`.finalstrike/secrets.env` alongside `OPENAI_API_KEY`.

```bash
finalstrike plan --repo . --acceptance acceptance-smoke.md --no-dry-run
finalstrike doctor --repo .   # shows Local config overlay when present
```

## Test commands

- `pytest -q` — unit tests in `tests/`

## Known gaps

- No authentication (intentional for fixture simplicity)
- No live third-party API integrations
- Tier 2 task actions (complete, delete) from `acceptance-full.md` are **planned** — see `capabilities.yaml`
