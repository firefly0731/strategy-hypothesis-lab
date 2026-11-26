#!/bin/bash
# Daily paper report for the latest completed session (launchd: com.livemomentum.report).
set -u
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO"
mkdir -p "live_momentum/runtime/log"
"$REPO/.venv/bin/python" -m live_momentum.paper_report \
    --config "live_momentum/deploy/macos/config.paper.toml" >> "live_momentum/runtime/log/report.log" 2>&1
