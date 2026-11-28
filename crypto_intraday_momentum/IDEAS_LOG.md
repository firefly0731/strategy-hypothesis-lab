# Idea log

Every idea tested on this strategy is listed here, adopted or not. The number of variants
tried feeds a deflated-Sharpe / multiple-testing correction at the end.

The base is the paper's noise-band rules on Binance USDT-M perps, US session 09:30–16:00
NY, `maker_chase` execution, BTC+ETH+SOL equal weight. The hold-out set is BNB+XRP+DOGE.

| # | Idea | Variants tried | Result | Decision |
|---|------|----------------|--------|----------|
| 1 | Session definition: US hours vs UTC day | 2 | UTC day loses money on every symbol. US hours positive on BTC/ETH/SOL | US hours |
| 2 | Execution: taker / maker_skip / maker_chase / maker_in_taker_out | 4 | maker_chase is best. maker_skip misses the big trend days | maker_chase |
| 3 | Parameter grid (lookback × interval × exec × cost filter) via CPCV | 120 | PBO 0.16 (basket). The paper's defaults are as good as the selection | keep paper defaults |
| 4 | Markov-chain Monte-Carlo noise bands (1 vs 3 states, q 0.70–0.90) | 8 | Every MC band is worse than the paper σ. CPCV picks paper σ 45/45 | rejected |
| 5 | Entry cutoff × VWAP confirmation | 20 | Sharpe 0.93 → 1.22 (discovery). Hold-out −0.16 → 0.27 (diff t 2.9). WF picks 14:00/0.6 from 2023 on | **adopted** (14:00, 0.6σ) |
| 6 | Earlier session anchor (06:00–09:00 NY) | 10 | Worse the earlier it starts. Pre-open entries are −17…−27 bp | rejected |
| 7 | Sizing schemes × weights × drawdown throttle | 20 | rv24 ≈ risk-per-trade > paper (t ≤ 0.5). The throttle cuts bootstrap tail MDD −23% → −16% | **adopted** (rv24, equal, dd 15%) |
| 8 | Hold past 16:00 (6 horizons × 3 post-close rules) | 16 | Discovery Sharpe 1.22 → 1.02–1.11. Post-close P&L ≈ 0 bp on BTC/ETH/SOL. CPCV picks 16:00 40/45 | rejected |
| 9 | Order-flow confirmation (taker-buy imbalance: since open / last 30 min / z-score) | 6 (attribution only) | No monotonic relation in either set. 80–95% of breakouts already go with the flow, so the feature is redundant with price. Weak post-hoc hint that the *least* aligned quintile is best (exhaustion?), not pursued because of snooping | rejected |

| 10 | Universe expansion: 27 candidates incl. dead coins (LUNA, FTT, MATIC), monthly point-in-time selection (all liquid / trailing SR / VR / top-k by liquidity) | 10 | Fixed BTC+ETH+SOL is best (SR 1.33). The 20 coins never used before have median SR 0.06 (11/20 > 0). Edge is concentrated in the most liquid coins. The ex-ante rule "top-2 by liquidity" (BTC+ETH) gives SR 1.29 | keep BTC+ETH+SOL; justify ex-ante as "most liquid" |
| 11 | Range / mean-reversion strategies (separate package `crypto_range/`, see its IDEAS_LOG) | 92 + 18-cell scan | Pre-registered A–E all lose after costs. Post-hoc F (fade the 08:30→09:29 move at 09:30, exit 10:00) is +13.8 bp/trade maker, but its edge decayed after 2023 and it is weak in the same years as momentum | rejected (F: forward-test only) |
| 12 | Decision interval 15 / 5 min (entries and exits), first decision 10:00 or one interval after the open. Adopted rules unchanged | 4 | Production-sized Sharpe 1.43 (30 min) → 1.39 / 1.19 (15) → 0.76 / 0.57 (5). Gross per trade 19 → 6 bp, fees stay 4.3 bp. Stop exits 71% → 89%: the trailing stop is hit by noise | rejected |
| 13 | Entries checked every 15 / 5 min, exits/flips only on the 30-min grid (and 5/15) | 5 | Best is 15/30 from 10:00: production SR 1.47, unit SR 1.27 → 1.36. Paired daily diff t 1.73 (unit), 0.04 (production), corr 0.97, yearly t −0.9…+1.4. Inside the selection noise (CPCV inflation ≈ 0.2) | rejected (re-test on live data later) |
| 14 | Cap on entries per symbol-day (1 / 2) | 2 | 86% of trades are the first entry of the day. Re-entries average +3.5 bp, not losers. Losing days are bad first entries. Cap 1: unit SR 1.27 → 1.36, production 1.43 → 1.41, MDD −16.2% → −19.8%, diff t −0.25 | rejected |
| 15 | CME index futures (NQ=F, ES=F, Yahoo 60m) as signals: H1 agree-filter, H2 futures-breakout trigger, H3 large overnight gap | 6 | No hypothesis passes both sets. Best is ES H3 on discovery (t +2.63), which reverses on the hold-out (−0.62). NQ H3 on the hold-out is −2.01 | rejected |
| 16 | σ lookback 7 / 10 / 21 / 30 sessions (paper 14) with the adopted rules (VWAP 0.6σ, 14:00 cutoff, rv24 sizing). Re-check of #3, which predates those rules | 4 | Discovery production SR 1.29 / 1.25 / **1.43 (14)** / 1.38 / 1.35, hold-out 0.24 / 0.04 / **0.27 (14)** / 0.14 / −0.09. No window beats 14 at production sizing in either set (unit hold-out: 7 has SR 0.16 vs 0.10, t +0.49): paired daily diff t (production) −1.25 / −1.91 / −0.39 / −0.28 discovery, −0.33 / −1.64 / −1.54 / −1.58 hold-out. Trades/week 6.6–7.7 | keep 14 |

Seminar re-check (2026-11-24, `experiments/2026-11_seminar/`): CPCV over the #5 grid (N=10, k=2, embargo 30,
1x unit size, 2021-02..2026-10) gives PBO 0.53 on BTC+ETH+SOL. All 9 OOS paths have SR 0.92–1.22. IS mean 1.21 vs
OOS mean 1.01, so selection inflates SR by about 0.2. The 20 combos are all at SR 0.90–1.22, so which one ranks
first is mostly luck; the skeleton carries the edge. The hold-out has PBO 0.40 and path SR 0.11–0.32.
Look-ahead audit of the code paths: no leak found. The remaining bias is hindsight in parameters, universe and
sizing choices.

Correction: an earlier claim that 30-min returns had lag-1 autocorrelation ≈ −0.09 every year was a
small-sample bias (mean of per-session correlations over 12 pairs). The pooled estimate is −0.04…+0.06.

Total variants tried so far: ~347 (incl. the range research).
