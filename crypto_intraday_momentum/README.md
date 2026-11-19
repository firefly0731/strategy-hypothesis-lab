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
