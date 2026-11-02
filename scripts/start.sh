#!/usr/bin/env bash
# Start the production-style local server (FastAPI serves the built Vue app).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "Virtual environment missing. Running setup first..."
  ./scripts/setup.sh
fi

if [ ! -d frontend/dist ]; then
  echo "Frontend build missing. Building..."
  (cd frontend && npm install && npm run build)
fi

HOST="${CNKI_HOST:-127.0.0.1}"
PORT="${CNKI_PORT:-8000}"

echo "Starting CNKI Scholar AI at http://${HOST}:${PORT}"
echo "API docs: http://${HOST}:${PORT}/docs"
echo "Data directory: ${CNKI_DATA_DIR:-$ROOT/data}"
echo "Press Ctrl+C to stop."

if [ "${OPEN_BROWSER:-0}" = "1" ]; then
  (sleep 2 && (open "http://${HOST}:${PORT}" 2>/dev/null || xdg-open "http://${HOST}:${PORT}" 2>/dev/null || true)) &
fi

exec .venv/bin/python scripts/run_server.py
