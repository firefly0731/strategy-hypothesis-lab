# Strategy research protocol

This protocol applies to every new strategy idea in this repository, for any asset class.

## 1. Literature first
- Start from published work: papers (SSRN, arXiv, NBER, journal versions), practitioner
  research (Quantpedia, Concretum, Alpha Architect, AQR, Robot Wealth), or a source the user
  provides. An idea with no source is labelled **"own hypothesis"** and tracked separately.
- The source may come from any asset class. What has to carry over is the **mechanism**.
- For each candidate, record:
  - the mechanism: who is on the other side of the trade and why they accept a loss;
  - the data, sample and frequency used;
  - the exact rules (entry, exit, sizing, costs);
  - the headline results and the cost assumptions behind them;
  - evidence after publication or out of sample, and any independent replications or critiques;
  - whether the mechanism exists in crypto perps (24/7, funding, liquidations, ETF flows in
    US hours, retail leverage, thin cross-section).
- Save notes in `literature/NOTES.md`. Keep the downloaded PDFs out of git.

## 2. Faithful replication before adaptation
- First implement the paper's rules **as written**: same parameters, same cost assumption.
  Then report how close the crypto numbers come to the paper's own.
- Change one thing at a time after that, and log every change.

## 3. Validation gates (all required before adoption)
- Look-ahead safety: decisions use closed bars only, maker fills require a trade-through,
  and every filter or statistic uses prior data only. A perturbation test is required for
  every new signal.
- Costs: Binance VIP0 fees (maker 2 bp, taker 5 bp), 1 bp taker slippage, funding.
  Report results gross and net.
- Discovery / hold-out split by symbol, plus a time split (walk-forward). Parameters are
  never chosen on the hold-out.
- CPCV PBO over any parameter grid. The grid stays small and is fixed before the run.
- Yearly breakdown. Results must not depend on a single year.
- Correlation with, and combination value for, the existing momentum strategy.

## 4. Numerical hygiene
- Compute every headline statistic two independent ways, for example a pooled estimate and an
  average of per-period estimates. Investigate any disagreement before reporting.
  (Lesson: a mean of per-session correlations over 12 pairs is biased by about −1/12.)
- State sample sizes and t-statistics next to every mean.

## 5. Bookkeeping
- Every idea and the number of variants tried go into the relevant `IDEAS_LOG.md`, including
  rejected ones. The running total of variants feeds a multiple-testing (deflated Sharpe)
  correction before any strategy goes live.
