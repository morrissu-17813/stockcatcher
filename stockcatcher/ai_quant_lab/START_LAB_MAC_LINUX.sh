#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD="$ROOT/dashboard"
cd "$ROOT"
echo '=== Tianji AI Quant Lab V12 | isolated paper-only ==='
if [[ ! -d "$DASHBOARD/node_modules/lightweight-charts" ]]; then
  echo 'Frontend packages missing; installing dashboard dependencies...'
  (cd "$DASHBOARD" && npm install)
fi
python server.py &
API_PID=$!
cleanup() { kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
cd "$DASHBOARD"
npm run dev -- --host 127.0.0.1
