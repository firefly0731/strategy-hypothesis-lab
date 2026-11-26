#!/bin/bash
# Supervisor for the Phase 1 paper trader on the macOS host (no orders, no API keys).
# Restarts it 10 s after any exit, except exit code 2 (Binance access restricted: stop, do not route around it).
# Started by launchd (com.livemomentum.paper, see install.sh). Runs from the repo checkout.
set -u
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO"
PY="$REPO/.venv/bin/python"
CFG="live_momentum/deploy/macos/config.paper.toml"
LOG="live_momentum/runtime/log"
mkdir -p "$LOG"
SUP="$LOG/supervisor.log"
child=""
trap '[ -n "$child" ] && kill -TERM "$child" 2>/dev/null; wait "$child" 2>/dev/null; exit 0' TERM INT
while true; do
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) start" >> "$SUP"
    "$PY" -m live_momentum.run_paper --config "$CFG" --equity 10000 >> "$LOG/stdout.log" 2>&1 &
    child=$!
    wait "$child"
    code=$?
    child=""
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) exit $code" >> "$SUP"
    if [ "$code" -eq 2 ]; then
        echo "access restricted: supervisor stops" >> "$SUP"
        exit 0
    fi
    sleep 10
done
