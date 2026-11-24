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

## Stage R: where does a maker fill revert? (2026-11-24, before any stage R result)
User question: can past data locate the band zone where mean reversion is most likely? For a grid
the relevant event is a first passage: after a fill, does the price move δ back toward the anchor
before it moves δ further away?

- **Coordinates:** the anchored band of stage A-anchored (R ∈ {5, 15} min). u is the position of
  |z| in its own distribution over the previous 14 days (the same histogram as k_q). The u bins
  are [0, .5), [.5, .8), [.8, .9), [.9, .95), [.95, .99) and [.99, 1].
- **Fill samples:** every 10th second (τ ≥ 10 s), and only when the last trade of that second
  was an aggressor pushing away from the anchor: a taker buy when y > 0, a taker sell when y < 0.
  That trade is the one that would hit a resting grid order on that side. Fill price p = that
  second's last trade. Position: short if y > 0, long if y < 0.
- **Outcome:** scan the following seconds using each second's trade high and low, for up to
  15 minutes. Reversion = a trade at p(1 ∓ δ) toward the anchor; adverse = a trade at p(1 ± δ)
  away from it. If both happen in the same second, it counts as adverse (conservative). Timeout:
  mark to market at 15 minutes. Value per fill (bp): +δ, −δ, or the mark to market.
- **δ ∈ {5, 10, 20} bp.** Cells where δ is less than 2 ticks are skipped, because bid-ask bounce
  would otherwise look like reversion.
- **Fees:** the value is reported gross (USDC-M maker 0 bp is the premise) and also net of 2 bp
  (USDT-M maker fee) for reference.
- **Secondary split (descriptive):** the sign of the 60 s taker flow relative to y (pushing away
  vs back toward the anchor).

Criteria (gross value; the CI is the day-block bootstrap as before):
- **R1, discovery:** for some (R, δ, u-bin), P(reversion) > 0.5 and the mean value is > 0 with the
  95% CI excluding 0. There are 2 R × 3 δ × 6 bins = 36 cells; the best cell is recorded with that
  count.
- **R2, hold-out:** the best discovery cell, unchanged, has a mean value > 0 on BNB/XRP/DOGE.
- The large-tick group is reported the same way. A one-day check on the order book recording
  compares trade-price and mid-price reversion rates for the bounce effect.
- This is still optimistic: queue position is ignored, so a real order fills less often when the
  price only touches it, and more often when the price goes through it.

### Stage R clarification (written after the discovery table, before any hold-out run)
"P(reversion) > 0.5" in R1 counts timeouts as neither, so it is ambiguous for large δ. Both
readings are now fixed for R2, and nothing else changes:
- **Primary cell (strict reading, P_rev > 0.5 of all samples and CI > 0):** R = 15, δ = 5 bp,
  u in [0.5, 0.8): +0.137 bp per fill (CI 0.110..0.165), P_rev 0.504.
- **Secondary cell (highest value, P_rev > P_adv):** R = 15, δ = 20 bp, u in [0.5, 0.8):
  +0.418 bp (CI 0.299..0.555), P_rev 0.293 vs P_adv 0.284.
R2 passes if the primary cell has a mean value > 0 on BNB/XRP/DOGE. The secondary cell is reported.

## Stage S: one-tick scalper with a band switch, from trades only (2026-11-24, before any result)
User idea: a tick scalper (bid and ask at the touch, take one tick) that quotes only while the
price is inside the conditional band. There is no order book data, so the queue position is
bracketed by two fill rules, and the result is read as a range.

- **Symbols:** those where one tick is worth taking: ADA, NEAR, WLD, TRUMP, FET (large tick) and
  SOL, XRP, DOGE (1.0–1.7 bp). BTC, ETH and BNB are excluded (one tick < 0.2 bp).
- **Quotes from trades:** the bid is the last taker-sell price and the ask is the last taker-buy
  price; if the ask is not above the bid, the ask is bid + 1 tick. A quote change takes effect
  250 ms after the trade that caused it (reaction delay). Until then the old quote rests, so it can
  be picked off.
- **States:** FLAT: rest a bid at the bid and an ask at the ask. On a fill, cancel the other side.
  LONG (SHORT): rest a take-profit one tick above (below) the entry. Exit by a taker order at
  the touch after 300 s if the take-profit has not filled.
- **Fill rules:** touch (optimistic, front of the queue): a taker trade at the quote price or
  better. Through (pessimistic, back of the queue): a taker trade strictly beyond the quote price.
  The fill price is the quote price either way.
- **Band switch** (anchored band R = 15 min, u as in stage R): new entries only while
  u < u_on, u_on ∈ {1.0 (no switch), 0.95, 0.8}. Open positions are managed the same way in
  every variant.
- **Fees:** maker 0 bp (USDC-M premise); the taker exit pays 4 bp. One unit at a time.
- **Output:** per round trip, PnL in bp; round trips per day; the share closed by the take-profit.
- **Split by time:** design half 2025-12 .. 2026-05, confirm half 2026-06 .. 2026-10.

Criteria:
- **S1:** under the through rule (pessimistic), the mean PnL per round trip is > 0 with the
  day-block CI excluding 0, pooled over the symbols, in both halves, for at least one u_on.
- **S2:** the band switch helps: under both fill rules, u_on = 0.8 or 0.95 has a higher mean than
  u_on = 1.0 in both halves.
- If S1 fails under the through rule but the touch rule is positive, queue position decides, and
  the order book recording is needed before any decision.
Variants: 2 fill rules × 3 u_on × 8 symbols.

### Stage S amended to the user's specification (2026-11-24, before any stage S result)
The user specified the strategy: buy and sell with a 20 bp spread, quote only inside the
strong-reversion zone of the hourly conditional band, and cancel and liquidate when the price
leaves the band. This replaces the one-tick take-profit above; everything else stays.
- **Take-profit:** 20 bp from the entry, rounded to whole ticks (at least 1 tick).
- **Band exit while in a position:** liquidate by a taker order when u ≥ exit_u,
  exit_u ∈ {0.95, 0.99, never}. "Never" holds until the take-profit or the timeout.
- **Timeout:** 30 minutes, then a taker exit.
- **Entry switch:** u_on ∈ {1.0, 0.95, 0.8} as before.
- **Symbols:** all 11 (a 20 bp spread is meaningful on the majors too).
- **Criteria:** S1 and S2 as above, for any (u_on, exit_u). Added S3 (descriptive): liquidating
  on a band exit is compared with holding, by mean PnL and by the 1st percentile of trip PnL.
Variants: 2 fill rules × 3 u_on × 3 exit_u × 11 symbols.
