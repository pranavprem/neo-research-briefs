#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_DEV="${WITH_DEV:-1}"

if [[ ! -d .venv ]]; then
  echo "Creating virtualenv in $ROOT/.venv"
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel >/dev/null
if [[ "$WITH_DEV" == "1" ]]; then
  python -m pip install -e '.[dev]'
else
  python -m pip install -e .
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo
echo "Config validation:"
if bash scripts/run_neo_briefs.sh --json validate-config; then
  echo "Config looks good."
else
  echo "Config still needs edits. That is normal until you fill in .env."
fi

echo
echo "Next steps:"
echo "  1. Edit .env for the adapters you want to enable"
echo "  2. bash scripts/run_neo_briefs.sh --json obsidian"
echo "  3. bash scripts/run_neo_briefs.sh --json run-once --dry-run"
echo "  4. bash scripts/run_neo_briefs.sh --json emit-openclaw-cron --repo-dir '$ROOT' > openclaw-cron.json"
echo "  5. bash scripts/run_neo_briefs.sh --json scan-repo-safety"
