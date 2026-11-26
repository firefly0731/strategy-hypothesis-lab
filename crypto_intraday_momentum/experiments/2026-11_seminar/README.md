# 2026-11 seminar and follow-up experiments

Scripts behind the seminar deck (`docs/seminar_2026-11/`) and IDEAS_LOG #12–#15. Each script takes an output
directory as its first argument. Run them from the repo root with `PYTHONPATH=.`. Small result files are
committed here. The pickles they write (`R_*.pkl`, `IV_*.pkl`, ~35 MB each) are not; regenerate them.

| script | what | output |
|---|---|---|
| `extract.py OUT` | Deck numbers for the production configuration (rv24, equal weight, 25% vol target, 3x cap, dd 15%), discovery and hold-out, maker_chase and taker | `deck.json` |
| `cpcv_deck.py OUT SYM`, then `cpcv_deck.py OUT` | CPCV over the IDEAS #5 grid (5 cutoffs × 4 VWAP k), N=10, k=2, embargo 30, 1x unit size. One symbol per process keeps memory low | `R_<SYM>.pkl`, `cpcv.json` |
| `interval_bt.py OUT SYM`, then `interval_bt.py OUT` | IDEAS #12: decision interval 30 / 15 / 5 min | `IV_<SYM>.pkl`, `interval.json` |
| `split_bt.py OUT` | IDEAS #13: entries every E min, exits on the 30-min grid. It patches a copy of `run_backtest` in memory and asserts that 30/30 reproduces the production trades exactly. Needs `IV_*.pkl` | `split.json` |
| `split_pair.py OUT` | Paired daily-return t-test of 15/30 vs 30/30 | stdout |
| `reentry.py OUT` | IDEAS #14: P&L by entry ordinal within a symbol-day, and entry caps. Needs `IV_*.pkl` | stdout |
| `premarket/` | IDEAS #15 (`study.py`, results in `out.txt`) and side studies for the "premarket" slide: SPY/QQQ (`etf_momo.py`), NQ/ES 24h vs regular hours (`fut_24h.py`), futures signal traded in crypto (`fut_signal_crypto.py`), weekends (`weekend.py`). Yahoo data comes from `fetch*.py` and is not committed | stdout |

The side studies in `premarket/` other than `study.py` have no IDEAS_LOG row yet. Their printed results were
shown in the seminar session but not saved. Re-run them before you cite them.

`weekend.py` also computes the per-time-of-day t on the "수익원 ① 시간대" slide:
t = mean(net bp) / std × √n over pooled trades. That t is not clustered by day, so it overstates significance.
