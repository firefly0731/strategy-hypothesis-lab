# Deploying Phase 1 (paper trading)

Phase 1 sends no orders and needs no API keys.

## Windows host (current)
Runs from the repo checkout with the existing `.venv`. Collected data, state and logs go to the git-ignored
`live_momentum/runtime/`.
```powershell
powershell -ExecutionPolicy Bypass -File live_momentum\deploy\windows\install_tasks.ps1   # per-user tasks, no admin
Start-ScheduledTask LiveMomentumPaper                                                       # start now
```
- `LiveMomentumPaper` starts at logon. A supervisor restarts the trader 10 s after any exit. It stops for good on exit
  code 2 (Binance access restricted).
- `LiveMomentumReport` runs daily at 06:20 and 21:00 KST (21:20 and 12:00 UTC).
- Both tasks run only while this user is logged on. Disconnect the remote session instead of signing out, and keep
  the machine from sleeping.
- Clock: Windows Time must be synced. Check with `w32tm /query /status`. The trader blocks entries if it is more than 1 s
  off Binance.
- Logs: `live_momentum\runtime\log\` (`paper.log`, `supervisor.log`). Events and reports: `live_momentum\runtime\data\`.
- Kill switch: `.venv\Scripts\python -m live_momentum.cli kill --config live_momentum\deploy\windows\config.paper.toml`
- Stop: `Stop-ScheduledTask LiveMomentumPaper`. This stops the supervisor. If a python process is still running,
  end it with `Get-Process python`.
- Remove: `Unregister-ScheduledTask LiveMomentumPaper,LiveMomentumReport -Confirm:$false`

## Live trading on the Windows host (Phase 3, REAL ORDERS)
Minimum-size test: every entry at the exchange minimum quantity (`size_mode = "min"`), config
`live_momentum\deploy\windows\config.live.toml`. Keys: `live_momentum\runtime\live.secrets` (git-ignored, user-only ACL).

Before the first start:
1. Put USDT in the futures wallet. Multi-Assets mode is off, so USDC cannot margin USDT contracts.
2. Keep the account flat in BTCUSDT/ETHUSDT/SOLUSDT. At a fresh session start the trader refuses to trade if
   it finds a position or an open order there.
3. Approve Phase 3 by setting the token yourself (at most 31 days ahead):
   `[Environment]::SetEnvironmentVariable("LIVE_MOMENTUM_ACK", "phase3-live:2026-12-20", "User")`
4. `powershell -ExecutionPolicy Bypass -File live_momentum\deploy\windows\install_live_task.ps1`, then
   `Start-ScheduledTask LiveMomentumLive`.

At start the trader checks the key (withdrawals and transfers off, IP whitelist on, futures on), one-way mode and the
USDT wallet. It exits with code 3 if a check fails, 4 if orders are not enabled (token), 2 on a region restriction.
The supervisor does not restart after these codes.

| what | how |
|---|---|
| log | `live_momentum\runtime\live\log\live.log`, events `live_momentum\runtime\live\data\paper\<date>\events.jsonl` |
| kill switch (cancel + flatten at the next minute, no new entries) | `.venv\Scripts\python -m live_momentum.cli kill --config live_momentum\deploy\windows\config.live.toml` |
| flatten now, without the trader | `.venv\Scripts\python -m live_momentum.run_live --config live_momentum\deploy\windows\config.live.toml --flatten` |
| stop | `Stop-ScheduledTask LiveMomentumLive`. Positions stay open: use the kill switch first |
| revoke approval | `[Environment]::SetEnvironmentVariable("LIVE_MOMENTUM_ACK", $null, "User")` (applies at the next start) |

## macOS host (Mac mini)
Same layout as the Windows host: runs from the repo checkout with its own `.venv`, and writes data, state and logs
to the git-ignored `live_momentum/runtime/`. The jobs are launchd LaunchDaemons, so they start at boot without a
login and run as the account that owns the checkout.

**One account, one trader.** Never run the live trader on two hosts at once. Move it only while the account is
flat and between sessions, and stop and disable the old host first:
`Stop-ScheduledTask LiveMomentumLive; Disable-ScheduledTask LiveMomentumLive`. Do the same for
`LiveMomentumPaper` if the paper trader moves too.

### 1. Host
- Keep the Mac awake and have it restart after a power cut: `sudo pmset -a sleep 0 disksleep 0 autorestart 1`.
- Clock: in System Settings → General → Date & Time, turn on "Set time and date automatically". Check it with
  `sntp time.apple.com`. The trader blocks entries if it is more than 1 s off Binance.
- Confirm Binance access: `curl -s https://fapi.binance.com/fapi/v1/time`. On HTTP 451 or 403, stop. Do not route
  around it.
- API key IP whitelist: the key only works from whitelisted IPs. Check the Mac's public IP
  (`curl -s https://api.ipify.org`) and add it in Binance API management. Better still, create a new key for this
  host and delete the old one. Allow futures trading only; withdrawals stay off.

### 2. Install
```bash
git clone https://github.com/firefly0731/strategy-hypothesis-lab.git ~/strategy-hypothesis-lab
cd ~/strategy-hypothesis-lab && git checkout feat/live-momentum
python3.14 -m venv .venv          # Windows host: Python 3.14.3, pandas 3.1.1, numpy 2.5.5,
                                  # exchange_calendars 4.13.3, websockets 17.4, pyarrow 26.0.1, requests 2.34.2
.venv/bin/pip install pandas numpy pyarrow requests exchange_calendars websockets pytest
PYTHONPATH=. .venv/bin/python -m pytest live_momentum/tests crypto_intraday_momentum/tests -q
# history archive 2021-01 .. now (~0.8 GB, cached under crypto_intraday_momentum/data_cache)
PYTHONPATH=. .venv/bin/python -c "from crypto_intraday_momentum.data import load_klines as l, load_funding as f; [(l(s,'2021-01','2026-11'), f(s,'2021-01','2026-11')) for s in ('BTCUSDT','ETHUSDT','SOLUSDT')]"
```
Keep the package versions close to the Windows host's. The parity tests pin decisions to the backtest, so they must
all pass.

### 3. Paper trader and daily report
```bash
sudo live_momentum/deploy/macos/install.sh paper report
```
The report runs at 21:20 and 12:00 UTC. The calendar is rendered in the Mac's local time zone at install time
(06:20 and 21:00 in Asia/Seoul). Re-run `install.sh report` after changing the time zone. In a zone with
daylight saving time, also re-run it after each DST switch. Asia/Seoul has none.

### 4. Live trader (Phase 3, REAL ORDERS)
1. Create the key file by hand on the Mac, in an editor, so the key stays out of shell history. Do not copy it
   through git or a chat:
   ```bash
   mkdir -p live_momentum/runtime
   (umask 077; touch live_momentum/runtime/live.secrets)      # owner-only from the start
   nano live_momentum/runtime/live.secrets                     # two lines: BINANCE_API_KEY=... and BINANCE_API_SECRET=...
   ```
2. Set the approval token yourself, at most 31 days ahead:
   ```bash
   (umask 077; echo 'LIVE_MOMENTUM_ACK=phase3-live:2026-12-20' > live_momentum/runtime/live.ack)
   ```
   launchd does not read shell profiles, so `run_live.sh` reads the token from this file. The file must be
   owned by you with mode 600. The supervisor re-reads it before every trader start. If you delete it, the next
   restart runs with no approval: the trader exits 4 and the supervisor stops. To stop at once, also run
   `install.sh remove live`, after the kill switch if a position is open. Do not put `LIVE_MOMENTUM_ACK` in the
   job environment. A token there takes precedence over the file, so deleting the file would not revoke it.
3. Check that the old host is stopped and the account is flat in BTCUSDT/ETHUSDT/SOLUSDT, then run:
   `sudo live_momentum/deploy/macos/install.sh live`

At start the trader runs the same preflight checks as on Windows. Exit 3 now also covers an unreadable secrets
file and a second trader on the same state directory, which holds the lock `state/run_live.lock`. The supervisor
stops on exit 2, 3 or 4. Check `live_momentum/runtime/live/log/supervisor.log` and `live.log`.

A stop on 2, 3 or 4 lasts until the next boot or reload. `RunAtLoad` starts the job again, and the same checks run
again. Reloading the job (`install.sh live`) or stopping it kills a running trader without flattening. The trader
has no graceful SIGTERM path. The next start reconciles with the exchange, but use the kill switch first while a
position is open. Stop or reload only between sessions.

| what | how |
|---|---|
| status | `sudo launchctl print system/com.livemomentum.live` |
| log | `live_momentum/runtime/live/log/live.log`, events `live_momentum/runtime/live/data/paper/<date>/events.jsonl` |
| kill switch (cancel + flatten at the next minute, no new entries) | `PYTHONPATH=. .venv/bin/python -m live_momentum.cli kill --config live_momentum/deploy/macos/config.live.toml` |
| flatten now, without the trader | `PYTHONPATH=. .venv/bin/python -m live_momentum.run_live --config live_momentum/deploy/macos/config.live.toml --flatten` |
| stop | `sudo live_momentum/deploy/macos/install.sh remove live`. Positions stay open, so use the kill switch first |

Optional: copy `live_momentum/runtime/live/data/` (collected bars and event logs, a few MB) from the old host so the
reports keep their history. State files are not needed when the account is flat between sessions.

## Linux host on AWS Tokyo (ap-northeast-1)

## 1. Host
- Ubuntu 22.04/24.04, 2 vCPU / 4 GB is enough (about 20 s of CPU at each open for the history replay).
- Clock: chrony with the Amazon Time Sync Service. In `/etc/chrony/chrony.conf`:
  ```
  server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4
  ```
  Then run `sudo systemctl restart chrony` and check with `chronyc tracking`. The system offset should be well under 10 ms.
  The paper trader also compares the local clock with Binance server time every hour. It blocks new entries if the
  difference exceeds 1 s (the exchange-time estimate includes network round-trip).
- Confirm Binance access from the instance: `curl -s https://fapi.binance.com/fapi/v1/time`.
  If you get HTTP 451 or 403, the region is restricted. Stop and do not route around it.

## 2. Install
```bash
sudo useradd --system --create-home --home-dir /opt/live_momentum livemom
sudo -u livemom git clone https://github.com/firefly0731/strategy-hypothesis-lab.git /opt/live_momentum/strategy-hypothesis-lab
cd /opt/live_momentum/strategy-hypothesis-lab && sudo -u livemom git checkout feat/live-momentum
sudo -u livemom python3 -m venv .venv
sudo -u livemom .venv/bin/pip install pandas numpy pyarrow requests exchange_calendars websockets pytest
sudo -u livemom .venv/bin/python -m pytest live_momentum/tests crypto_intraday_momentum/tests -q
sudo mkdir -p /etc/live_momentum /var/lib/live_momentum /var/log/live_momentum
sudo chown livemom:livemom /var/lib/live_momentum /var/log/live_momentum
sudo cp live_momentum/deploy/config.paper.toml /etc/live_momentum/config.toml
# history archive 2021-01 .. now (about 0.5 GB, cached under crypto_intraday_momentum/data_cache)
sudo -u livemom .venv/bin/python -c "from crypto_intraday_momentum.data import load_klines as l, load_funding as f; [(l(s,'2021-01','2026-11'), f(s,'2021-01','2026-11')) for s in ('BTCUSDT','ETHUSDT','SOLUSDT')]"
```

## 3. Run
```bash
sudo cp live_momentum/deploy/live-momentum-*.service live_momentum/deploy/live-momentum-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now live-momentum-paper.service live-momentum-report.timer
journalctl -u live-momentum-paper -f
```

## 4. Daily operation
| what | where |
|---|---|
| event log (decisions, virtual orders, fills, risk) | `/var/lib/live_momentum/data/paper/<date>/events.jsonl` |
| collected 1m bars | `/var/lib/live_momentum/data/bars/<SYM>/` |
| state (restart recovery), paper equity | `/var/lib/live_momentum/state/` |
| daily report, running summary | `/var/lib/live_momentum/data/reports/paper/<date>.md`, `summary.csv` |
| kill switch | `python -m live_momentum.cli kill --config /etc/live_momentum/config.toml` (`unkill`, `status`) |

The daily report runs twice:
- at 21:20 UTC: paper vs a replay on the bars collected live
- at 12:00 UTC the next day: adds the comparison with the public archive

A restart during a session reloads the state and catches up the missed minutes with the bar rule. The catch-up is logged as `catchup_start`.
