# Tick regime study, stage A: do conditional band breaks predict continuation?

User hypothesis (2026-11-24). Short-horizon price moves stay inside a band whose width depends
on the conditions (time of day, recent volatility, trade flow). A break of a wide, high-probability
band marks a trend. A maker would quote a grid inside the band and, on a break, exit or widen
the side against the trend. Stage 1 of `mm_trend_filter` rejected the 30-minute version of
this idea. This study tests the second-scale version.

Stage A is a prediction test only. It does not simulate a grid. The question is whether, after
a break, the price keeps moving in the break direction by more than the cost of a taker exit
(5 bp = 4 bp fee + 1 bp half spread and slippage), measured after a realistic reaction delay.
If not, a grid that exits on breaks cannot gain from the signal, and the idea stops here.
Stage B (grid inventory) runs only if stage A passes.

Everything below was fixed before any result was computed.

## Data
- Binance USD-M aggTrades, 2025-11 .. 2026-10 (12 months), exchange transact time in ms.
- Discovery: BTCUSDT, ETHUSDT, SOLUSDT. Hold-out: BNBUSDT, XRPUSDT, DOGEUSDT, run only after
  the discovery result is written down, with nothing changed.
- Large-tick group (added 2026-11-24 at the user's request, before any result): ADAUSDT
  (tick about 6.5 bp of price), NEARUSDT (3.2), WLDUSDT (4.0), TRUMPUSDT (10.7), FETUSDT (8.7).
  These are liquid coins whose one-tick spread is wide, so a maker earns more per fill. The group
  is reported on its own: (i) the best discovery cell, unchanged, as a second hold-out; and (ii)
  its own best cell, labelled descriptive.
- Cost per symbol: 4 bp fee + max(1 bp, half the tick in bp). This is 5 bp for BTC, ETH, BNB and
  XRP, and up to about 9.4 bp for TRUMP. On large-tick coins, trade prices bounce between bid and
  ask, which adds noise to g. A trade-price study cannot remove that; the one-day order book
  recording measures it.
- There is no order book data here. Prices are trade prices. Order book features are checked
  later on one day of the local recording (`crypto_mm/collector.local.toml`).

## Events
- Clock: 1-second grid on exchange time. p_t is the last trade price at or before t.
- Displacement x_t = log(p_t / p_{t-L}), L ∈ {10 s, 60 s}.
- Conditional scale s_t, using only data before t: the mean |x| over the previous 14 days at the
  same UTC hour, multiplied by the ratio of the realised volatility (Σ|Δlog p| over 1 s steps)
  of the last 15 minutes to its 14-day mean at that hour.
- z_t = x_t / s_t. Its threshold k_q is the q-quantile of |z| over the previous 14 days.
  q ∈ {0.90, 0.95, 0.99, 0.995, 0.999}.
- A break is the first second at which |z_t| > k_q, with direction sign(x_t). After a break,
  there are no new events for the same (L, q) until |z| has fallen below k_q again and at least
  L seconds have passed.

## Outcome
- Entry at t + d with delay d ∈ {0, 50, 100, 250, 500, 1000} ms. The entry price is the first
  trade at or after t + d.
- Continuation g = sign · log(p_{t+d+h} / p_entry) in bp, horizon h ∈ {10, 30, 60, 300} s.
- Net value = g − 5 bp. This is what a taker exit at the break saves (or a trend entry earns),
  ignoring the inventory already lost inside the band; that loss is stage B's job.
- Control: the same statistics at random seconds with the same hour-of-day mix, and a random
  direction. Its mean continuation should be about 0.

## Bayesian layer
Fixed before the results, with no tuning on the event table:
- A walk-forward logistic model predicts P(g > 5 bp | features). It is refit each month on the
  previous 3 months of events. The features are |z|, the 60 s signed taker-flow share, the
  trade-count intensity relative to its 14-day hourly mean, and the hour of day (sin/cos).
- The action rule comes from the costs, not from a search: act when the predicted expected net
  value is positive.

## Pre-committed criteria (discovery symbols pooled, d = 250 ms)
d = 250 ms is the primary delay. It is a conservative figure for a home PC in Korea: about
35 ms of network to Tokyo, gateway latency, and a margin for spikes.
- **A1, continuation beats cost:** for at least one (L, q, h) cell, the mean net value is > 0
  and the 95% day-block bootstrap CI (block 5 days, 2,000 draws) excludes 0. The best cell is
  recorded together with the number of cells examined (2 L × 5 q × 4 h = 40 at d = 250 ms).
- **A2, holds out of sample:** the best discovery cell, unchanged, has a mean net value > 0 on
  the hold-out symbols.
- **A3, the model adds value:** out of sample, the events the model selects have a higher mean
  net value than all events of the best cell, and its probabilities are calibrated (each decile
  within ±5 percentage points of the realised rate).
- The latency curve (net value against d) is reported for the best cell. It shows how much a
  faster implementation (for example in Rust) would be worth.

Stage B goes ahead if A1 and A2 pass. If A3 fails, stage B uses the plain threshold rule.

Statistics: every headline number is also shown per month. Variants counted for IDEAS_LOG:
2 L × 5 q × 4 h × 6 d = 240 descriptive cells, of which 40 are at the primary delay, plus 1 model.

## Stage A-anchored (2026-11-24, written after the stage A results, before any anchored result)
Stage A measured fast jumps against a moving reference (the price L seconds ago). A slow drift
out of a range never triggers it, and that drift is what loads a grid with inventory. This test
uses a band fixed to an anchor, which is closer to the user's concept. Everything below was fixed
before the anchored results were computed.

- **Anchor:** the clock is split into windows of R minutes, R ∈ {5, 15}, starting on the UTC
  hour. The anchor A is the last trade price at the start of a window; τ is the number of seconds
  since then. (This stands in for a grid that recentres every R minutes.)
- **Displacement:** y(τ) = log(p / A).
- **Conditional scale:** s = (mean |y| over the previous 14 days at the same UTC hour and the same
  10-second τ bucket) × (15-minute realised volatility / its 14-day mean at that hour). It is the
  same structure as the intraday momentum σ (mean move from the open at the same minute), on a
  shorter clock.
- **Band and break:** z = y / s; k_q is the q-quantile of |z| over the previous 14 days,
  q ∈ {0.90, 0.95, 0.99, 0.995, 0.999}. A break is the first second with τ ≥ 10 s and |z| > k_q.
  There is at most one break per window, and its direction is sign(y).
- **Outcome:** the same as stage A (entry at the first trade at or after t + d, cost
  4 + max(1, tick/2) bp), with horizons h ∈ {30, 60, 300, 900} s and the same delays.
- **Inventory note:** at a break the grid is loaded against the move. Holding it is worth the
  continuation −g per unit, and a taker exit costs the cost per unit. So the decision depends
  only on g against the cost, whatever the inventory size, and A1/A2 below are enough for stage A.
- **Criteria:** A1 and A2 as in stage A, at d = 250 ms. The cells are 2 R × 5 q × 4 h = 40. The
  large-tick group is reported in the same way. Random-time controls are matched on the hour
  and on τ.
- Variants added: 2 R × 5 q × 4 h × 6 d = 240 cells per group.
