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

## Stage X: cross-sectional, monitored maker (2026-11-24, universe fixed before any download)
User idea: pick, every day, only the coins where a maker earns the spread net of fees and
slippage inside the strong-reversion zone of a short conditional band; leave a coin as soon as
the opportunity fades (band break, or the monitored edge turning negative).

Universe (`universe_xs.csv`, from one exchange snapshot on 2026-11-24): Binance USDT-M perps
listed before 2026-03-01, 24 h volume $5M–300M, and one tick ≥ 3 bp or a current spread ≥ 4 bp
(that is, the round-trip maker fee can be covered). Symbols whose 2026-04..10 aggTrades zips
exceed 1 GB are left out for the disk budget (AKE, H, Q, VELVET, SKYAI, BANK, LAB). 77 symbols.
Data: 2026-04 (warm-up) .. 2026-10. Known bias: the snapshot keeps only coins still listed and
liquid today (survivorship). The strategy rules and criteria are written before any simulation,
in the next section.

### Stage X rules and criteria (written while the data downloads, before any simulation)
Fees (Binance USDT-M, regular tier): maker 2 bp, taker 5 bp.

Per symbol, a maker simulated on trades (the stage S machinery, with these changes):
- **Band (shorter than the momentum band):** anchored R = 15 min (primary, the stage R cell) and
  R = 5 min, hour-of-day baseline over 14 days. Quote only while u < 0.8 (the strong-reversion
  zone of stage R). Variant u_on = 1.0 (no switch) for comparison.
- **Band break:** u ≥ 0.99 cancels resting quotes. In a position: hold (primary, stage S
  showed it has the better mean) or liquidate by taker (variant).
- **Spread condition:** need = 2 × maker fee + AS, where AS is the symbol's mean 10-second
  markout against the maker side, over the previous 7 days (from trades: aggressor side ×
  price change 10 s after the trade). Quote only if the spread we would capture is ≥ need.
- **Quotes:** if the market spread is ≥ 3 ticks, improve each side by one tick (we are then the
  only order at that price); otherwise join the touch. Captured spread = our ask − our bid.
- **Fill rule (primary, "hybrid"):** a quote that improved the touch fills on any taker trade at
  its price (we are alone there); a quote that joined the touch fills only on a trade through it
  (back of the queue). The all-touch and all-through rules are reported as bounds.
- **After a fill:** a take-profit at max(entry + need, opposite touch − 1 tick) on the long side
  (mirror for short), same hybrid rule; taker exit after 30 minutes. One unit per symbol.
- 250 ms reaction delay on every quote change, as in stage S.

**Monitoring (selection):** each UTC day d, a symbol is active if its simulated mean net PnL per
round trip over days d−7..d−1 is > 0 with at least 20 round trips. Only active symbols count on
day d. Every input is from before day d.

Comparisons: all symbols every day (no selection); random selection with the same number of
symbols each day (200 draws); selection by the spread condition alone.
Halves: design 2026-05..07, confirm 2026-08..10.

Criteria (primary: R = 15, u_on = 0.8, hold, hybrid rule):
- **X1:** the selected book's mean net PnL per round trip is > 0 with the day-block CI excluding 0
  in both halves, and above the p95 of the random selections.
- **X2 (descriptive):** u_on = 0.8 against 1.0, R = 5 against 15, and hold against liquidate, inside
  the selected book.
- Capacity is reported: round trips per day and notional per day at the minimum order size.

### Stage X extension: the 12 months before (written 2026-11-24, before any download or simulation)
Reason: the main test rests on a few coins per half (confirm: IDOL 78% of PnL; without IDOL the
CI spans 0). A longer, earlier sample is the test the main result cannot give.

- **Data:** the same 77-symbol universe (no re-selection), aggTrades 2025-04 (warm-up) .. 2026-04.
  Simulated days 2025-05-08 .. 2026-04-30; with the main period this covers 2025-05 .. 2026-10.
  A symbol enters in its first listed month (that month is its warm-up; the band and the spread
  condition need 14 and 7 earlier days, so it cannot quote before). Months off today's tick grid
  are skipped as before.
- **Rules:** unchanged: the same code, the same primary settings and variants, no tuning.
- **Criterion X3 (primary settings):** over the whole extension, the selected book's mean net PnL
  per round trip is > 0, its day-block CI excludes 0, and it is above the p95 of the random books.
  Also reported, not part of the criterion: the two halves (2025-05..10, 2025-11..2026-04), the
  PnL share of the top symbols, and the result with the top one and top two symbols removed.
- **Known biases, larger here:** the universe is a 2026-11 snapshot (coins still listed and liquid
  now), so survivorship is worse further back; the tick size is today's.
- **Amendment (same day, before any simulation):** the 2025 months are larger than estimated
  (1.0–1.4 GB each) and the disk ran short at 2025-12. The user chose to shorten the extension
  instead of deleting more data: warm-up 2025-04, simulated 2025-05-08 .. 2025-11-30; halves
  2025-05..07 and 2025-08..11. The gap 2025-12 .. 2026-04 stays untested. X3 is unchanged.

### Bug fix before the re-run (2026-11-24): the tick in force, not today's tick
Binance cut the tick size by 10x or 100x on many of these coins during 2025–2026 (GTC 100x until
2026-04; ZIL, HOT, KAVA 10x until 2026-06; W until 2026-08; IDOL through 2026-10; 30 of 77 coins in
all; table `results/eff_tick_by_day.csv`). The tick-grid check caught only ticks *finer* than
today's, so on these days the simulator quoted "one tick inside" a spread that was a single real
tick: prices nobody could quote. Results in `xs/` and `xs_early/` are invalid for those coins.
Fix: per UTC day, the tick in force is the largest m in (1000, 100, 10, 5, 2) × today's tick with
≥ 99% of that day's trade prices on its grid (days under 200 trades keep the previous value);
each run of days is simulated in units of that tick. Everything else, including X1 and X3, is
unchanged. Both periods are re-run into `xs_v2/` and `xs_early_v2/`.

## Stage G: band-bounded inventory maker (user's specification, 2026-11-24, before any code run)
Change from stage X: the band is a price range, not an on/off switch. Every resting order and
the inventory stay inside it, and inventory may build up to a limit.

**Band (per second, from data before that second):** anchor = price at the start of the current
15-minute window; half-width = q80 × den, where den is the stage A-anchored scale (hour-of-day
14-day baseline × 15-minute realised volatility) and q80 is the 80% point of |z| over the
previous 14 days. Lower = anchor·exp(−q80·den), upper = anchor·exp(+q80·den), rounded inward to
the tick in force (stage X fix).

**Orders (one unit each; re-quoted on every trade, 250 ms to land):**
- *Entry bid* while the inventory is ≥ 0 and < 5 units and the price is inside the band: at the
  touch (one tick inside if the spread is ≥ 3 ticks), raised to the lower band edge if it is
  below it, never at or above the market ask. With inventory > 0, also at most last entry −
  need (a grid step), so units are added only as price falls. Only if the upper edge is at least
  `need` above the bid (room for a profitable exit). Mirror for the entry ask.
- *Exit ask* while long: max(touch ask, average entry + need), then **capped at the upper band
  edge** (the user's rule: an order outside the band is moved to the band edge, even when that
  is below break-even), never at or below the market bid. One unit per fill, FIFO. Mirror while
  short (floored at the lower edge).
- need = 2 × maker fee + trailing 7-day 10 s markout, as in stage X.
- Fill rules as in stage X: hybrid (primary), through (bound).

**Band break:** long and the trade price is below the lower edge → sell the whole inventory by
taker at the bid. Short and above the upper edge → buy back by taker. A break on the favourable
side is held (the exit order at the band edge then fills). End of each month: close by taker.

**Fees:** maker 2 bp, taker 5 bp. **Universe and periods:** stage X universe and the tick in
force; 2026-05..10 (halves as stage X) and 2025-05..11.

**Variants (descriptive):** max inventory 1 (no build-up); break at the 99% point instead of
the band edge (hold through small breaks).

**Monitoring and criteria:** stage X selection (trailing 7-day PnL per closed unit > 0, ≥ 20
closed units). **G1:** all-symbol book mean net PnL per closed unit, and **G2:** the selected
book, each > 0 with the day-block CI above 0 in every half and, for G2, above the random-book
p95. Also reported: by symbol, exit mix (maker / break / month end), inventory reached.

## Stage C: ceiling for a fill-toxicity predictor (2026-11-24, before any run)
Question: how good must a predictor of "this round trip will lose" be before the maker turns
positive? If even a strong predictor does not suffice, a Bayesian model of the conditional
probability (or any model) is not worth building on these fees.

- **Trips:** stage X primary settings, tick in force (R = 15, u_on 0.8, hold, hybrid), 75
  symbols, 2026-05-08 .. 2026-10-31; every round trip with its net PnL (mean −9.4 bp).
- **Synthetic predictor of a given quality:** label y = 1 if the trip loses (net PnL < 0). Score
  = y·μ + N(0, 1) with μ = √2·Φ⁻¹(AUC), so the score has exactly that AUC for y. AUC ∈ {0.55,
  0.60, 0.65, 0.70, 0.75, 0.80, 0.90}; 20 noise draws each. A second version ranks by the
  PnL itself with rank correlation (IC) ∈ {0.05, 0.10, 0.15, 0.20, 0.30}.
- **Decision:** keep only trips whose score is in the best fraction f of the design half
  (2026-05..07), f chosen on the design half from {0.1, 0.2, ..., 1.0}; apply the same score
  threshold in the confirm half (2026-08..10). Report the kept fraction and mean net PnL.
- **Reading:** the lowest AUC (and IC) at which the confirm-half mean is > 0. A predictor at
  AUC ≤ 0.60 is realistic for second-scale features in the literature; ≥ 0.75 is not.
- **Simplification (optimistic):** skipping a trip does not change later trips (in reality the
  quote would rest and fill at another time), and the predictor costs nothing in latency.

## Stage P: a Bayesian model of fill toxicity, target AUC ≥ 0.75 (2026-11-24, before any run)
Label: y = 1 if a stage X primary round trip loses (net PnL < 0); stage C showed a filter needs
AUC ≥ 0.75 on y to turn the maker positive.

**Information set:** only trades strictly before the decision time τ = fill time − 250 ms (the
quote that filled was set at least one reaction delay earlier). Trades of the same coin only
(BTC and ETH were deleted for disk; cross-asset lead is a later step if this one is promising).
All direction features are signed by the trip side d (+1 long, −1 short), so that > 0 means in
favour of the position.
- returns d·log(p_τ / p_{τ−W}) and taker flow imbalance d·(buy − sell)/(buy + sell) notional, for
  W ∈ {1 s, 5 s, 30 s, 2 min, 10 min};
- activity: trade count in W ∈ {5 s, 30 s, 2 min} relative to the last hour; path length
  Σ|Δlog p| over {30 s, 2 min, 10 min} (bp); last trade notional relative to the 10-min mean;
  log time since the last trade;
- band: u and d·z (stage X band, R = 15); need; estimated spread in ticks; tick in bp; whether
  the quote improved the touch; hour of day (sin, cos);
- the coin's loss share over the previous 7 days of trips (past labels only).

**Model:** logistic regression with a Gaussian prior (MAP by Newton, Laplace posterior). Every
feature enters as one-hot bins at its training-set deciles (a Bayesian additive model, so
non-linear shapes are allowed), plus an intercept. Prior scale τ chosen from {0.1, 0.3, 1, 3, 10}
on the last design month (2026-07) with the model fit on 2026-05..06; then refit on all of
2026-05..07 with that τ. Bins are fixed on the training data.

**Test:** AUC on 2026-08..10 (never used for any choice). **P1:** AUC ≥ 0.75 → the economic
check of stage C with the real scores (kept fraction chosen on the design half) and, only then,
a second test on 2025 trips. Reported always: AUC by month and by symbol group, calibration, the
top features. If AUC < 0.75 the model is reported as it is and not tuned further on the test.

## Stage E: a Bayesian model of expected round-trip PnL (2026-11-24, before any run)
Stage P found that the loss probability is predictable (test AUC 0.68) but that the trips with
rare losses lose the most when they do (−386 bp in the safest decile), so a loss classifier does
not rank by money. Stage E predicts the net PnL itself.

- **Trips and features:** the stage P table unchanged (`results/toxic_features.parquet`, the same
  27 features, the same decile bins with a NaN bin, the same information set).
- **Primary model:** E[pnl | x] as an additive Bayesian linear model: pnl = b0 + Σ w_bin + ε,
  ε ~ N(0, σ²), w ~ N(0, τ²), flat b0. The posterior mean is the ridge solution
  (X'X + σ²/τ² I)⁻¹X'y, X'X built from the bin contingency tables. Squared loss is kept on
  purpose: the conditional mean is the quantity that decides money, tails included.
- **Secondary model (reported, not used for the verdict):** two-part, E = (1 − p)·W + p·L, with
  p from the stage P logistic model and W, L the same linear model fit on winning and losing
  trips separately.
- **Choices, all on the design half:** fit on 2026-05..06, validate on 2026-07: the prior ratio
  λ = σ²/τ² ∈ {1, 10, 100, 1e3, 1e4, 1e5} by validation MSE; then refit on 2026-05..07.
- **Test:** 2026-08..10, never used for any choice.
- **E1 (decision rule fixed now):** quote a trip only when the predicted PnL > 0. Pass if, on the
  test half, the kept trips number ≥ 2,000, their mean net PnL is > 0, and the day-block bootstrap
  95% lower bound (2,000 draws over test days) is > 0. If E1 passes: a second test on the 2025
  trips, and a re-simulation where the filter acts inside the simulator (a skipped trip lets the
  quote rest; the trip-level check here treats later trips as unchanged, which is optimistic).
- **Always reported:** test PnL by decile of the prediction, the rank correlation (IC) of the
  prediction with the PnL, by month; the same for the secondary model; and, descriptively, the
  best kept fraction in {0.01, 0.02, 0.05, 0.1, 0.2} chosen on 2026-07 (May–Jun fit) applied to
  the test half. If E1 fails the result stands; no tuning on the test half.
