# Idea log

Every idea tested on this strategy is listed here, adopted or not. The number of variants
tried feeds a deflated-Sharpe / multiple-testing correction at the end.

The base is the paper's noise-band rules on Binance USDT-M perps, US session 09:30–16:00
NY, `maker_chase` execution, BTC+ETH+SOL equal weight. The hold-out set is BNB+XRP+DOGE.

| # | Idea | Variants tried | Result | Decision |
|---|------|----------------|--------|----------|
| 1 | Session definition: US hours vs UTC day | 2 | UTC day loses money on every symbol. US hours positive on BTC/ETH/SOL | US hours |
| 2 | Execution: taker / maker_skip / maker_chase / maker_in_taker_out | 4 | maker_chase is best. maker_skip misses the big trend days | maker_chase |
| 3 | Parameter grid (lookback × interval × exec × cost filter) via CPCV | 120 | PBO 0.16 (basket). The paper's defaults are as good as the selection | keep paper defaults |
| 4 | Markov-chain Monte-Carlo noise bands (1 vs 3 states, q 0.70–0.90) | 8 | Every MC band is worse than the paper σ. CPCV picks paper σ 45/45 | rejected |
| 5 | Entry cutoff × VWAP confirmation | 20 | Sharpe 0.93 → 1.22 (discovery). Hold-out −0.16 → 0.27 (diff t 2.9). WF picks 14:00/0.6 from 2023 on | **adopted** (14:00, 0.6σ) |
| 6 | Earlier session anchor (06:00–09:00 NY) | 10 | Worse the earlier it starts. Pre-open entries are −17…−27 bp | rejected |
| 7 | Sizing schemes × weights × drawdown throttle | 20 | rv24 ≈ risk-per-trade > paper (t ≤ 0.5). The throttle cuts bootstrap tail MDD −23% → −16% | **adopted** (rv24, equal, dd 15%) |
| 8 | Hold past 16:00 (6 horizons × 3 post-close rules) | 16 | Discovery Sharpe 1.22 → 1.02–1.11. Post-close P&L ≈ 0 bp on BTC/ETH/SOL. CPCV picks 16:00 40/45 | rejected |
| 9 | Order-flow confirmation (taker-buy imbalance: since open / last 30 min / z-score) | 6 (attribution only) | No monotonic relation in either set. 80–95% of breakouts already go with the flow, so the feature is redundant with price. Weak post-hoc hint that the *least* aligned quintile is best (exhaustion?), not pursued because of snooping | rejected |

Total variants tried so far: 206.
