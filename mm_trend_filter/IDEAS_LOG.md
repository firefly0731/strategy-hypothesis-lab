# MM trend filter: ideas log

Own hypothesis (user, 2026-11-21): use the intraday-momentum band break as a risk signal for a
passive two-sided maker; cancel quotes while it is on. Spec and pre-committed criteria: DESIGN.md.
Variants tried: 48 (36 pre-committed + 12 post-hoc diagnostics).

| # | Test | Result | Verdict |
|---|---|---|---|
| 1 | Pause quotes, hold inventory (`band_off`), anchor δ=10 bp, discovery BTC/ETH/SOL | +25 bp/session vs none (CI −4..61). Broken windows −22.5 vs inside −13.8 bp (CI of diff −18.5..+1.0). Random pausing at the same share: +85 (p95 119) | **rejected** (C1, C2 fail) |
| 2 | Same, hold-out BNB/XRP/DOGE | −10 bp (CI −75..51); C1, C2, C4 fail | **rejected** |
| 3 | Post-hoc H-a: flatten on break (`band_flat`), anchor δ=10 | discovery +146 vs matched random p95 121; hold-out +36 vs p95 44 | **rejected on hold-out** |
| 4 | Post-hoc H-b: lean with the trend (`band_skew`), mid δ=10 | discovery +257 vs p95 148; hold-out +131 vs p95 133 | **rejected on hold-out** (borderline) |
| 5 | Shuffle test (bars permuted within session) | The baseline loss stays (anchor δ=10: −616 real vs −359 shuffled; mid: −587 vs −641) | The 1-minute model's level is dominated by the trade-through fill rule; only differences between policies are informative |

Notes
- Code review (separate reviewer): no result-changing bugs; 4 low items (anchor unchanged on a
  same-bar double fill, a fixed bootstrap seed, shuffled open off by <0.002%, a theoretical
  divide-by-zero in the C1 bootstrap).
- Stage 2 (aggTrades, queue-aware) is not justified by these results.
