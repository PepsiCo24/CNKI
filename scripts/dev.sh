#!/usr/bin/env bash
# Development mode: FastAPI with reload + Vite dev server with HMR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "Virtual environment missing. Running setup first..."
  ./scripts/setup.sh
fi

cleanup() {
  kill "${BACKEND_PID:-}" 2>/dev/null || true
  kill "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

CNKI_PORT=8000 .venv/bin/python scripts/run_server.py --reload &
BACKEND_PID=$!

(
  cd frontend
  if [ ! -d node_modules ]; then npm install; fi
  npm run dev
) &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://127.0.0.1:8000  (docs /docs)"
echo "Frontend: http://127.0.0.1:5173"
echo ""
wait
