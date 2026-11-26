#!/bin/bash
# Supervisor for the Phase 3 LIVE trader on the macOS host (REAL ORDERS). Restarts it 10 s after a crash.
# Stops for good on exit 2 (region restriction), 3 (preflight / secrets / another trader running) or
# 4 (orders not approved).
#
# Approval: orders need LIVE_MOMENTUM_ACK=phase3-live:<last valid UTC date>, set BY THE USER. launchd does not
# read shell profiles, so unless the token is in the job's environment it is read from the git-ignored file
# live_momentum/runtime/live.ack (one line: LIVE_MOMENTUM_ACK=phase3-live:YYYY-MM-DD, owner-only, mode 600).
# The file is re-read before EVERY trader start: deleting it revokes the approval at the next restart, and the
# trader then exits 4 and the supervisor stops.
set -u
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO" || exit 1
export PYTHONPATH="$REPO"
PY="$REPO/.venv/bin/python"
CFG="live_momentum/deploy/macos/config.live.toml"
LOG="live_momentum/runtime/live/log"
ACKF="live_momentum/runtime/live.ack"
ENV_ACK="${LIVE_MOMENTUM_ACK:-}"           # token from the job environment, if the user put it there
mkdir -p "$LOG"
SUP="$LOG/supervisor.log"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$SUP"; }

load_ack() {   # sets LIVE_MOMENTUM_ACK for the next start; returns 1 if the file is unsafe
    unset LIVE_MOMENTUM_ACK
    if [ -n "$ENV_ACK" ]; then
        export LIVE_MOMENTUM_ACK="$ENV_ACK"
        return 0
    fi
    [ -f "$ACKF" ] || return 0               # no token: the trader exits 4 and we stop
    if [ "$(stat -f %Lp "$ACKF")" != "600" ] || [ "$(stat -f %Su "$ACKF")" != "$(id -un)" ]; then
        say "$ACKF must be owned by $(id -un) with permissions 600: supervisor stops"
        return 1
    fi
    LIVE_MOMENTUM_ACK="$(sed -n 's/^LIVE_MOMENTUM_ACK=//p' "$ACKF" | head -n 1 | tr -d '[:space:]')"
    export LIVE_MOMENTUM_ACK
    return 0
}

child=""
trap '[ -n "$child" ] && kill -TERM "$child" 2>/dev/null; wait "$child" 2>/dev/null; exit 0' TERM INT
while true; do
    load_ack || exit 0
    say "start"
    "$PY" -m live_momentum.run_live --config "$CFG" >> "$LOG/stdout.log" 2>&1 &
    child=$!
    wait "$child"
    code=$?
    child=""
    say "exit $code"
    case "$code" in
        2|3|4) say "exit $code: supervisor stops (see live.log)"; exit 0 ;;
    esac
    sleep 10
done
