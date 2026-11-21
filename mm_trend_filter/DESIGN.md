# MM trend filter: stage 1 (1-minute bars)

Own hypothesis (user, 2026-11-21). A passive two-sided maker loses money mainly when a
trend builds and its inventory piles up on the wrong side. The intraday-momentum noise-band
break (`crypto_intraday_momentum`) marks trend periods. Question: **does pulling quotes while
the band is broken cut the maker's losses by more than it cuts its earnings?**

Stage 1 is a cheap screen on 1-minute klines. It cannot model queue position or sub-second
adverse selection (the 1 s markout of about −0.5 bp measured in `research/mm/06`). It only
measures the inventory loss from trends. If stage 1 fails, the idea stops here.

Everything below was fixed before any result was computed.

## Data
- Binance USDⓈ-M USDT perps, 1-minute klines, 2021-01-01 .. 2026-11-18.
- Discovery: BTCUSDT, ETHUSDT, SOLUSDT. Hold-out: BNBUSDT, XRPUSDT, DOGEUSDT, run only after
  the discovery result is written down, with nothing changed.
- The USDT price path stands in for the USDC-M book the maker would actually quote on.
- Sessions: NYSE days 09:30–16:00 New York (390 bars), the same as the momentum strategy.
  The maker quotes only inside the session and is flat at the start and end of each session.

## Maker model
- Unit = notional 1 at the session open (u = 1/open coins). Inventory cap Q = 5 units each way.
- Quotes are set at the close of bar k−1 and rest during bar k:
  - **anchor** (primary, the user's description): anchor A = price of the last fill, reset to
    the close C[k−1] whenever inventory is 0. The bid is the highest A(1−δ)^n (n ≥ 1) that is
    below C[k−1], and the ask is the lowest A(1+δ)^n above C[k−1]. After a buy at p, the next
    ask is p(1+δ) and the next bid p(1−δ).
  - **mid** (sensitivity): bid C[k−1](1−δ), ask C[k−1](1+δ).
- Fill rule: the same as `crypto_grid/neutral.py`. A buy fills only if the bar trades
  through it (low < bid), a sell only if high > ask, at the quote price. Each side fills at
  most once per bar, so results do not depend on the intrabar path. Both sides can fill in
  the same bar.
- Fees: maker 0 bp (the USDC-M premise from `research/mm/06` §7). Taker 4 bp + 1 bp slippage
  for any forced flatten and for the session-end flatten.
- Funding is ignored (at most one settlement per session, on a small inventory).
- δ ∈ {5, 10, 20} bp. **Primary: anchor, δ = 10 bp.**

## Signal (unchanged adopted configuration)
`compute_signals` with lookback 14 and a 30-minute interval. At decision minute m
(30, 60, …, 360) the state is `up` if px > UB, `down` if px < LB, otherwise `inside`
(NaN bands count as inside). The state governs bars m .. m+29. Bars 0..29 count as inside.
Only bars < m are used, which the research code's perturbation tests already guarantee.

## Policies
| name | rule while the state is up/down |
|---|---|
| none | quote always |
| band_off | no quotes; existing inventory is held |
| band_flat | no quotes; inventory is flattened at the window's first bar open (taker) |
| band_skew | up: no ask (stop getting short into the rally); down: no bid |
| sticky_off | after the first break in the session, no quotes for the rest of the session |
| vol_off | control signal: no quotes when the realised path length of the last 30 bars (Σ\|Δlog C\|) exceeds 1.5× its mean at the same minute over the previous 14 sessions |
| random_off | control: each window is off with probability p = band_off's off share for that symbol, inventory held; 200 seeds |

## Pre-committed criteria (anchor, δ = 10 bp, discovery symbols pooled)
- **C1, windows are toxic:** under `none`, the mean PnL of broken windows is below that of
  inside windows, and the 95% session-block bootstrap CI of the difference excludes 0.
- **C2, better than quoting less at random:** the improvement of `band_off` over `none`
  exceeds the 95th percentile of the improvements from `random_off`.
- **C3, better than a plain volatility filter:** the improvement of `band_off` (or the best band
  policy) exceeds that of `vol_off`.
- **C4, not one year:** the band_off improvement is positive in at least 4 of the 6 years.

Stage 2 (aggTrades, queue-aware) goes ahead only if C1, C2 and C4 pass on discovery and
the sign of the improvement holds on the hold-out. If C3 fails, the plain volatility
filter is the better candidate and stage 2 tests that one instead.

Statistics: per-session PnL; the CI is a moving-block bootstrap over sessions (block 20,
2,000 draws). Every headline number is also computed as a mean of per-year means.
Variants counted for IDEAS_LOG: 2 quote modes × 3 δ × 6 policies = 36.

## Addendum (2026-11-21, written after the discovery result and before the hold-out run)
Discovery failed C1 and C2: pausing quotes while holding inventory (`band_off`) did no better
than pausing at random. The post-hoc diagnostics (`diag.py`) added matched random controls
for `band_flat` and `band_skew`, plus a within-session bar shuffle. Two post-hoc hypotheses
are now fixed and are tested on the hold-out symbols with nothing changed:
- **H-a:** anchor, δ = 10 bp: `band_flat` improvement > p95 of the matched `random_flat`.
- **H-b:** mid, δ = 10 bp: `band_skew` improvement > p95 of the matched `random_skew`
  (random windows, random direction).
The original C1–C4 are also rerun on the hold-out as pre-committed.
Diagnostic variants added: 2 policies × 6 configs = 12 (running total 48).
