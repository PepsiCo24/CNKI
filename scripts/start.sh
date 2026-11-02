#!/usr/bin/env bash
# Start the production-style local server (FastAPI serves the built Vue app).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "Virtual environment missing. Running setup first..."
  if ! ./scripts/setup.sh; then
    echo ""
    echo "Setup failed. Please check:"
    echo "  - Python 3.11+ (python3 --version)"
    echo "  - Node.js 20+ and npm (node --version)"
    echo "  - Network access for pip/npm"
    echo "Then run: ./scripts/setup.sh"
    exit 1
  fi
fi

if [ ! -d frontend/dist ]; then
  echo "Frontend build missing. Building..."
  if ! (cd frontend && npm install && npm run build); then
    echo ""
    echo "Frontend build failed. Ensure Node.js 20+ is installed (node --version)."
    exit 1
  fi
fi

HOST="${CNKI_HOST:-127.0.0.1}"
PORT="${CNKI_PORT:-8000}"
DATA_DIR="${CNKI_DATA_DIR:-$ROOT/data}"
# Default import/watch folder after first DB init (overridable in 设置 → 数据与存储 / 知网接入).
IMPORT_HINT="${DATA_DIR}/imports"

echo "Starting CNKI Scholar AI at http://${HOST}:${PORT}"
echo "API docs: http://${HOST}:${PORT}/docs"
echo "Data directory: ${DATA_DIR}"
echo "Import directory: configure in 设置 → 知网接入 / 数据与存储 (default: ${IMPORT_HINT})"
echo "Press Ctrl+C to stop."

if [ "${OPEN_BROWSER:-1}" = "1" ]; then
  (sleep 2 && (open "http://${HOST}:${PORT}" 2>/dev/null || xdg-open "http://${HOST}:${PORT}" 2>/dev/null || true)) &
fi

exec .venv/bin/python scripts/run_server.py
