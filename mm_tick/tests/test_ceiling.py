import numpy as np
import pandas as pd

from mm_tick.ceiling import _ND, _ppf, auc


def test_synthetic_score_has_the_target_auc_and_ic():
    rng = np.random.default_rng(0)
    n = 200_000
    y = (rng.random(n) < 0.13).astype(float)
    for a in (0.55, 0.7, 0.9):
        s = y * np.sqrt(2) * _ND.inv_cdf(a) + rng.standard_normal(n)
        assert abs(auc(s, y) - a) < 0.01
    pnl = rng.standard_t(3, n)
    z = _ppf((pd.Series(pnl).rank().to_numpy() - 0.5) / n)
    for c in (0.1, 0.3):
        g = c * z + np.sqrt(1 - c * c) * rng.standard_normal(n)
        ic = np.corrcoef(pd.Series(g).rank(), pd.Series(pnl).rank())[0, 1]
        assert abs(ic - c) < 0.02
