#!/usr/bin/env bash
# Bootstrap local dev environment: venv, dependencies, fixture secrets.
# Usage (from repo root):
#   ./scripts/setup-dev.sh
#   ./scripts/setup-dev.sh --recreate-venv   # delete broken .venv first
set -euo pipefail

RECREATE=0
SKIP_TESTS=0

for arg in "$@"; do
  case "$arg" in
    --recreate-venv) RECREATE=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    -h|--help)
      echo "Usage: $0 [--recreate-venv] [--skip-tests]"
      echo "  --recreate-venv  Remove .venv before creating a fresh virtualenv"
      echo "  --skip-tests     Do not run pytest at the end"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.11+ (e.g. apt install python3 python3-venv)." >&2
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Using python3 ($PY_VERSION) at $(command -v python3)"

if [[ "$RECREATE" -eq 1 ]] && [[ -d .venv ]]; then
  echo "Removing existing .venv (--recreate-venv)..."
  rm -rf .venv
fi

if [[ -d .venv ]]; then
  if [[ ! -x .venv/bin/python ]] || [[ ! -f .venv/bin/pip ]]; then
    echo "warning: .venv looks incomplete; recreating..."
    rm -rf .venv
  elif ! .venv/bin/python -c "import sys" 2>/dev/null; then
    echo "warning: .venv python is broken; recreating..."
    rm -rf .venv
  elif ! .venv/bin/pip --version >/dev/null 2>&1; then
    echo "warning: .venv pip is broken (stale shebang?); recreating..."
    rm -rf .venv
  fi
fi

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv at .venv ..."
  if ! python3 -m venv .venv; then
    echo "error: python3 -m venv failed. On Debian/Ubuntu try:" >&2
    echo "  sudo apt install python${PY_VERSION}-venv python3-full" >&2
    exit 1
  fi
fi

echo "Installing package and dev dependencies..."
.venv/bin/pip install -U pip wheel
.venv/bin/pip install -e ".[dev]"

SECRETS_FILE="fixtures/sample-app/.finalstrike/secrets.env"
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Creating fixture secrets vault at $SECRETS_FILE ..."
  mkdir -p fixtures/sample-app/.finalstrike
  cat >"$SECRETS_FILE" <<'EOF'
OPENAI_API_KEY=fixture-test-key-not-real
SLACK_BOT_TOKEN=fixture-slack-token
EOF
else
  echo "Fixture secrets vault already exists: $SECRETS_FILE"
fi

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  source .venv/bin/activate    # required so bare 'pytest' subprocess tests pass"
echo "  pytest -q"
echo "  finalstrike doctor --repo fixtures/sample-app"
echo ""
echo "Without activating, prefix commands: .venv/bin/pytest, .venv/bin/finalstrike"
echo "Full guide: docs/LOCAL_SETUP.md"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  echo ""
  echo "Running pytest -q ..."
  # Activate-equivalent: put .venv/bin first for subprocess pytest resolution.
  export PATH="$ROOT/.venv/bin:$PATH"
  pytest -q
fi
