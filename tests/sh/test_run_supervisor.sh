#!/usr/bin/env bash
# Verifies that scripts/run.sh's supervisor logic restarts on failure up to MAX_RESTARTS.
# This test mocks `python` to exit non-zero and `caffeinate` to be a no-op.
# We capture the restart count from stderr and assert it matches OBSERVER_MAX_RESTARTS.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Mock python — always fail
cat >"$TMP/python" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/python"

# Mock caffeinate — strip the -i flag and exec the rest of the args directly.
# This lets the re-exec pattern in run.sh work without the real caffeinate binary
# needing to be present (or behave differently in CI).
cat >"$TMP/caffeinate" <<'EOF'
#!/usr/bin/env bash
# Drop the -i flag if present, then exec remaining args
while [[ $# -gt 0 && "$1" == -* ]]; do
  shift
done
exec "$@"
EOF
chmod +x "$TMP/caffeinate"

export PATH="$TMP:$PATH"
export OBSERVER_MAX_RESTARTS=2
# Mark as already caffeinated so the re-exec guard is bypassed (caffeinate mock
# will also set it, but being explicit here prevents a double-exec race in PATH
# lookup during testing).
export OBSERVER_RUN_CAFFEINATED=1

# Run with a short timeout and capture output; run.sh exits 1 after max restarts
output=$(bash "$REPO_ROOT/scripts/run.sh" 2>&1 || true)

# Expect exactly OBSERVER_MAX_RESTARTS restart messages
restarts=$(echo "$output" | grep -c "restart #" || true)
if [[ "$restarts" -ne 2 ]]; then
  echo "FAIL: Expected 2 restart messages, got $restarts" >&2
  echo "--- captured output ---" >&2
  echo "$output" >&2
  exit 1
fi
echo "OK: supervisor restarted $restarts times"
