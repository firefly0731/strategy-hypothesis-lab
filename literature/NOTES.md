# Literature notes

The rules below were read from the full texts. PDFs live outside git.

## Heston, Korajczyk & Sadka (2010, JF): "Intraday Patterns in the Cross-section of Stock Returns"
- **Data**: 1,715 NYSE stocks, 2001–2005, TAQ, 13 half-hour returns per day (09:30–16:00).
- **Method**: Jegadeesh cross-sectional regressions r_i,t = α_k,t + γ_k,t · r_i,t−k, run for each
  lag k with Fama-MacBeth t-stats. Portfolio version: equal-weight deciles sorted on the
  return k half-hours ago, long the top decile and short the bottom.
- **Results**:
  - Reversal at short lags.
  - Positive return responses at lags that are exact multiples of one day (13, 26, …). The
    smallest t-stat over the first week is 9.62.
  - The decile spread at lag 13 (same time next day) is **3.01 bp**, and it stays positive for
    up to 40 days.
- **Mechanism**: systematic institutional trading and fund flows that split orders at the same
  time each day. The pattern is not explained by volume, order imbalance, volatility or spreads.
- **Costs**: the authors say it is "quite difficult to profit from these type of intraday
  strategies without some exogenous desire to trade". The effect is about the size of the
  spread, so it is best used for **execution timing**, not as a standalone strategy.
- **Crypto mapping**: 24/7 trading means 48 half-hours per day, so "same time next day" is
  lag 48. There is daily institutional / ETF flow in US hours. The cross-section is thin
  (≤ 27 coins instead of 1,715).

## Avellaneda & Lee (2010, QF): "Statistical Arbitrage in the U.S. Equities Market"
- **Data**: US stocks with market cap > $1bn, daily EOD data, 1997–2007.
- **Model**:
  - Each stock's return is regressed on factor returns (sector ETFs or PCA eigenportfolios)
    over a **60-day** window.
  - The cumulative residual X_t is fitted with AR(1) / Ornstein-Uhlenbeck:
    κ = −log(b)·252, m = a/(1−b), σ_eq = sqrt(var(ε)/(1−b²)).
  - Only names with fast mean reversion are traded: κ > 252/30, i.e. τ < 30 days.
- **Signal**: s = (X − m)/σ_eq. The paper also has a "modified" version with a drift term.
  - Buy to open if s < −1.25. Sell to open if s > +1.25.
  - Close the short if s < +0.75. Close the long if s > −0.50.
  - Each position is market-neutral: $1 stock, −β$ factor.
- **Costs**: 5 bp per trade (10 bp round trip). Leverage is "2+2".
- **Results (after costs)**:
  - PCA: Sharpe 1.44 over 1997–2007, but only **0.9 over 2003–2007**.
  - ETF: Sharpe 1.1, with a similar decline after 2002.
  - ETF + "trading time" (volume-adjusted returns): Sharpe 1.51 over 2003–2007.
  - The strategy was hit in August 2007, the quant unwind (Khandani & Lo).
- **Mechanism**: contrarian liquidity provision on idiosyncratic moves.
- **Crypto mapping**: use BTC or the PCA first component as the market factor and the 27
  candidate perps as the stock universe. Daily (or 8h) frequency, 365-day year.

## Nagel (2012, RFS): "Evaporating Liquidity"
- **Strategy**: daily reversal with weights ∝ −(R_i,t−k − R_m,t−k) for k = 1..5 (market-adjusted
  returns), scaled to $1 long / $1 short.
- **Result**: the expected return from liquidity provision is highly predictable from the VIX
  and spikes in turmoil, such as 2007–09.
- **Mechanism**: liquidity suppliers who are financially constrained pull back, so the
  compensation for supplying liquidity rises.
- **Crypto mapping**: condition reversal trades on implied or realised vol (DVOL / RV) and
  liquidation-shock days.

## Lou, Polk & Skouras (2019, JFE): "A Tug of War: Overnight Versus Intraday Expected Returns"
- **Result**: across 14 strategies, profits accrue either overnight or intraday, with
  opposite signs. The cause is clientele heterogeneity (intraday professionals vs overnight
  individuals).
- **Crypto mapping**: this is a design principle rather than a strategy. It is consistent with
  our finding that momentum works only in US hours and is absent after 16:00 NY.

## Crypto-specific prior evidence
- Pairs trading with distance / cointegration on 26 Binance coins (Fil & Kristoufek 2020,
  IEEE Access) underperforms benchmarks. Several follow-ups report weak or inconsistent net
  performance.
