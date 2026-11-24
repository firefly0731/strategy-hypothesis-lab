# Tick regime study: ideas log

Own hypothesis (user, 2026-11-24): a break of a conditional, high-probability price band on the
second scale marks a trend; a maker grids inside the band and exits or widens on a break.
Spec and pre-committed criteria: DESIGN.md. Data: Binance USD-M aggTrades 2025-11 .. 2026-10.
Variants: 240 cells per group (2 L × 5 q × 4 h × 6 delays), 40 at the primary delay of 250 ms.
Tables: `reports/summary_{discovery,holdout,large_tick}.csv`.

| # | Test | Result | Verdict |
|---|---|---|---|
| 1 | A1, discovery BTC/ETH/SOL, d=250 ms | Continuation after a break is +0.0 to +0.4 bp in every cell (cost 5 bp). Best cell L=10 s, q=0.995, h=300 s: +0.21 bp, net −4.79 (CI −5.01..−4.55). All 40 cells have a CI far below 0 | **rejected** |
| 2 | Latency curve, best cell | +0.29 bp at 0 ms, +0.19 bp at 1 s. Flat: speed does not matter because there is nothing to capture | no value in a faster (Rust) implementation for this signal |
| 3 | A2, hold-out BNB/XRP/DOGE, best discovery cell | +0.11 bp, net −4.89 (CI −5.13..−4.65). Own best cell +0.45 bp | **rejected** |
| 4 | Large-tick group ADA/NEAR/WLD/TRUMP/FET | Best discovery cell −0.24 bp, net −6.51. Own best cell +0.13 bp. Continuation is slightly negative (trade-price bounce and reversion) | **rejected** |
| 5 | Random-time control | −0.14 .. +0.22 bp: the same as after breaks | breaks carry no directional information beyond noise |

Notes
- A3 (the walk-forward logistic model) was not run: stage B needs A1 and A2, and both fail by
  about 5 bp, which a feature-based selection would have to recover on its own.
- Consequence for a maker: on average the price neither continues nor reverts after a break, so
  a taker exit at the break pays its 5 bp for nothing. The inventory loss in a trend is the
  move already made before the break, not what follows it.
- The one-day order book recording (`crypto_mm/collector.local.toml`) was started before these
  results and is kept for order book feature checks.

## Anchored band (stage A-anchored) and fill reversion (stage R)

| # | Test | Result | Verdict |
|---|---|---|---|
| 6 | Anchored band break, discovery (R=5/15 min) | Best cell R=5, q=0.999, h=900 s: +1.70 bp after a break, net −3.30 (CI −5.42..−0.77). Continuation grows with q and h; it is +0.1 bp at 1 min | **rejected** (A1) |
| 7 | Same cell, hold-out / large tick | +1.21 bp (net −3.79) / −2.23 bp (net −8.42) | **rejected**. Trends exist on the majors, but at about 1/3 of a taker exit |
| 8 | Stage R, discovery: first passage after a fill (gross, maker 0 bp) | Mid-band zone u 0.5–0.8 is best: R=15 δ=5 +0.137 bp (CI 0.110..0.165, P_rev 0.504); δ=20 +0.418. The edge fades toward the band edge and turns negative above u=0.99 at δ=20 | R1 passes, but the effect is tiny |
| 9 | Stage R, hold-out BNB/XRP/DOGE, cells fixed beforehand | Primary +0.134 bp (CI 0.101..0.166, P_rev 0.509); secondary +0.339. Same shape: u ≥ 0.99 −0.21 bp at δ=20 | **R2 passes** |
| 10 | Stage R, large-tick group | +0.3 to +1.8 bp, flat across u bins (no band effect) | Consistent with bid-ask bounce and spread capture, which queue priority on long large-tick queues would erode; not a band effect |

Reading
- The band shape the user expected is real and replicates: reversion is most likely in the middle
  of the conditional band and disappears at its edge, where quoting should stop.
- The size is +0.1–0.4 bp per fill before queue effects. The measured 1 s maker markout of about
  −0.5 bp (`research/mm/06`) and any maker fee (2 bp on USDT-M) are larger. Only a 0 bp maker venue
  (USDC-M) could use it, and only if the queue-aware test keeps a positive value.
- Next check: the one-day order book recording, mid price against trade price, for the bounce part.
