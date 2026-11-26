"""CPCV (N=10 groups, k=2 test groups, embargo 30 sessions -> 45 splits, 9 OOS paths) over the
entry-rule grid (5 cutoffs x 4 VWAP k = 20 combos), maker_chase, BTC+ETH+SOL equal-weight basket,
and the hold-out basket BNB+XRP+DOGE."""
import json, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from crypto_intraday_momentum.run_improve import _one
from crypto_intraday_momentum.cpcv import run_cpcv
PPY = 252
OUT = sys.argv[1]
SETS = {"disc": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "hold": ["BNBUSDT", "XRPUSDT", "DOGEUSDT"]}
if __name__ == "__main__":
    if len(sys.argv) > 2:  # stage: one symbol per process, keeps peak memory low
        sym = sys.argv[2]
        _, r, _ = _one(sym, "2021-01", "2026-10", "maker_chase")
        r.to_pickle(f"{OUT}/R_{sym}.pkl"); print("saved", sym, r.shape); sys.exit(0)
    R = {s: pd.read_pickle(f"{OUT}/R_{s}.pkl") for v in SETS.values() for s in v}
    out = {}
    for k, ss in SETS.items():
        idx = R[ss[0]].index
        for s in ss[1:]: idx = idx.intersection(R[s].index)
        B = sum(R[s].loc[idx] for s in ss) / len(ss)
        cv = run_cpcv(B, 10, 2, 30)
        psr = cv.paths.apply(lambda x: x.mean() / x.std(ddof=1) * np.sqrt(PPY))
        avg = cv.paths.mean(axis=1)
        eq = (1 + cv.paths).cumprod()
        eqw = eq.resample("W").last() if isinstance(eq.index, pd.DatetimeIndex) else eq
        ch = cv.chosen
        out[k] = dict(pbo=cv.pbo, path_sr=psr.round(3).tolist(), avg_path_sr=float(avg.mean() / avg.std(ddof=1) * np.sqrt(PPY)),
                      is_sr=(ch.is_sharpe * np.sqrt(PPY)).round(3).tolist(), oos_sr=(ch.oos_sharpe * np.sqrt(PPY)).round(3).tolist(),
                      chosen=ch.combo.value_counts().to_dict(), oos_rank=ch.oos_rank_pct.round(3).tolist(),
                      full_sr={c: round(float(B[c].mean() / B[c].std(ddof=1) * np.sqrt(PPY)), 3) for c in B.columns},
                      yearly_avg=avg.groupby(avg.index.year).apply(lambda x: float(np.prod(1 + x) - 1)).round(4).to_dict(),
                      path_end=eq.iloc[-1].round(3).tolist(), start=str(B.index[0])[:10], end=str(B.index[-1])[:10], n=len(B),
                      eq_week={str(i)[:10]: v for i, v in zip(eqw.index, eqw.round(4).values.tolist())})
        print(k, "PBO", round(cv.pbo, 3), "path SR", sorted(out[k]["path_sr"]), "avg", round(out[k]["avg_path_sr"], 2))
        print("  chosen", out[k]["chosen"]); print("  yearly", out[k]["yearly_avg"]); print("  full SR adopted", out[k]["full_sr"].get([c for c in B.columns if "14:00" in c and "0.6" in c][0]), "cols", list(B.columns)[:3])
        print("  IS mean", np.mean(out[k]["is_sr"]).round(2), "OOS mean", np.mean(out[k]["oos_sr"]).round(2), "n", out[k]["n"], out[k]["start"], out[k]["end"])
    json.dump(out, open(f"{OUT}/cpcv.json", "w"), indent=1, default=str)
