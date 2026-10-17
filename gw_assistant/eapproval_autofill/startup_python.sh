#!/usr/bin/env bash
# Run the e-approval POC on a Linux server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-/home/bizntech/venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8810}"

if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
  echo "Virtual environment not found: ${VENV_DIR}" >&2
  echo "Set VENV_DIR to the directory containing bin/activate." >&2
  exit 1
fi

cd "${SCRIPT_DIR}"
source "${VENV_DIR}/bin/activate"

echo "GW Assistant E-Approval POC"
echo "Listening on http://${HOST}:${PORT}"
exec python -m uvicorn main:app --host "${HOST}" --port "${PORT}"
