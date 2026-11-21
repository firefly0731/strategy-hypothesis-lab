"""Post-hoc diagnostics, NOT pre-committed (added after stage1_discovery was read).

1. Matched random controls for band_flat and band_skew: the same off share per symbol, with a
   random direction for skew.
2. Shuffle test: bars are permuted within each session (bar shapes kept, order destroyed), and
   `none` is rerun. This shows how much of the baseline loss comes from the order of the price
   path (trends) and how much from the fill rule itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .policies import permissions
from .run import CAP, DELTAS, MODES, OUT, TAKER, load_symbol, log, pooled
from .sim import simulate

N = 200
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def sim(d, P, name, state, delta, mode):
    n_k = P["C"].shape[1]
    ab, aa, fl = permissions(name, state, d["dm"], n_k)
    eq, _ = simulate(P["O"], P["H"], P["L"], P["C"], ab, aa, fl, delta, MODES[mode], CAP, TAKER)
    return pd.Series(eq[:, -1] * 1e4, index=d["dates"])


def shuffled(P, rng):
    O, H, L, C = P["O"], P["H"], P["L"], P["C"]
    prev = np.concatenate([O[:, :1], C[:, :-1]], axis=1)
    parts = np.stack([O / prev, H / O, L / O, C / O], axis=-1)
    idx = np.argsort(rng.random(C.shape), axis=1)
    parts = np.take_along_axis(parts, idx[..., None], axis=1)
    c = np.cumprod(parts[..., 0] * parts[..., 3], axis=1)
    o = np.concatenate([np.ones((C.shape[0], 1)), c[:, :-1]], axis=1) * parts[..., 0]
    return {"O": o, "H": o * parts[..., 1], "L": o * parts[..., 2], "C": o * parts[..., 3]}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=SYMS)
    ap.add_argument("--tag", default="discovery")
    a = ap.parse_args(argv)
    data = {s: load_symbol(s) for s in a.symbols}
    rows = []
    for mode in MODES:
        for delta in DELTAS:
            base = pooled({s: sim(d, d["P"], "none", d["state"], delta, mode) for s, d in data.items()})
            band = {k: (pooled({s: sim(d, d["P"], k, d["state"], delta, mode) for s, d in data.items()}) - base).mean()
                    for k in ("band_flat", "band_skew")}
            rnd = {"band_flat": [], "band_skew": []}
            for seed in range(N):
                rng = np.random.default_rng(5000 + seed)
                fake = {}
                for s, d in data.items():
                    p = (d["state"] != 0).mean()
                    on = rng.random(d["state"].shape) < p
                    fake[s] = np.where(on, rng.choice([-1, 1], d["state"].shape), 0)
                for k in rnd:
                    ser = pooled({s: sim(d, d["P"], k, fake[s], delta, mode) for s, d in data.items()})
                    rnd[k].append((ser - base).mean())
            shuf = []
            for seed in range(20):
                rng = np.random.default_rng(9000 + seed)
                shuf.append(pooled({s: sim(d, shuffled(d["P"], rng), "none", d["state"], delta, mode)
                                    for s, d in data.items()}).mean())
            for k in rnd:
                r = np.array(rnd[k])
                rows.append({"mode": mode, "delta_bp": delta * 1e4, "policy": k, "band_improvement": band[k],
                             "random_mean": r.mean(), "random_p95": np.percentile(r, 95),
                             "share_random_ge_band": (r >= band[k]).mean(),
                             "none_pnl": base.mean(), "none_pnl_shuffled": np.mean(shuf),
                             "none_pnl_shuffled_sd": np.std(shuf)})
            log(f"{mode} δ={delta * 1e4:.0f} done")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"diag_{a.tag}.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
