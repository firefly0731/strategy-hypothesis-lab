import numpy as np
import pandas as pd

from mm_tick.bayes import Bins, predict
from mm_tick.epnl import day_boot, normal_equations, ridge


def _data(n=20_000, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"a": rng.normal(size=n), "b": rng.uniform(size=n)})
    df.loc[rng.random(n) < 0.05, "b"] = np.nan
    y = 3.0 * (df["a"] > 0.5) - 2.0 * df["b"].fillna(2.0) + rng.normal(size=n)
    return df, y.to_numpy()


def test_normal_equations_match_the_dense_design():
    df, y = _data(3000)
    bins = Bins(df, features=["a", "b"])
    c = bins.codes(df)
    X = np.zeros((len(df), bins.k + 1))
    X[:, 0] = 1
    for j in range(c.shape[1]):
        X[np.arange(len(df)), 1 + bins.offsets[j] + c[:, j]] = 1
    A, b = normal_equations(c, bins, y)
    assert np.allclose(A, X.T @ X) and np.allclose(b, X.T @ y)


def test_ridge_recovers_an_additive_mean_out_of_sample():
    df, y = _data()
    bins = Bins(df.iloc[:10_000], features=["a", "b"])
    A, b = normal_equations(bins.codes(df.iloc[:10_000]), bins, y[:10_000])
    w, b0 = ridge(A, b, 1.0)
    p = predict(bins.codes(df.iloc[10_000:]), w, b0, bins)
    truth = 3.0 * (df["a"].iloc[10_000:] > 0.5) - 2.0 * df["b"].iloc[10_000:].fillna(2.0)
    assert np.corrcoef(p, truth)[0, 1] > 0.97


def test_day_boot_brackets_the_mean():
    rng = np.random.default_rng(0)
    pnl = rng.normal(1.0, 5.0, 5000)
    day = rng.integers(0, 50, 5000)
    m, lo, hi = day_boot(pnl, day, np.random.default_rng(1))
    assert lo < m < hi and lo > 0
