#!/usr/bin/env bash
# One-shot local setup: Python venv + backend deps, frontend deps, .env scaffold.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Backend"
cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
mkdir -p data/outbox

echo "==> Frontend"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm install --no-audit --no-fund; fi

echo
echo "Done. Start with:  ./scripts/dev.sh"
