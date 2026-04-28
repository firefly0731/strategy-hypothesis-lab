#!/usr/bin/env bash
# 5-minute live smoke test against real Bithumb endpoints.
# REQUIRES: live .env with valid v2 read-only API key. NEVER commit captured fixtures untreated.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .venv/bin/activate ]]; then source .venv/bin/activate; fi

RUN_ID="smoke-$(date -u +%Y-%m-%dT%H-%M-%S)"
RUN_DIR="data/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "[smoke] starting 5-minute capture into $RUN_DIR" >&2
echo "[smoke] *** WHILE THIS RUNS, watch your bot server logs for any anomaly ***" >&2

OBSERVER_RUN_DIR="$RUN_DIR" \
OBSERVER_DURATION_SEC=300 \
OBSERVER_MAX_RESTARTS=2 \
python -m observer.main

echo "[smoke] capture finished, running convert..." >&2
python -m observer.convert "$RUN_DIR"

echo "[smoke] post-checks:" >&2

python - <<PY
import json, sys
from pathlib import Path
run_dir = Path("$RUN_DIR")
report = json.loads((run_dir / "report.json").read_text())
counts = report["event_counts"]
verdict = report["quality"]["verdict"]
errors_log = run_dir / "errors.log"
err_lines = errors_log.read_text().count("\n") if errors_log.exists() else 0

print(f"  event_counts={counts}")
print(f"  quality.verdict={verdict}")
print(f"  errors.log lines={err_lines}")

problems = []
if any(v == 0 for v in counts.values()):
    problems.append(f"empty channel(s): {[k for k,v in counts.items() if v==0]}")
if verdict != "OK":
    problems.append(f"quality verdict {verdict}")
if err_lines > 10:
    problems.append(f"errors.log has {err_lines} lines (>10)")

if problems:
    print("FAIL: " + "; ".join(problems))
    sys.exit(1)
print("PASS")
PY
