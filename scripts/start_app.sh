#!/usr/bin/env bash
# Start Funding Navigator (macOS/Linux; only the Windows script has been run so far).
#   scripts/start_app.sh [port]          REBUILD=1 scripts/start_app.sh   # build the database again
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8000}"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "Create the environment first: python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e ."; exit 1; }
export DATA_MODE=live PYTHONUTF8=1
if [ ! -f data/navigator.db ] || [ "${REBUILD:-0}" = "1" ]; then
  rm -f data/navigator.db
  "$PY" -m navigator.cli db upgrade --mode live >/dev/null 2>&1
  saved=$(find data/raw -type f ! -name .gitkeep 2>/dev/null | wc -l)
  if [ "$saved" -ge 5 ]; then
    echo "Rebuilding from $saved saved pages (nothing is downloaded)..."
    "$PY" -m navigator.cli pipeline --mode live --limit 200 --max-pages 200 --resume >/dev/null 2>&1 || true
  else
    echo "Loading the prepared dataset data/awards.jsonl ..."
    "$PY" -m navigator.cli import-data --input data/awards.jsonl --artifact-root data --mode live --trust-export >/dev/null
  fi
  "$PY" -m navigator.cli report --mode live >/dev/null 2>&1 || true
fi
echo "Funding Navigator: http://127.0.0.1:$PORT/  (Ctrl+C to stop)"
exec "$PY" -m navigator.cli serve --mode live --host 127.0.0.1 --port "$PORT"
