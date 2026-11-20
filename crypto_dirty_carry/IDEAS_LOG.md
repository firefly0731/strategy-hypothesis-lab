# Funding carry ideas (crypto_dirty_carry)

| # | Source | Variants | Result | Decision |
|---|--------|----------|--------|----------|
| C1 | Own hypothesis (user specification, 2026-11-20): factor-neutral "dirty" funding carry. Short top-K trailing funding, long bottom-K, inverse vol, dollar neutral, BTC-beta neutral. Literature step (RESEARCH_PROTOCOL §1) still open | 9 configs × {raw, hedged} (below) | 8h rebalance: costs ≈ funding in every variant. Daily rebalance: relative carry Sharpe 0.61 (t ≈ 1.0), spec signs ≈ 0. Daily + rank buffer 2K: Sharpe 0.84 (t ≈ 1.4), in-sample after 9 trials. Same rules on USDT-M 2021–2026: Sharpe 1.02 (t 2.4), 2021–2023 Sharpe 0.84 (t 1.4) but carried by 2021 and biased by a survivor universe | open (no adoption gate passed) |

## C1 runs: Binance USDC-M, 2024-01 .. 2026-10, 1h bars

All runs share these settings:
- Universe: 39 USDC perps that have data, taken from the current exchangeInfo (survivorship bias: contracts delisted before 2026-11-20 are missing).
- Parameters (defaults, fixed before the run): k = 5, decisions every 8h (00/08/16 UTC), execution 1 bar later.
- Carry signal: 3-day trailing funding. Volatility window 30 days, beta window 60 days, max weight 0.25.
- Costs: taker 4 bp + 1 bp slippage. Metrics span 2.66 years.

Every variant ran on one schedule for both books: "hedged" trades the factor-neutral targets and "raw" trades the dollar-neutral baskets. These are first descriptive runs; no hold-out split, CPCV or parameter search has been done.

| Config | Book | CAGR | Sharpe (bar / daily) | MDD | Funding | Price | Cost | Turnover/yr | Ex-post BTC β (t) | Flat decisions |
|---|---|---|---|---|---|---|---|---|---|---|
| Spec signs (short carry > 0, long carry < 0), projection | hedged | −12.9% | −0.51 / −0.46 | −51.0% | +0.42 | −0.34 | −0.39 | 150× | −0.016 (−1.0) | 247 / 2915 |
| | raw | −16.7% | −0.66 / −0.62 | −51.2% | +0.40 | −0.46 | −0.32 | 132× | −0.053 (−3.2) | |
| Relative (no sign condition), projection | hedged | +4.7% | 0.32 / 0.31 | −49.2% | +0.52 | +0.14 | −0.53 | 158× | −0.018 (−1.2) | 71 |
| | raw | +5.8% | 0.36 / 0.35 | −49.1% | +0.52 | +0.12 | −0.48 | 140× | −0.085 (−5.2) | |
| Relative, hedge legs (BTCUSDC) | hedged | +7.3% | 0.43 / 0.42 | −53.9% | +0.56 | +0.21 | −0.57 | 155× | −0.013 (−0.8) | 68 |
| | raw | +5.6% | 0.36 / 0.35 | −49.2% | +0.52 | +0.11 | −0.47 | 140× | −0.085 (−5.2) | |

### C1b: daily rebalance (rebalance_every = 1D at 00:00 UTC; everything else unchanged, fixed before the run)

| Config | Book | CAGR | Sharpe (bar / daily) | MDD | Funding | Price | Cost | Turnover/yr | Ex-post BTC β (t) | Flat decisions |
|---|---|---|---|---|---|---|---|---|---|---|
| Spec signs, projection | hedged | −2.4% | 0.01 / 0.02 | −37.6% | +0.43 | −0.20 | −0.28 | 98× | −0.024 (−1.4) | 86 / 972 |
| | raw | −6.9% | −0.18 / −0.16 | −37.2% | +0.40 | −0.33 | −0.24 | 90× | −0.062 (−3.6) | |
| Relative, projection | hedged | +11.2% | 0.61 / 0.58 | −35.4% | +0.48 | +0.20 | −0.36 | 103× | −0.025 (−1.6) | 23 |
| | raw | +8.1% | 0.46 / 0.44 | −32.2% | +0.45 | +0.09 | −0.31 | 94× | −0.091 (−5.4) | |
| Relative, hedge legs | hedged | +8.9% | 0.49 / 0.48 | −39.1% | +0.47 | +0.15 | −0.36 | 104× | −0.017 (−1.0) | 23 |
| | raw | +8.1% | 0.46 / 0.44 | −32.2% | +0.45 | +0.09 | −0.31 | 94× | −0.091 (−5.4) | |

Observations:
- **Costs fell but less than the decision count.** There are 3× fewer decisions but each one turns over about 0.29 of equity one-way, against 0.15 at 8h, so annual turnover only falls from about 155× to about 100×. The 3-day carry ranking reshuffles a lot from one day to the next. Funding collected barely changed (−0.04 to −0.09).
- **Every variant improved.** The best is relative/projection: Sharpe 0.61, CAGR +11.2%, MDD −35%, with yearly returns of +19.9% (2024), +21.0% (2025) and −8.6% (2026 YTD).
- **The result is not significant.** Sharpe 0.61 over 2.66 years gives t ≈ 1.0. Six configurations have been tried so far, so a deflated-Sharpe correction applies. Nothing has been held out.
- **Next, by pre-commitment:** cut the remaining turnover through the signal, not the clock. Options are a longer carry lookback, or a rank buffer that keeps a name until it leaves the top/bottom 2K.

### C1c: signal-side turnover cuts (base: relative, projection, daily; fixed before the run)

A = 7-day carry lookback (was 3D). B = rank buffer: a held name stays while ranked within 2K. C = A + B.

| Config | Book | CAGR | Sharpe (bar / daily) | MDD | Funding | Price | Cost | Turnover/yr | Ex-post BTC β (t) |
|---|---|---|---|---|---|---|---|---|---|
| Base (C1b best) | hedged | +11.2% | 0.61 / 0.58 | −35.4% | +0.48 | +0.20 | −0.36 | 103× | −0.025 (−1.6) |
| A: 7D lookback | hedged | +1.4% | 0.17 / 0.18 | −43.5% | +0.45 | −0.20 | −0.21 | 67× | −0.010 (−0.6) |
| | raw | +3.6% | 0.27 / 0.27 | −47.8% | +0.49 | −0.18 | −0.22 | 60× | −0.097 (−5.5) |
| B: buffer 2K | hedged | +16.2% | 0.84 / 0.80 | −20.9% | +0.43 | +0.24 | −0.18 | 52× | −0.010 (−0.7) |
| | raw | +14.7% | 0.73 / 0.71 | −22.3% | +0.43 | +0.18 | −0.17 | 47× | −0.081 (−5.1) |
| C: 7D + buffer | hedged | +7.7% | 0.46 / 0.45 | −34.1% | +0.37 | −0.05 | −0.10 | 30× | +0.007 (+0.5) |
| | raw | +12.4% | 0.62 / 0.60 | −35.1% | +0.41 | +0.06 | −0.10 | 28× | −0.086 (−5.1) |

Yearly returns of the hedged books:

| Config | 2024 | 2025 | 2026 YTD |
|---|---|---|---|
| A | +23.0% | +3.0% | −18.0% |
| B | +31.1% | +1.1% | +12.4% |
| C | +16.3% | +11.5% | −6.1% |

Observations:
- **Both cuts reduce turnover as intended.** Annual turnover falls from 103× to 67× (A), 52× (B) and 30× (C), and costs fall from −0.36 to between −0.21 and −0.10.
- **Funding collected is stable** across all variants, at +0.37 to +0.48.
- **Performance is not monotonic in turnover.** C has the lowest cost but a lower Sharpe than B. The differences come from price PnL, which swings between −0.20 and +0.24 across variants, more than the cost savings. So the ranking between variants is mostly noise in the price component, not a cost effect.
- **B is the best so far:** Sharpe 0.84, t ≈ 1.4, MDD −21%. It was chosen after seeing 9 configurations on the same sample, so it must be treated as in-sample. A deflated-Sharpe correction over 9 trials and a hold-out (time split, or a USDT-M universe the rules were not tuned on) are required before reading anything into it.

### C1d: variant B unchanged on USDT-M (2021-01 .. 2026-10)

The rules are exactly those of C1c-B: relative carry, projection, daily rebalance, 3D carry, rank buffer 2K, k = 5. Venue-dependent inputs:
- Universe: the USDT perps of the same 41 base assets as the USDC list.
- Costs: USDT VIP0 taker 5 bp + 1 bp slippage. Hedge instrument: BTCUSDT.
- Metrics start at the first trade, 2021-03-03. Sub-period PnL is relative to the equity at the start of each period.

| Period | Book | CAGR | Sharpe (bar / daily) | t | MDD | Funding | Price | Cost | Turnover/yr |
|---|---|---|---|---|---|---|---|---|---|
| 2021-03 .. 2023 (not seen when B was chosen) | hedged | +15.8% | 0.84 / 0.83 | 1.4 | −19.1% | +0.36 | +0.39 | −0.23 | 44× |
| | raw | +22.3% | 1.03 / 1.02 | 1.7 | −23.6% | +0.50 | +0.50 | −0.24 | 38× |
| 2024 .. 2026-10 (same coins and period as the USDC runs) | hedged | +26.5% | 1.19 / 1.15 | 2.0 | −36.2% | +0.77 | +0.56 | −0.38 | 65× |
| | raw | +34.8% | 1.26 / 1.20 | 2.1 | −35.8% | +0.86 | +0.86 | −0.38 | 61× |
| Full | hedged | +21.1% | 1.02 / 1.00 | 2.4 | −36.2% | +1.53 | +1.24 | −0.82 | 54× |
| | raw | +28.4% | 1.15 / 1.11 | 2.7 | −36.7% | +2.02 | +2.01 | −0.91 | 50× |

Yearly returns of the hedged book:

| 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|
| +53.4% | +2.9% | −4.1% | +47.3% | +65.2% | −19.8% |

Ex-post daily BTC β: hedged −0.001 (t −0.2), raw −0.067 (t −6.6).

Observations:
- **The unseen period is positive but rests on one year.** Most of 2021–2023 is 2021 (+53%, the high-funding bull market). 2022 and 2023 together are about flat, and t = 1.4 is not significant.
- **USDT beats USDC on the same coins and period** (Sharpe 1.19 against 0.84). Two candidate reasons, neither tested: USDT funding is larger and more dispersed, and early 2024 had more eligible USDT names (USDC had only 4 non-BTC perps).
- **Hedging lowers return.** The raw book does better than the hedged book in every sub-period. Its −0.07 BTC beta was not costly here. Neutralisation buys lower beta, not higher Sharpe.
- **Strong universe look-ahead in 2021–2023.** The universe is coins that (a) still trade in 2026-11 and (b) later received a USDC perp, which is selection on future success. LUNA, FTT and other delisted names are absent. The "unseen" period therefore is not a clean hold-out. A point-in-time USDT universe built from the symbols traded each month, with a liquidity filter, is needed before this counts.
- **Variant count: 10 configurations.**

(Re-run 2026-11-20 after the code review fixes: hedge instruments are no longer basket names,
outages are held instead of closed, post-cost sizing. Flat decisions in the relative runs are
mostly early 2024, when only 4 non-BTC USDC perps existed and k = 5 left the long side empty.)

In the table, PnL columns are in units of initial equity, and β is from daily OLS (n = 972).

Observations:
- **Factor neutralisation works.** Ex-ante BTC exposure goes to 0 (projection) or to |β'w| ≈ 0.004 (hedge legs, where the ±0.25 leg cap binds in 158 decisions). Ex-post daily β falls from −0.05 to −0.09 (t −3 to −5) in the raw books to between −0.01 and −0.02 (|t| ≤ 1.2) in the hedged books.
- **Costs are as large as the funding collected.** About 150× annual one-way turnover at 5 bp absorbs all of the funding in every run. The next variant to test is a slower rebalance and/or a turnover buffer, chosen before looking at results.
- **The spec's sign rule loses money on price.** Long names with negative funding fell (basket price PnL −0.37 to −0.46). One untested explanation: negative funding marks names under persistent selling.
- **Drawdowns are large.** All books have MDD near −50% at ~21% vol, with the largest loss from 2025-11 to 2026-08. 2026 YTD is −19% to −30% in every variant. BTC beta does not explain them, since the hedged books have β ≈ 0. A per-name decomposition has not been done.