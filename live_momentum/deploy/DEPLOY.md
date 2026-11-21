# Deploying Phase 1 (paper trading) on AWS Tokyo (ap-northeast-1)

Phase 1 sends no orders and needs no API keys.

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
