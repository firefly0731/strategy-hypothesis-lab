# Cash-and-carry (funding rate arbitrage): design

This document fixes the formulas before any code is written. Every number in the reports follows from these definitions. If code and this document disagree, the code has a bug.

## 1. Instruments and data

| Item | Source | Notes |
|---|---|---|
| Perp 1h klines | `data.binance.vision/data/futures/um/monthly/klines/{SYM}/1h/` | Archive starts 2020-01. Earlier months come from REST `fapi/v1/klines` and are cached the same way. |
| Spot 1h klines | `data.binance.vision/data/spot/monthly/klines/{SYM}/1h/` | Timestamps after 2025 are in µs; `_to_utc` detects the unit. |
| Mark price 1h klines | `.../futures/um/monthly/markPriceKlines/{SYM}/1h/` | Used for the liquidation check only. |
| Funding | `.../futures/um/monthly/fundingRate/{SYM}/`, plus REST `fapi/v1/fundingRate` for months that are not archived | All settlement timestamps are used as published, so 8h, 4h and 1h intervals are all handled. |
| T-bills | FRED `DTB3` CSV (`fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3`) | If the download fails, the run stops. There is no silent fallback. `--no-tbill` skips the comparison explicitly. |

- **Grid.** A kline with `open_time` T becomes a bar with close time T + 1h on a regular UTC hourly grid. Every price used for a bar is that bar's close.
- **Funding timing.** A settlement at time s belongs to the bar (t_{j−1}, t_j], which is the first bar close ≥ s. Two settlements in one bar are summed. Funding is paid on the position held during that bar, meaning the position after the trades at t_{j−1}. Trades at t_j happen after the settlement at t_j.
- **Funding price.** The funding notional uses the perp close of bar t_j, not the mark price, which the archive does not have. On BTC/ETH the 1h close and the mark at the settlement minute differ by a few bp. The effect on funding PnL is second order (rate × gap).
- **Multiplier contracts.** `1000PEPEUSDT`, `1000000MOGUSDT`, `1MBABYDOGEUSDT` and similar pair with spot `PEPEUSDT`, and so on. Perp prices are divided by the multiplier k (1e3, 1e4, 1e5, 1e6, or "1M" = 1e6), so both legs are quoted per coin.

## 2. One sleeve

The state of one sleeve:
- `qs`: spot coins held.
- `qp`: short perp size in coins (≥ 0, so the position is −qp).
- `M`: futures account equity, which is collateral plus unrealised PnL, in USDT.

At prices S (spot) and F (perp):

```
sleeve equity     e  = qs·S + M
effective lev     L  = qp·F / M          (M ≤ 0  →  L = +inf)
```

**Why L uses M and not e.** Only the futures account backs the short. Spot coins sit in the spot wallet and are not cross-margined. Liquidation therefore depends on qp·F against M. The spec's own split ($0.25 margin carrying a 3× short of $0.75) also defines leverage this way.

**Target state** (the spec's rule: per $1, $0.75 spot and $0.25 margin at 3×):

```
qs* = 0.75·e'/S        qp* = 3·(0.25·e')/F = 0.75·e'/F        M* = 0.25·e'
```

Spot and short notional are equal, so the sleeve is delta neutral in USDT at the trade. Any quantity mismatch afterwards comes from basis.

**Leverage drift.** Take a price move x on both legs with no basis change. Then L = 0.75(1+x) / (0.25 − 0.75x).
- L = 5 at x = +11.1%.
- L = 2 at x = −11.1%.

The band is checked at every bar close. A sleeve is rebalanced to the target when L < 2, L > 5 or M ≤ 0.

### Costs

| | Fee | Slippage per side | Total rate per $ traded |
|---|---|---|---|
| Spot | 0.10% | 0.02% | c_s = 0.0012 |
| Perp | 0.05% | 0.02% | c_p = 0.0007 |

There is no fee discount, and idle cash and margin earn 0%. Slippage is charged as a cost on traded notional. Positions are marked at the bar close, so slippage shows up immediately as a loss.

### Rebalance and entry with costs paid out of the sleeve

Let a = qs·S and b = qp·F before the trade. The post-trade equity e' solves

```
e' = e − c_s·|0.75e' − a| − c_p·|0.75e' − b|
```

- The right-hand side is a contraction with slope ≤ 0.75(c_s + c_p) < 0.0015, so fixed-point iteration from e' = e converges to machine precision in fewer than 10 steps.
- **Entry** from cash C: a = b = 0, M = C, so e' = C / (1 + 0.75(c_s + c_p)).
- **Exit:** proceeds = a(1 − c_s) + M − c_p·b go to portfolio cash.
- A full round trip costs 2 × 0.75 × (c_s + c_p) = 0.285% of the sleeve.

### Per-bar update, in this order

1. **Liquidation check, using the intrabar mark-price high H_t.** Binance liquidates on the mark price, not the last price.
   - Source: `.../futures/um/monthly/markPriceKlines/{SYM}/1h/`.
   - Where the mark kline is missing (before 2020-01, or an hour absent from the archive), the proxy is spot high × (perp close / spot close) for that bar. The report counts these bars.
   - Last-price wicks are reported but not used. ETHUSDT on 2020-03-13 traded at 323 with mark 119; BTCUSDT on 2021-07-26 traded at 48,169 with spot 38,300.
   - The first build used the last-price high. It liquidated both legs on those two wicks, and the 2020 and 2021 returns fell to +3% and +18%. The worst futures equity in the bar is M_{t−1} − qp(H_t − F_{t−1}). If that is ≤ mmr·qp·H_t, the short is liquidated:
   - Liquidation price: P_liq = (M_{t−1} + qp·F_{t−1}) / (qp(1 + mmr)).
   - perp PnL = −qp(P_liq − F_{t−1}).
   - The remaining maintenance margin mmr·qp·P_liq is forfeited and recorded as `liq_loss`.
   - Then qp = 0 and M = 0. The spot leg stays.
   - mmr: BTC 0.4%, ETH 0.5%, every other coin 1.0%. These are Binance tier-1 levels, fixed in advance.
2. **Mark to market:**
   - spot_pnl = qs(S_t − S_{t−1})
   - perp_pnl = −qp(F_t − F_{t−1})
   - M += perp_pnl
3. **Funding:** funding = qp·F_t·r_t, and M += funding.
   - r > 0 means longs pay shorts, so the short receives it.
   - r < 0 means the short pays.
4. **Trades at the close of t:** exits, band rebalances, entries. Fees and slippage reduce the equity in the order described above.

### Portfolio identity, asserted at every bar

```
E_t = cash_t + Σ_sleeves (qs·S_t + M)
E_t − E_{t−1} = spot_pnl + perp_pnl + funding − fee − slippage − liq_loss      (|err| ≤ 1e-9·max(1, E))
```

Other assertions at every bar:
- Prices, rates, positions and equity are finite.
- Every settlement maps to exactly one grid bar.
- DTB3 dates are UTC calendar days.

## 3. Missing data and delistings

- **Outages.** If either price of a held name is missing in a bar, the sleeve is held. Its legs are marked at the last valid price, so the PnL arrives when trading resumes. No band trade happens in that bar.
- **Liquidation check during an outage.** It is skipped when the high is missing.
- **Delistings.** If a leg has no price data after bar t (its last valid bar), the sleeve is closed at t at the last prices, with full costs.
- **Entry requirement.** Both raw prices must be present at the decision bar.

## 4. Strategies

### A. Fixed BTC + ETH (spec)

- **Sleeves.** Two sleeves of 50% each: BTCUSDT and ETHUSDT. They stay on for the whole run, with the band rebalance only.
- **Start.** Entry at the 2019-11-28 00:00 UTC close. The ETHUSDT perp started trading on 2019-11-27 at 07:00 UTC, and its first hour traded between 125 and 146. Waiting for the first full UTC day costs two settlements against the video's start of 2019-11-27.
- **End.** Everything is closed at the 2026-10-19 00:00 close, which ends 2026-10-18 inclusive, with exit costs.

### B. Greedy top-10 (spec)

- **Universe.** Every USDT perp with a kline archive, delisted names included, and with a matching spot USDT pair. TradFi and index contracts are dropped.
- **Eligibility at decision time t:**
  - At least 30 days of price history on both legs.
  - A 30-day median hourly quote volume of at least $100k on both legs.
  - Raw prices on both legs at t.
- **Decision.** Every day at 00:00 UTC, right after the 00:00 settlement.
- **Signal.** Sum of funding rates settled in (t − 24h, t]. This is daily carry, so 4h and 8h interval names are comparable.
- **Selection.** The top 10 by signal, ties broken by symbol name. Names that leave the top 10 are exited. New names are entered at min(E/10, cash / n_new) each. Names that stay keep their sleeve, with band rebalance only.
- **Start.** Decisions begin when the first names pass the 30-day history rule after the 2020-01 archive start.

### C. Greedy, improved (pre-committed, one run)

The rules below are fixed before any result is seen:
- **Universe.** Each name needs at least 365 days of history on both legs. Of those, only the top 40 by 30-day median perp quote volume are eligible, and that median must be at least $1M per hour. Spot must have at least $100k per hour.
- **Signal.** Average daily carry over the trailing 3 days, i.e. the funding sum over (t − 3D, t] divided by 3.
- **Cost threshold for a new entry.** The signal must be at least 0.0543% per day. At that rate, 7 days of funding on the 0.75 short covers one round trip: 0.75 × 7 × signal ≥ 0.285%.
- **Rank buffer.** A held name stays while it ranks in the top 20 and its signal is > 0. Empty slots are filled with the best new names above the threshold.
- **Settlement timing.** Decisions run at 00:00 UTC after the settlement, so an exit never gives up a settlement it was waiting for.

### D. Liquidation risk check

Strategies A to C all run with the intrabar liquidation check (§2, step 1). The run also reports:
- the number of liquidations,
- the largest one-hour high-over-close move,
- the minimum futures equity relative to the notional.

## 5. Benchmarks and metrics

**T-bills.** DTB3 is forward-filled to calendar days. The daily accrual is r/100/365 (treating the discount rate as a yield). The report shows the yearly average rate and the compounded return for the same window as the strategy.

**Metrics:**
- total return, CAGR, MDD (hourly equity)
- Sharpe and Sortino (daily, ×√365)
- rebalances, fees, slippage, liquidation loss
- share of settlements with a negative rate (A: BTC and ETH)
- the largest |F/S − 1| basis gap

**Decomposition:**
- funding
- hedge or basis PnL (spot_pnl + perp_pnl)
- fees + slippage + liquidation loss
- cross-check: the parts sum to the total, and this is asserted

## 6. Not modelled (stated in every report)

- Exchange insolvency, default or withdrawal freeze (for example FTX, November 2022). Every dollar sits on one venue.
- Taxes, and keeping records of thousands of 8-hour funding events per jurisdiction.
- Spot borrow, transfer delays between the spot and futures wallets (assumed instant and free), funding at the mark price instead of the close, and queue position or market impact beyond the 2 bp slippage.
