import numpy as np
import pandas as pd

from mm_tick.bayes import Bins, _eta, fit_map, predict
from mm_tick.ceiling import auc


def data(n=40_000, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"a": rng.standard_normal(n), "b": rng.standard_normal(n), "c": rng.standard_normal(n)})
    df.loc[rng.random(n) < 0.05, "b"] = np.nan
    logit = -1.5 + 1.2 * (df["a"] > 0.5) - 0.8 * df["b"].fillna(2.0).clip(-2, 2) ** 2 / 2
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(float)
    return df, y.to_numpy(), logit.to_numpy()


def test_map_recovers_a_nonlinear_signal_and_is_stationary():
    df, y, logit = data()
    bins = Bins(df, features=["a", "b", "c"])
    c = bins.codes(df)
    w, b0, cov = fit_map(c, y, bins, tau=3.0)
    s = predict(c, w, b0, bins)
    assert auc(s, y) > auc(logit, y) - 0.01            # close to the true model's AUC
    # the noise feature carries almost no weight
    j = 2
    sl = slice(bins.offsets[j], bins.offsets[j] + bins.sizes[j])
    assert np.ptp(w[sl]) < 0.15
    # stationarity of the MAP: gradient of the log posterior is ~0
    p = 1 / (1 + np.exp(-_eta(c, w, b0, bins.offsets)))
    g = np.zeros(bins.k)
    for jj in range(c.shape[1]):
        g[bins.offsets[jj]:bins.offsets[jj] + bins.sizes[jj]] = np.bincount(c[:, jj], y - p, minlength=bins.sizes[jj])
    g -= w / 9.0
    assert np.max(np.abs(g)) < 1e-4


def test_strong_prior_shrinks_weights():
    df, y, _ = data()
    bins = Bins(df, features=["a", "b", "c"])
    c = bins.codes(df)
    w_small, _, _ = fit_map(c, y, bins, tau=0.01)
    w_big, _, _ = fit_map(c, y, bins, tau=10.0)
    assert np.abs(w_small).max() < 0.1 < 0.5 < np.abs(w_big).max()
