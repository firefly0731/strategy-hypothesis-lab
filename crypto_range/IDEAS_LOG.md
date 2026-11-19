# Idea log (crypto_range)

Every variant is counted, including ones that lost, so a multiple-testing correction can be
applied later. Unit notional, one position per symbol. Discovery = BTC/ETH/SOL, hold-out =
BNB/XRP/DOGE, 2021-01..2026-11. "net" is after fees, slippage and funding. Numbers come from
`results/report.txt`.

| # | Idea | Variants | Result (primary, discovery / hold-out) | Decision |
|---|------|----------|----------------------------------------|----------|
| A | Pre-open (07:00–09:30) noise-band fade, exit at the anchor or at 09:30 | 8 × 2 exec = 16 | gross_mid +1…+4 bp; net maker −2.7 / −2.6 bp (t −1.5 / −1.1), taker −7.9 / −6.6 bp. Sharpe < 0 on the whole grid. PBO 0.29 | rejected |
| B | US-session VWAP ± kσ fade, VR20<1 filter | 6 × 2 = 12 | gross is NEGATIVE on discovery (−8 to −10 bp): moves away from VWAP keep going (this is the momentum effect). Hold-out maker +1.2 bp (t 0.25). Corr. with momentum −0.34 | rejected |
| C | Off-US hours (20:00–08:00) rolling-120 z-band fade | 6 × 2 = 12 | gross ≈ −1…−3 bp, ~25k trades, net maker −6 bp (t −11). Fees dominate | rejected |
| D | 30-min reversal in the US session (fade \|r30\| > xσ, hold 30/60) | 8 × 2 = 16 | gross_mid −1.2 bp (disc). Positive only in 2021. Note: lag-1 autocorrelation of consecutive within-session 30-min returns is ≈ 0 (BTC −0.04…+0.05 by year), so the −0.09 premise could not be reproduced in this setup | rejected |
| E | 08:30 macro-spike fade (08:30→08:45 move > xσ) | 6 × 2 = 12 | exit 09:30: net −12 / −16 bp. Exit 10:00: +8 / +14 bp (maker, t 1.6 / 2.3). The move CONTINUES until 09:30 and then reverts after the open → led to F | rejected (as specified) |
| scan | Descriptive: −sign(pre-open move) × 09:30→10:00/10:30 return, 3 anchors × 2 horizons × 3 thresholds, all 6 symbols, no costs | 18 cells | +14…+33 bp for \|z\|>1 on every symbol; mainly 2021–2023 | motivated F (hold-out contaminated) |
| F | **POST-HOC.** US-open fade of the pre-open move (anchor 08:30, \|z\|>1, entry 09:30, exit 10:00) | 12 × 2 = 24 | maker net +13.8 / +18.6 bp (t 4.4 / 5.0), Sharpe 1.26 / 1.50, MDD −9% / −8%. Taker +6.8 / +11.1 bp. PBO 0.07. **But the edge has decayed**: discovery maker net 2021–23 +28.6 bp, 2024–26 +0.1 bp (2024 −0.6, 2025 +5.1, 2026 −4.2 bp/trade); hold-out 2024–26 +10.7 bp (t 2.6). Corr. with momentum ≈ 0.00; 50/50 Sharpe 1.34 → 1.90 (2022–26) but it does NOT help in 2024/2026, the years momentum is weak. It earns most on trend days, not quiet days | needs more work: paper-trade or forward-test; do not adopt as a "range" hedge |

Total: 68 (A–E) + 24 (F) = 92 backtested variants, plus 18 descriptive scan cells.
Pre-registered selection rule (best discovery maker Sharpe among A–E) picks A, which loses
(Sharpe −0.38).
