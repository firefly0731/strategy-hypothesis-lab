# live_momentum

Live / paper trading system for the adopted intraday momentum configuration
(`crypto_intraday_momentum/`, see its README and IDEAS_LOG). The research code is the
specification. This package reuses it unchanged wherever possible.

**Status: Phase 0 (signal parity) only. This package sends no orders.** Exchange connectivity,
risk enforcement, state storage, and systemd units come in Phase 1–2, after approval.

## Adopted configuration (`strategy.py`)
| item | value |
|---|---|
| universe | BTCUSDT, ETHUSDT, SOLUSDT USDⓈ-M perpetuals, equal weight |
| session | NYSE trading days 09:30–16:00 America/New_York (DST-aware, early closes skipped) |
| decisions | every 30 min from 10:00 to 15:30. Price = close of the last closed 1m bar |
| entry filters | no new leg at or after 14:00. New leg only if side·(p/VWAP − 1) ≥ 0.6σ |
| execution | maker_chase: post-only at last ∓ 1 tick for 5 min, then market. EOD post-only from 15:50, then market at 16:00 |
| sizing | 2%/RV24 per symbol, 25% portfolio vol target (60 sessions, cap 20), 3x per-trade cap, 15% drawdown throttle (floor 0.25) |
| history anchor | 2021-01 (the throttle and build_portfolio's warm-up are path dependent) |

## Modules
| module | role |
|---|---|
| `strategy.py` | constants above, `backtest_config(sym)`, `SizingParams` |
| `bars.py` | live 1m bar store → same grid as `load_klines` (outage bars marked `filled`) |
| `signal_engine.py` | `snapshot(df, now)`: research `build_sessions` + `compute_signals` on the bars closed at `now` (the rest of the session is NaN-padded). `target_position` is the decision rule. Raises `DataGap` when the last bar is missing |
| `executor.py` | `MakerChaseExecutor`: minute-driven order state machine with a pluggable venue. `SimBarVenue` uses the backtest fill rules (maker fills only when the price trades through the limit) |
| `sizing_live.py` | `session_sizing(data, day)`: multipliers from sessions before `day` only |
| `replay.py` | runs historical sessions through the live path minute by minute |
| `config.py` | TOML config. Safe defaults (`dry_run=true`, `mode=replay`). Secrets come from the environment or a 0600 file and are never printed |

### Timing contract
`step(t)` runs at session_start + t minutes, when bars 0..t−1 are closed:
1. maker fills on bar t−1
2. timeouts: cancel and send a market order
3. follow-up entry after an exit (same minute after a market exit, next minute after a maker exit, only before the deadline)
4. decision (only at decision minutes, and only when the session is `ready`)
5. EOD exit

An order never outlives the next decision. Its deadline is min(next decision, 15:50).

### Order safety (Phase 2+ design, enforced in config now)
Real orders require all of:
- `mode` = `testnet` or `live`
- `dry_run = false`, as a real TOML boolean
- a config that passes `validate()`. For example, `risk.max_notional_per_symbol` must be set.
- `LIVE_MOMENTUM_ACK` set to `<phase token>:<last valid UTC date>`, such as `phase2-testnet:2026-12-05` or `phase3-live:…`. The date may be at most 31 days ahead. An expired or wrong-phase token disables orders.

`replay` and `paper` reject `dry_run = false`. When `secrets_file` is set, keys are read from that file only. There is no fallback to the environment.

## Tests
```bash
python -m venv .venv && .venv/Scripts/python -m pip install pandas numpy pyarrow requests exchange_calendars pytest
python -m pytest live_momentum/tests -q          # real-data tests skip without the kline cache
python -c "from crypto_intraday_momentum.data import load_klines as l; [l(s,'2021-01','2026-11') for s in ('BTCUSDT','ETHUSDT','SOLUSDT')]"
```
| test file | checks |
|---|---|
| `test_signal_parity.py` | live replay vs `run_backtest` with `sizing="fixed"`, the backtest that `unit_trades` runs. Signals (rtol 1e-12), `ready`, and trades must be exactly equal. Synthetic data runs every session, including warm-up, and covers: 5 execution variants including the cost filter, forced band flips, and outage bars (a session with > 2% outage bars blocks the next one). Real data covers the last 60 sessions × 3 symbols by default, or more with `LIVE_PARITY_SESSIONS=250` |
| `test_lookahead_live.py` | perturbation of every bar from T. Snapshots and trades decided before T are bit-identical. Also checks the `snapshot` input cut, stale-data refusal, DST, and holidays / early closes |
| `test_sizing_parity.py` | per-session Σ multiplier·unit return = `build_portfolio` + `drawdown_throttle`. Runs on synthetic data with and without funding, on a stressed case where the 3x cap and the throttle bind, and on real data with funding (last 60 sessions). Multipliers rebuilt from klines and funding cut at the open are identical |
| `test_bars_executor.py` | bar grid identical to `load_klines` with outages. Executor scenarios: timeout → market, maker exit → flip entry next minute, orders resolve by the deadline |
| `test_config.py` | safe defaults, order gating, invalid configs, secrets not printed |

Reports: `reports/phase0.md`.
