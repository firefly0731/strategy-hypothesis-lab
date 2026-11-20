"""Synthetic fixtures for unit tests only (deterministic seeds). They check mechanics; no
statistic computed on them is a research result."""
import numpy as np
import pandas as pd
import pytest

from crypto_dirty_carry.data import MarketData

# (beta, rate per 8h settlement). Shorts are higher beta on average than longs (raw book is short
# beta) but betas overlap across the sides, so a dollar- and beta-neutral re-weighting exists.
HIGH = {"A": (1.6, 3e-4), "B": (0.9, 2.5e-4), "C": (1.3, 2e-4)}
LOW = {"D": (1.2, -1.0e-4), "E": (0.6, -1.5e-4), "F": (0.8, -2e-4)}
BTC = "BTCUSDC"


def make_data(n_days=80, seed=0, bar="1h", noise=0.004) -> MarketData:
    rng = np.random.default_rng(seed)
    step = pd.Timedelta(bar)
    n = int(pd.Timedelta(days=n_days) / step)
    idx = pd.date_range(pd.Timestamp("2024-01-01", tz="UTC") + step, periods=n, freq=step)
    spec = {BTC: (1.0, 5e-5), **HIGH, **LOW}
    mkt = rng.normal(0, 0.006, n)
    rets = {s: b * mkt + (0 if s == BTC else 1) * rng.normal(0, noise, n) for s, (b, _) in spec.items()}
    close = pd.DataFrame({s: 100 * np.exp(np.cumsum(r)) for s, r in rets.items()}, index=idx)
    settle = pd.date_range(idx[0].ceil("8h"), idx[-1], freq="8h")
    rows = []
    for s, (_, rate) in spec.items():
        jitter = rng.normal(0, abs(rate) * 0.1, len(settle))
        rows.append(pd.DataFrame({"time": settle, "symbol": s, "rate": rate + jitter}))
    funding = pd.concat(rows, ignore_index=True)
    factors = pd.DataFrame({"BTC": close[BTC].pct_change(fill_method=None)}, index=idx)
    qv = pd.DataFrame(1e6, index=idx, columns=close.columns)
    return MarketData(close=close, funding=funding, factors=factors, quote_volume=qv)


@pytest.fixture
def data():
    return make_data()
