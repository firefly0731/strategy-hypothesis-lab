#!/bin/bash
# Install / remove the launchd jobs on the macOS host. Run from the account that owns the checkout:
#   sudo live_momentum/deploy/macos/install.sh paper report      # paper trader + daily report
#   sudo live_momentum/deploy/macos/install.sh live              # LIVE trader (REAL ORDERS once approved)
#   sudo live_momentum/deploy/macos/install.sh remove live       # stop and unload a job
# The jobs are LaunchDaemons (/Library/LaunchDaemons): they start at boot without a login and run as you.
# Before `live`: the Windows live task must be stopped and disabled (one account, one trader), the account must
# be flat, live_momentum/runtime/live.secrets must exist with permissions 600, and you set the approval token
# yourself in live_momentum/runtime/live.ack (see run_live.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != root ] || { echo "run with sudo from the account that owns $REPO"; exit 1; }
[ $# -ge 1 ] || { echo "usage: sudo $0 [remove] paper|live|report ..."; exit 1; }
action=install
if [ "$1" = remove ]; then action=remove; shift; fi
for name in "$@"; do
    case "$name" in paper|live|report) ;; *) echo "unknown job $name"; exit 1 ;; esac
    label="com.livemomentum.$name"
    dst="/Library/LaunchDaemons/$label.plist"
    if [ "$action" = remove ]; then
        launchctl bootout "system/$label" 2>/dev/null || true
        rm -f "$dst"
        echo "removed $label"
        continue
    fi
    if [ "$name" = live ]; then
        sec="$REPO/live_momentum/runtime/live.secrets"
        [ -f "$sec" ] || { echo "missing $sec"; exit 1; }
        [ "$(stat -f %Lp "$sec")" = "600" ] || { echo "$sec must have permissions 600 (chmod 600)"; exit 1; }
        [ "$(stat -f %Su "$sec")" = "$OWNER" ] || { echo "$sec must be owned by $OWNER"; exit 1; }
        echo "note: (re)loading the live job stops a running trader WITHOUT flattening. Use the kill switch first if a position is open."
    fi
    sudo -u "$OWNER" mkdir -p "$REPO/live_momentum/runtime/log" "$REPO/live_momentum/runtime/live/log"
    tmp="$(mktemp -d)"
    "$REPO/.venv/bin/python" "$HERE/make_plists.py" "$tmp" --user "$OWNER" --only "$name" > /dev/null
    plutil -lint "$tmp/$label.plist" > /dev/null
    launchctl bootout "system/$label" 2>/dev/null || true
    install -m 644 -o root -g wheel "$tmp/$label.plist" "$dst"
    rm -rf "$tmp"
    ok=""
    for _ in 1 2 3 4 5; do             # bootstrap right after bootout can fail with "5: Input/output error"
        if launchctl bootstrap system "$dst" 2>/dev/null; then ok=1; break; fi
        sleep 2
    done
    [ -n "$ok" ] || { echo "launchctl bootstrap failed for $dst"; exit 1; }
    echo "loaded $label (status: sudo launchctl print system/$label)"
done
