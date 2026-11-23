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
