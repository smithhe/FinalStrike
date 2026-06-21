# Sample App — FinalStrike fixture

Minimal API + static frontend used for FinalStrike integration testing.

## Services

| Service  | Port | Notes                    |
|----------|------|--------------------------|
| API      | 8080 | `GET /health` returns 200 |
| Frontend | 3000 | Static HTML smoke page   |

## Smoke routes

- UI: `http://localhost:3000/` — landing page with title "Sample App"
- API: `http://localhost:8080/health`

## Test commands

- `pytest -q` — unit tests in `tests/`

## Known gaps

- No authentication (intentional for fixture simplicity)
- No live third-party API integrations
