import numpy as np
import pandas as pd
import pytest

from mm_tick import events as E

N_DAYS = 32


def synth_grid(seed=0, n_days=N_DAYS):
    rng = np.random.default_rng(seed)
    n = n_days * E.DAY_S
    lp = np.cumsum(rng.standard_t(3, n) * 2e-5)
    return {"start_ms": 0, "px": 100 * np.exp(lp), "buy": np.zeros(n), "sell": np.zeros(n),
            "cnt": np.ones(n, dtype=np.int64)}


@pytest.fixture(scope="module")
def base():
    g = synth_grid()
    zs = E.zscores(g, 60)
    k = E.thresholds(zs["z"], zs["n_days"])
    return g, zs, k


def test_zscores_and_thresholds_use_only_the_past(base):
    g, zs, k = base
    rng = np.random.default_rng(1)
    for cut_day, cut_sec in ((29, 4000), (30, 50000)):
        i0 = cut_day * E.DAY_S + cut_sec
        g2 = dict(g, px=g["px"].copy())
        g2["px"][i0 + 1:] *= np.exp(np.cumsum(rng.normal(0, 1e-3, len(g2["px"]) - i0 - 1)))
        zs2 = E.zscores(g2, 60)
        k2 = E.thresholds(zs2["z"], zs2["n_days"])
        same = np.isfinite(zs["z"][: i0 + 1])
        assert same.any()
        np.testing.assert_array_equal(zs["z"][: i0 + 1][same], zs2["z"][: i0 + 1][same])
        np.testing.assert_array_equal(k[: cut_day + 1], k2[: cut_day + 1])


def test_thresholds_are_quantiles(base):
    _, zs, k = base
    d = 25
    az = np.abs(zs["z"][(d - E.LOOKBACK_D) * E.DAY_S: d * E.DAY_S])
    az = az[np.isfinite(az)]
    for j, q in enumerate(E.QS):
        assert k[d, j] == pytest.approx(np.quantile(az, q), rel=0.01)


def test_breaks_rearm_rule():
    z = np.array([0, 3, 3, 0.5, 3, 0, 0, 0, 3, 4], float)
    x = np.sign(z) + 0.0
    k = np.full(len(z), 2.0)
    # event at 1; |z| falls below k at 3, but only 2 s later (< L=4); re-arms at 5 -> event at 8
    assert E._breaks(z, x, k, 4).tolist() == [1, 8]


def test_outcomes_prices(monkeypatch):
    # trades every 100 ms: price rises 1 bp per trade (multiplicatively)
    t = np.arange(0, 400_000, 100, dtype=np.int64)
    px = 100 * np.exp(np.arange(len(t)) * 1e-4)
    df = pd.DataFrame({"t": t, "px": px})
    monkeypatch.setattr(E, "_load_tp", lambda sym, mo, base, until_ms=None:
                        ((t - base).astype(np.uint32), px.astype(np.float32)))
    ev = pd.DataFrame({"i": [9], "sign": [-1], "absz": [5.0], "k": [3.0]})
    out = E.outcomes("X", ["1970-01"], 0, ev, delays=(0, 250), horizons=(10,))
    # detection T = 10_000 ms. d=0: entry trade at 10_000 (index 100), exit last trade <= 20_000
    # (index 200): 100 trades up -> continuation for a short = -100 bp
    assert out["g_d0_h10"][0] == pytest.approx(-100, abs=1e-3)
    # d=250: entry first trade >= 10_250 (index 103), exit <= 20_250 (index 202): 99 bp
    assert out["g_d250_h10"][0] == pytest.approx(-99, abs=1e-3)


def test_cost_bp():
    assert E.cost_bp(0.1, 60000) == 5.0
    assert E.cost_bp(0.01, 1.0) == pytest.approx(4 + 50)
