# Crypto Intraday Momentum (Noise-Band Breakout)

Zarattini, Aziz & Barbon (2024) "Beat the Market: An Effective Intraday Momentum
Strategy for S&P500 ETF (SPY)" adapted to Binance USDT-M perpetual futures, with
maker / taker execution models.

## Rules
- **Noise σ(m)**: for decision minute *m*, mean of `|price(m)/open − 1|` over the
  previous 14 sessions (same minute-of-session, current session excluded).
- **Bands**: `UB = max(open, prev_close)·(1+σ)`, `LB = min(open, prev_close)·(1−σ)`.
- **Decisions** every 30 min starting 30 min after the session open.
  Long if price > UB, short if price < LB.
- **Exit/stop** (checked at decision times): long closes when price < max(UB, VWAP),
  short when price > min(LB, VWAP); a break of the opposite band flips. Flat at session end.
- **Sizing**: `leverage = min(4, 2% / σ_daily(14 sessions))`, compounding.

## Sessions
| name | window | prev_close |
|---|---|---|
| `us`  | 09:30–16:00 America/New_York on NYSE trading days (DST-aware, early-close days skipped) | previous NYSE session's 16:00 price (Mon → Fri, so the weekend move is the "gap") |
| `utc` | 00:00–24:00 UTC every day | previous day close (= today's open, no gap) |

## Look-ahead safeguards
Binance kline `open_time` is the **start** of the bar; bar `T` holds trades in `[T, T+1m)`
and its close is only known at `T+1m`.

| Item | What is used | Known at |
|---|---|---|
| Session open | `open` of the bar with open_time = 09:30 NY | 09:30 |
| Price at the 10:00 decision | `close` of the **09:59** bar | 10:00 |
| VWAP at 10:00 | Σquote_volume / Σvolume over bars 09:30 … 09:59 | 10:00 |
| σ, daily vol, prev_close | previous sessions only | before session start |
| Taker fill for the 10:00 decision | `open` of the **10:00** bar + slippage | ≥ 10:00 |
| Maker fill | limit = last close ∓ k·tick, fills on bars ≥ 10:00 only if price trades **through** the limit (touching ≠ fill) | ≥ 10:00 |
| Funding | charged if held over a settlement time (`entry_bar < t_f ≤ exit_bar`) | — |
| Outage filter | skip a session if the *previous* session had > 2% synthetic (missing) bars | before session start |

`tests/test_lookahead.py` enforces this with **perturbation tests**: every bar from time T
onward is replaced with random data, and the test checks that all signals and trades
decided before T stay bit-for-bit identical. Both session types and both execution modes
are covered. It also checks DST alignment (13:30 vs 14:30 UTC), the decision price =
previous bar close, and that a maker fill requires a trade through the limit.

## Execution variants (`run.py`)
| variant | entry | exit |
|---|---|---|
| `taker` | market at the next bar open | market |
| `maker_skip` | post-only, 5 min; unfilled → skip the trade | post-only 5 min → market fallback; EOD maker from 10 min before the close → market |
| `maker_chase` | post-only, 5 min; unfilled → market | same as above |
| `maker_in_taker_out` | post-only, 5 min; unfilled → skip | market |

Fees default to VIP0: maker 0.02%, taker 0.05%, and taker slippage is 1 bp. Check the
current fee schedule.

## Usage
```bash
pip install pandas numpy pyarrow requests exchange_calendars pytest
python -m pytest crypto_intraday_momentum/tests -q
python -m crypto_intraday_momentum.run --symbols BTCUSDT ETHUSDT SOLUSDT --session us utc
```
Data is downloaded from `data.binance.vision` (1m klines + funding) and cached in
`crypto_intraday_momentum/data_cache/` (git-ignored). Results go to `results/`.

## Known simplifications
- Maker queue position is modelled only by the trade-through rule. There is no partial-fill model.
- Stops are checked only at the 30-minute decision times, as in the paper. There is no intrabar stop.
- The random-direction test reuses the actual fill prices, so it is approximate. Use it on the `taker` variant.
- Tick sizes are hard-coded in `run.py`.

## CPCV & regime decomposition (`cpcv.py`, `run_cpcv.py`)
- **Unit = one session.** Every trade opens and closes inside one session, so splits never cut a trade.
- **Splits**: 10 contiguous groups, 2 test groups per split → 45 splits and 9 full OOS paths.
  Purge = 0 because labels end at the session close. Embargo = 30 sessions after each test
  group, because σ and the daily vol look back up to 30 sessions.
- **Selection**: in each split, the combo with the best train Sharpe among 120 combos
  (lookback {7,10,14,21,30} × interval {15,30,60} × exec {taker, maker_chase} × cost filter
  {0,2,4,8}) is applied to the test groups. PBO is computed from the OOS rank of the IS winner.
- **Cost filter** (`Config.cost_filter_mult`): open a new position only if σ at that decision
  time is ≥ mult × the expected round-trip cost.
- **Regime decomposition** of the OOS returns (Newey-West t, demeaned regressors):
  market direction β, ex-ante regimes (60-session trend, 20-session vol), a regime-balanced
  mean (2×2 ex-ante cells weighted equally), and same-session |move| terciles.

## Markov-chain Monte-Carlo bands (`mc_bands.py`, `run_mc.py`)
The band is the q / (1−q) quantile of the simulated open→m cumulative return. The simulation
uses 5-minute returns standardised by a time-of-day scale, and a 3-state volatility Markov
chain estimated over the previous 20 sessions (transitions within sessions only). The
starting state comes from the realised vol of the 60 minutes before the open. Each step
bootstraps from the empirical pool of its state. With `n_states=1` the Markov structure is
switched off (control). q = 0.79 matches the paper's σ width for Gaussian noise. RNG is
seeded per session; the look-ahead perturbation test covers both variants.

## Entry filters (`Config.entry_cutoff_min`, `Config.vwap_confirm_k`; `run_improve.py`)
These filters come from the trade attribution in `analyze_trades.py`.
- `entry_cutoff_min=270` opens no new position at or after 14:00 NY. Holding and stops are unchanged.
- `vwap_confirm_k=0.6` opens a new position only if `side·(px/VWAP − 1) ≥ 0.6·σ`.

`run_improve.py` validates them on the discovery set (BTC/ETH/SOL) and on a hold-out set
(BNB/XRP/DOGE, not used to find the rules). It reports a 5×4 threshold sensitivity grid,
CPCV over the grid, and yearly returns.

## Position sizing (`sizing.py`, `run_sizing.py`)
P&L is linear in size, so the strategy is run once at 1x notional. Each trade then gets a
leverage computed only from information available before its decision time.
- Schemes:
  - `paper`: 2% / 14-session close-to-close vol.
  - `rv24`: 2% / realised vol from 5-minute returns over the 24h before the open.
  - `ewma_rv24`: a smoothed version of `rv24`.
  - `strategy_vol`: targets the strategy's own trailing vol.
  - `risk_per_trade`: R / distance to the trailing stop, with a 0.5σ floor.
- Portfolio: equal or inverse-vol weights. A portfolio vol target uses the realised vol of
  the previous 60 sessions. Per-trade effective leverage on total equity is capped at 3x.
- Drawdown throttle: exposure × clip(1 − DD/dd_max, 0.25, 1), using the drawdown at the
  previous session's close.
- `run_sizing.py` also reports the adverse excursion per trade, a leverage ladder, and a
  block-bootstrap MDD distribution (20-session blocks). The throttle is re-applied on each
  resampled path.

## Walk-forward (`walkforward.py`)
This is an anchored walk-forward of the whole design process. At the start of each period,
the entry rules × sizing scheme (best train Sharpe) and the throttle level (best train
Calmar) are chosen from data before the period only, then applied to the period. The
results are joined into one out-of-sample curve for 2022-01 to 2026-11. 2026-11 comes from
the daily archives and was never used in any design step. Its funding is unavailable and
set to 0.
