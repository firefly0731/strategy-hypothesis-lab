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

## Stage S: 20 bp spread scalper with the band switch (user's specification)

| # | Test | Result | Verdict |
|---|---|---|---|
| 11 | Through rule (back of the queue), all 11 symbols, any u_on / exit_u | −4.7 to −6.6 bp per round trip in both halves; CIs far below 0 | **S1 fails** |
| 12 | Touch rule (front of the queue) | Best: hold on band exit, about 0 (−0.2..+0.1 bp, CIs span 0) | no edge even when optimistic |
| 13 | Band switch (u_on 0.8 / 0.95 vs 1.0) | No consistent gain under either rule | **S2 fails** |
| 14 | Liquidate on band exit vs hold (S3) | Liquidation lowers the mean (touch, u_on 0.8: hold −0.04/−0.15, exit 0.99 −0.39/−0.57, exit 0.95 −1.41/−1.44) and improves the 1% tail (−180 → −162 → −132 bp) | pays about 1.4 bp per trip for tail protection |
| 15 | By symbol, touch rule | Large-tick coins positive (NEAR +3.4, ADA +1.6, FET +1.3, TRUMP +1.0); majors negative (−1.4 to −3.5). Under the through rule all are −3.3 to −7.1 | the large-tick gain exists only at the front of the queue |

Reading
- Round trips win +19.9 bp about 2/3 of the time and lose about −40 bp on a timeout the rest:
  the classic maker profile, and adverse selection removes the edge.
- For large-tick coins the answer depends on queue position. The one-day order book recording
  (ADA, TRUMP) is the right test for that.

## Stage X: cross-sectional, monitored maker (77-symbol universe, 75 simulated)

AGT and BULLA were dropped by the tick-grid check (their tick size changed, so most prices are
off today's grid); ON lost 4 of 6 months the same way.

| # | Test | Result | Verdict |
|---|---|---|---|
| 16 | All symbols every day (no selection), primary settings | −7.8 bp (design) / −8.6 bp (confirm) per round trip | the maker loses on the average coin |
| 17 | Selected book (trailing 7-day PnL > 0, ≥ 20 trips), primary settings (R=15, u_on 0.8, hold, hybrid fill) | Design +7.92 bp per trip (CI 4.72..10.08), confirm +1.66 (CI 0.50..2.96); random books of the same size −7.65 / −8.48 (p95 −6.56 / −7.25) | **X1 passes** |
| 18 | Same under the pessimistic through rule | +8.22 / +1.58 | holds at the back of the queue |
| 19 | Band switch, R, liquidation (X2) | u_on 0.8 vs 1.0, R 5 vs 15, hold vs liquidate: differences ≤ 0.6 bp, inside the CIs | the band adds nothing; the selection does all the work |
| 20 | Concentration | Design: ZIL 44%, HOT 42%, KAVA 15% of PnL (7 symbols ever selected). Confirm: IDOL 78%, TA 14%, W 7% (4 symbols). About 1–3 symbols active per day | fragile: few coins, and the edge decays from +7.9 to +1.7 bp |

Reading
- The monitoring rule finds coins whose maker PnL persists for weeks: tick-constrained, range-bound
  coins where price oscillates over a few ticks (ZIL, tick 12 bp; HOT; IDOL with 7-tick spreads).
- It is a walk-forward result: every selection uses only earlier days. But it rests on 3–4 coins
  per half, on fill rules inferred from trades only, and on illiquid books where the touch
  inferred from trades can be stale.
- Next checks before any money: record the order books of the selected coins (IDOL, TA, W, ZIL,
  HOT, KAVA) for a day or two, and replay the queue; then a minimum-size live test.

**Correction (2026-11-24): #17–#20 are invalid.** The simulator used today's tick on days when
the exchange tick was 10–100x coarser (ZIL, HOT, KAVA, W, IDOL among them), which created
impossible inside-the-spread quotes. Found when the 2025 extension gave +14 bp per trip, 64% of
it from GTC (tick 100x today's then). See DESIGN.md, "Bug fix before the re-run"; re-run results
follow.
