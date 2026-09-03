#!/usr/bin/env bash
# Runs API (FastAPI :8000) and web app (Vite :5173) together for local development.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --reload) &
(cd "$ROOT/frontend" && npm run dev -- --host 0.0.0.0 --port "${WEB_PORT:-5173}") &
wait
