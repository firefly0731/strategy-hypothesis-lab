import numpy as np
import pandas as pd

from crypto_intraday_momentum.universe import selection_masks


def _panel(seed=0, n=900, syms=("AUSDT", "BUSDT", "CUSDT", "DUSDT", "BTCUSDT")):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    out = {}
    for k, s in enumerate(syms):
        d = pd.DataFrame({"u": rng.normal(0.0002 * (k - 2), 0.01, n), "r": rng.normal(0, 0.01, n),
                          "maxlev": 1.0, "qv": rng.uniform(50e6, 500e6, n),
                          "vr_num": rng.uniform(0, 2, n), "vr_den": 1.0, "tradable": True}, index=idx)
        if s == "DUSDT":
            d.loc[d.index[:400], ["u", "r", "maxlev", "qv", "vr_num", "vr_den"]] = np.nan   # listed later
        out[s] = d
    return out


def test_selection_uses_only_prior_sessions():
    p0 = _panel()
    T = p0["AUSDT"].index[600]
    p1 = {s: d.copy() for s, d in p0.items()}
    rng = np.random.default_rng(5)
    for d in p1.values():
        m = d.index >= T
        d.loc[m, ["u", "qv", "vr_num"]] = rng.normal(0, 1, (m.sum(), 3))
    m0, m1 = selection_masks(p0), selection_masks(p1)
    for k in m0:
        a, b = m0[k].loc[: T], m1[k].loc[: T]          # sessions up to and including T
        pd.testing.assert_frame_equal(a, b, check_names=False)


def test_selection_respects_history_and_month_hold():
    p = _panel()
    m = selection_masks(p)["all_liquid"]
    late = p["DUSDT"]["u"].first_valid_index()
    pos = m.index.get_loc(late)
    assert (m["DUSDT"].iloc[: pos + 250] == 0).all()     # needs 250 sessions of history
    months = m.index.to_period("M")
    for _, g in m.groupby(months):
        assert (g.nunique() <= 1).all()                  # held constant within a month
