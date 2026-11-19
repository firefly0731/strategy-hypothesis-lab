# crypto_range — intraday mean-reversion research (Binance USDT-M perps)

Goal: find a range / mean-reversion strategy that complements the intraday momentum
strategy in `crypto_intraday_momentum/` (momentum loses on quiet days, wins on trend days).

## Pre-registration (written BEFORE any of the results below were computed)

Universe: discovery = BTCUSDT, ETHUSDT, SOLUSDT (parameters may only be judged here);
hold-out = BNBUSDT, XRPUSDT, DOGEUSDT (never used to choose anything). Data 2021-01..2026-11.
Unit sizing (1x notional per trade, one position per symbol at a time), basket = equal
weight of the symbols. All times America/New_York unless stated.

Timing conventions are those of `crypto_intraday_momentum/signals.py`: a decision at
minute m sees bars 0..m-1 only (price = close of bar m-1); the first bar that can fill is m.
Taker = open of the fill bar +- 1 bp slippage, 0.05% fee. Maker = post-only limit,
filled only if the market trades THROUGH the limit, 0.02% fee. Funding charged when a
hold crosses a settlement. Regime filters use prior sessions only.

Execution modes tested for every idea (both reported):
* `taker`: taker entry; target checked on bar closes, exit taker at next open; time stop taker.
* `maker`: maker entry at the last close (+-0.5 bp), 5-minute timeout, skip if unfilled (no chase);
  take-profit = resting limit at the target; time stop = maker limit at the last close
  posted 5 minutes before the stop, taker fallback at the stop.

| ID | Idea | Primary (pre-registered) | Sensitivity grid |
|----|------|--------------------------|------------------|
| A | **Pre-open fade.** Session 07:00–09:30 NY (NYSE days), anchor = 07:00 open. Noise band O0·(1 ± k·σ_m), σ_m = mean |C/O0−1| at minute m over prior 14 sessions. Decisions every 15 min 07:30–09:00. Price above UB → short, below LB → long. Target = anchor, time stop 09:30. | k = 1.0, target = anchor | k ∈ {0.75, 1, 1.5, 2} × target ∈ {anchor, none} = 8 |
| B | **US-session VWAP-band reversion in range regimes.** 10:00–15:30, every 5 min: z = (px − VWAP)/(O0·σ_m) (σ_m = noise σ as in the momentum paper). |z| > k → fade, target = VWAP at decision, time stop 60 min (≤ 16:00). Regime filter: trailing 20-session variance ratio VR20 < 1 (VR = Σ session-return² / Σ 13 × 30-min-return², prior sessions only). | k = 1.5, VR20 < 1 | k ∈ {1, 1.5, 2} × filter ∈ {none, VR<1} = 6 |
| C | **Off-US-hours rolling-band fade.** Session 20:00 → 08:00 NY (every day). Every 15 min from 21:00: z = (px − mean120)/sd120 of the last 120 closed 1-min closes. |z| > k → fade, target = mean120, time stop 60 min. Filter: trailing 20-session VR of the off-hours session < 1. | k = 2.0, no filter | k ∈ {1.5, 2, 2.5} × filter ∈ {none, VR<1} = 6 |
| D | **30-min reversal in the US session.** At 10:00, 10:30, …, 15:30: r30 = last 30-min return; σ30 = RMS of 30-min returns over prior 20 sessions. |r30| > x·σ30 → fade, pure time exit after h minutes. | x = 1.0, h = 30 | x ∈ {0.5, 1, 1.5, 2} × h ∈ {30, 60} = 8 |
| E | **08:30 macro-spike fade** (no calendar; proxy = big move). Session 08:30–10:00 NY. At 08:45: r = 08:30→08:45 return; σ = mean |r| prior 20 sessions. |r| > x·σ → fade, target = 08:30 price, time stop h. | x = 2.0, h = 09:30 | x ∈ {1.5, 2, 3} × h ∈ {09:30, 10:00} = 6 |

34 parameter variants × 2 execution modes = 68 backtests per symbol set. The best idea is
chosen on the discovery basket by the session Sharpe of the pre-registered primary in
`maker` mode (and checked in `taker`); grid variants are only for sensitivity + CPCV PBO.

Validation per idea: per-trade gross/net bp and t, session Sharpe, MDD, yearly table
(esp. 2024 and 2026), CPCV PBO over the grid, hold-out. Complementarity: correlation of
the chosen strategy's daily returns with momentum `"final config"`, 50/50 (vol-matched)
and trailing inverse-vol combinations, 2022-01..2026-11.

### Addendum (POST-HOC, written after A–E results, before F was run through the engine)

A–E all lose after costs. One pattern stood out: in E the 09:30 exit loses but the 10:00 exit
wins on both sets, i.e. the pre-open move reverts *after* the US open (matches the
momentum finding that pre-open breakouts revert). A descriptive scan (no costs; 3 anchors
× 2 horizons × 3 thresholds = 18 cells × 6 symbols, ALL symbols seen, so the hold-out is
contaminated for this idea) showed −sign(pre-open move) × (09:30→10:00 return) ≈ +14…+33 bp
for |z| > 1 on every symbol, weaker in 2024 and ≈ 0/negative in 2026.

| ID | Idea | Primary | Grid |
|----|------|---------|------|
| F | **US-open fade of the pre-open move.** Session 07:00–10:30 NY. At 09:30 (sees bars to 09:29): r = C(09:29)/O(anchor) − 1, σ = mean |r| prior 20 sessions. |r| > k·σ → fade at 09:30, pure time exit. | anchor 08:30, k = 1, exit 10:00 | anchor ∈ {07:00, 08:30} × k ∈ {0.5, 1, 2} × exit ∈ {10:00, 10:30} = 12 |

Because F was found on data that includes the hold-out symbols, its only clean test is a
time split: the parameters above were fixed from the scan as a whole; we report 2021–2023
vs 2024–2026 and treat F as "needs forward testing" whatever the numbers say.

## Running

    python3 -m pytest crypto_range/tests -q
    python3 -m crypto_range.run          # writes crypto_range/results/report.txt

## Results (summary; full tables in `results/report.txt`, log in `IDEAS_LOG.md`)

* A–E (pre-registered): all lose after costs on discovery and hold-out, in both execution
  modes. Gross edges are ≈ 0…+4 bp (A) or negative (B, C, D), against round-trip costs of
  ~4–8 bp (maker) and ~12 bp (taker). B and D are −0.3 correlated with momentum because they
  take the other side of the same moves, but they lose money.
* F (post-hoc): fade the pre-open move at 09:30, exit 10:00. +14 / +19 bp net per trade
  (maker, discovery / hold-out), uncorrelated with momentum, but concentrated in 2021–2023
  and ≈ 0 on discovery in 2024–2026. Status: needs forward testing.
