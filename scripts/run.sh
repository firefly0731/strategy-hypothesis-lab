#!/usr/bin/env bash
# Supervisor for the observer process. Restarts on non-zero exit up to OBSERVER_MAX_RESTARTS times.
# Wraps the whole run in `caffeinate -i` so macOS doesn't sleep mid-capture.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Re-exec under caffeinate if not already caffeinated.
# This pattern keeps all functions/state in a single script rather than
# attempting to pass shell functions into a `bash -c` subshell.
if [[ -z "${OBSERVER_RUN_CAFFEINATED:-}" ]]; then
  export OBSERVER_RUN_CAFFEINATED=1
  exec caffeinate -i "$0" "$@"
fi

# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Load .env so OBSERVER_MAX_RESTARTS (and other settings) are visible.
# Parse manually to handle "KEY = VALUE" (spaces around =) and skip blanks/comments,
# since `source` with `set -a` would try to execute such lines as commands.
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip blank lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue
    # Strip inline comments, leading/trailing whitespace, and spaces around '='
    # shellcheck disable=SC2001
    line="$(echo "$line" | sed 's/[[:space:]]*=[[:space:]]*/=/' | sed 's/[[:space:]]*#.*//' | xargs)"
    [[ "$line" == *=* ]] && export "$line" 2>/dev/null || true
  done < .env
fi

MAX_RESTARTS="${OBSERVER_MAX_RESTARTS:-10}"
attempt=0

run_once() {
  python -m observer.main
}

main() {
  while (( attempt <= MAX_RESTARTS )); do
    if (( attempt > 0 )); then
      echo "[run.sh] restart #$attempt after non-zero exit, sleeping 2s…" >&2
      sleep 2
    fi
    if run_once; then
      echo "[run.sh] observer exited cleanly" >&2
      exit 0
    fi
    attempt=$((attempt + 1))
  done
  echo "[run.sh] giving up after $MAX_RESTARTS restarts" >&2
  exit 1
}

main "$@"
