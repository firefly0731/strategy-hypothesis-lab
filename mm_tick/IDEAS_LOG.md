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

| # | Test (tick in force each day, `xs_v2/`, `xs_early_v2/`) | Result | Verdict |
|---|---|---|---|
| 21 | All symbols, primary settings | 2026-05..07 −9.39, 2026-08..10 −9.38, 2025-05..11 −9.43 bp per trip; through rule −10.6 to −10.9 | the maker loses on every coin on average |
| 22 | By symbol, whole sample | 0 of 75 (2026) and 0 of 70 (2025) coins positive; best TA −2.9 bp. ZIL −10.6, HOT −11.0, IDOL −7.4, GTC −5.9 / −28.1 | no coin carries an edge |
| 23 | Selected book (X1, X3) | 2026-05..07: no coin ever selected; 2026-08..10: TA on 12 days only, +2.28 bp (CI −0.19..5.04); 2025: no coin selected | **X1 fails, X3 fails. Stage X rejected** |

Reading
- With the real tick, the coins that looked profitable have one-tick spreads most of the time, so
  the "improve by one tick" quote does not exist and the maker joins long queues; adverse
  selection and fees then dominate, as in stage S.
- TA is the only coin whose earlier result did not change (its tick was unchanged in 2026), and
  alone it does not pass.

## Stage G: band-bounded inventory maker (user's specification; tick in force)

| # | Test | Result | Verdict |
|---|---|---|---|
| 24 | All symbols, primary (band 80%, break at the band edge, up to 5 units, hybrid) | −10.09 / −9.96 bp per closed unit (2026 halves), −9.54 / −9.83 (2025 halves); CIs about ±0.3 | **G1 fails** |
| 25 | By symbol, primary | 0 of 75 (2026) and 0 of 70 (2025) positive; best TA −6.9, 1000BONK −7.8 | no coin with an edge |
| 26 | Selected book | almost never active (no coin has a positive trailing week); where active −21 to +0.1 bp on 1 coin | **G2 fails** |
| 27 | Variants | 1 unit instead of 5: same (−9.5 to −10.1). Break at the 99% point: −9.4 to −9.7, fewer taker exits but larger losses on each. Through rule −10.1 to −10.7 | the band-bounded grid does not change the result |

Reading
- Inventory that builds up inside the band and exits at the band edge earns the same as the
  one-unit maker: about −10 bp per unit. Each maker exit earns need minus fees, and the units
  closed by a break or below break-even at the band edge lose more than that on average.
- Across stages S, X and G, a trade-only maker on Binance USDT-M at regular fees (2 / 5 bp) loses
  about 9–10 bp per round trip whatever the band rule. The band carries 0.1–0.4 bp of reversion
  (stage R), an order of magnitude less than the fee and the adverse selection.

## Stage C: ceiling for a fill-toxicity predictor (2026 trips of stage X, 2.34 M round trips)

Trip check: 1,098,149 / 1,244,200 trips, −9.39 / −9.38 bp: identical to #21. Structure: 86.8% of
trips win +2.9 bp on average, 13.2% lose −90.1 bp on average.

| # | Test | Result | Verdict |
|---|---|---|---|
| 28 | Synthetic predictor, kept fraction chosen on 2026-05..07 from 10%..100% (pre-registered) | Confirm-half mean: AUC 0.55 −6.3, 0.60 −3.9, 0.65 −1.9, 0.70 −0.2, **0.75 +0.9**, 0.80 +1.8, 0.90 +2.6 bp; IC 0.20 −1.7, **0.30 +1.1** | needs AUC ≥ 0.75 or IC ≈ 0.3, keeping 10% of fills |
| 29 | Same, finer fractions down to 0.5% (descriptive, added after #28) | Keeping 0.5% of fills: AUC 0.65 +0.25, 0.70 +1.6; IC 0.20 +1.6 | positive only on the most extreme 0.5% of scores, where the Gaussian synthetic score is most optimistic |

Reading
- Even a perfect predictor earns at most the average win, +2.9 bp per kept trip, because the
  take-profit is set at the cost (need). The edge of a filter is avoiding the 13% of trips that
  lose 90 bp, not improving the winners.
- Realistic second-scale features reach AUC 0.55–0.60. At that quality every kept fraction loses
  (−3.9 bp at 0.60). Reaching AUC 0.75 on the next 10 s–30 min of a coin would be a strong
  directional forecast in its own right, worth more as a taker signal than as a maker filter.
- Conclusion for the Bayesian idea: a posterior model of P(toxic fill) is worth building only
  with features that plausibly reach AUC ≥ 0.75; price-path features (the bands) measured
  0.1–0.4 bp of reversion, far below that. Order book features would be the candidate, which
  needs order book data first.

## Stage P: Bayesian additive logistic model of "this round trip loses" (trade-only features)

| # | Test | Result | Verdict |
|---|---|---|---|
| 30 | Fit 2026-05..07 (prior scale picked on 07, flat across 0.1..10), test 2026-08..10 | AUC train 0.673, **test 0.682** (Aug 0.695, Sep 0.659, Oct 0.688); large / small tick 0.671 / 0.675; calibration within 0.3 pp in every decile | **P1 fails** (< 0.75), but the model is real and stable |
| 31 | What carries it | Path length over 10 / 2 min (alone AUC 0.66 inverted), spread in ticks, tick size, the coin's past loss share, time since last trade. Flow imbalance and returns: ≤ 0.13 logit range | it predicts activity and volatility, not direction |
| 32 | Economic check (kept fraction chosen on the design half) | Keeps 13.4% of test trips: −7.81 bp vs −9.38 for all | still a loss |
| 33 | PnL by predicted-risk decile, test half (descriptive) | Loss share 3% → 28% across deciles, but the mean loss shrinks −386 → −54 bp; PnL −7.6 (safest) → −12.8 bp (riskiest) | frequency and severity of losses offset each other |

Reading
- The synthetic ceiling of stage C assumed that the score says nothing about the size of a
  loss. The real score does: the trips least likely to lose are on very active coins whose rare
  losses are huge. AUC on the binary label overstates the money a filter can make; at AUC 0.68
  the real filter earns −7.8 bp, not the −0.8 bp the ceiling implied.
- The right target is the expected PnL of the trip (or the loss severity together with its
  probability), not the loss probability. Even the safest decile here is −7.6 bp, so a better
  target would have to find about 8 bp per trip that these features do not show.

## Stage E: Bayesian additive model of the expected round-trip PnL (same features as stage P)

| # | Test | Result | Verdict |
|---|---|---|---|
| 34 | Fit 2026-05..07 (prior ratio by July MSE; the strongest value on the grid, 1e5, won), test 2026-08..10, rule "quote only if predicted PnL > 0" | Rank IC with PnL: train 0.13, **test 0.14** (Aug 0.17, Sep 0.15, Oct 0.12). **No test trip has a predicted PnL > 0** (0 kept); with weaker priors July kept 0.01% of trips | **E1 fails** |
| 35 | PnL by decile of the prediction, test half | Predicted −13.1 → −5.8 bp, realised −13.8 → **−5.4 bp** (best decile); top 1% chosen on July: −5.2 bp [−6.5, −4.0] | calibrated: the model ranks correctly and says no slice is positive |
| 36 | Two-part model (loss probability × win / loss size), secondary | IC 0.004; best decile predicted −0.3 bp, realised −7.1 bp; kept 3.8% at −6.9 bp | worse and miscalibrated |

Reading
- Predicting the money directly roughly doubles what the binary filter recovers (best decile
  −5.4 bp vs −7.6 bp), but the trade-only features cannot find a slice where the stage X maker
  earns its fees. The model is calibrated out of sample, so this is a statement about the
  information in these features, not about the fit.
- The prior choice at the grid edge would only shrink the predictions further toward −9.4 bp;
  it cannot create kept trips.

## Stage H: cut a held position or keep it (conditional continuation value, trade-only features)

| # | Test | Result | Verdict |
|---|---|---|---|
| 37 | One additive Bayesian linear model per checkpoint (5 s .. 25 min after entry), target = final − cut PnL; policy cuts at the first predicted A < 0; test 2026-08..10 | Hold −9.38 bp, policy **−9.39 bp** [−9.56, −9.21]; gain −0.02 [−0.09, +0.06]; 21% of trips cut | **H1 fails**, no gain at all |
| 38 | What the model sees | Rank IC with A: 0.28–0.29 at 5–10 s, falling to 0.07 at 15–25 min. Mean A is positive at every checkpoint (+3.4 bp at 5 s, +0.8 at 25 min): holding beats a taker cut on average; where the model says cut, A ≈ 0 | it ranks, but finds no rows where cutting pays |
| 39 | Hindsight ceiling (best of hold and every checkpoint cut, per trip) | **+0.64 bp** per trip (test), +0.76 design | the exit decision is worth up to ~10 bp with perfect foresight |

Reading
- The taker cut costs 5 bp plus the spread, and a held loser has usually already moved by the
  time any checkpoint sees it. With these features, the expected value of cutting never exceeds
  the value of waiting, so the money in the exit decision (up to 10 bp with hindsight) is not
  reachable from trade data.
- The same pattern as stages P and E: the trade tape ranks risk, but not by enough to pay the fees.
  The order book (stage OB, collection started 2026-11-25, bookTicker of 6 coins) is the next
  information set.
