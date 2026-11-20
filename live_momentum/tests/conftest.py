import numpy as np
import pandas as pd
import pytest

from crypto_intraday_momentum.data import DEFAULT_CACHE
from crypto_intraday_momentum.tests.test_lookahead import perturb_from, synth  # noqa: F401

REAL_START, REAL_END = "2021-01", "2026-11"
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def has_real_data() -> bool:
    return all((DEFAULT_CACHE / "klines_v2" / s).exists() for s in SYMS)


real_data = pytest.mark.skipif(not has_real_data(), reason="Binance kline cache not downloaded")


@pytest.fixture(scope="session")
def synth_df():
    # long enough for 14-session sigma warm-up plus ~50 traded sessions, spans a DST change
    return synth("2024-01-02", "2024-04-20", seed=1)


def synth_v_sessions(start="2024-01-02", end="2024-04-20", seed=5, every=4, up=0.012, down=0.03):
    """Random 1m data where every `every`-th NYSE session rises `up` in the first 30 min and
    then falls `down` over the next 30 min, so band flips (long -> short) actually happen."""
    from live_momentum.signal_engine import session_for
    df = synth(start, end, seed=seed)
    r = np.diff(np.log(df["close"].to_numpy()), prepend=np.log(df["close"].iloc[0]))
    r[0] = 0.0
    days = pd.date_range(start, end, freq="D")
    k = 0
    for d in days:
        s = session_for(d)
        if s is None:
            continue
        k += 1
        if k < 16 or k % every:
            continue
        a = int((s.start - df.index[0]) // pd.Timedelta(minutes=1))
        if a + 120 >= len(r):
            break
        r[a:a + 30] += up / 30
        r[a + 30:a + 60] -= down / 30
    c = df["close"].iloc[0] * np.exp(np.cumsum(r))
    o = np.concatenate([[c[0]], c[:-1]])
    spread = (df["high"] - np.maximum(df["open"], df["close"])).to_numpy() / df["close"].to_numpy() * c
    out = df.copy()
    out["close"], out["open"] = c, o
    out["high"] = np.maximum(o, c) + spread
    out["low"] = np.minimum(o, c) - spread
    out["quote_volume"] = out["volume"] * (out["high"] + out["low"] + out["close"]) / 3
    return out


@pytest.fixture(scope="session")
def synth_outage_df():
    """Random outages (missing minutes) plus one session with > 2% missing bars, put on
    the minute grid by the same code path as the research loader."""
    from live_momentum.bars import regularize
    from live_momentum.signal_engine import session_for
    df = synth("2024-01-02", "2024-04-20", seed=7)
    raw = df.drop(columns="filled")
    rng = np.random.default_rng(11)
    drop = set((rng.choice(len(raw) - 2, 400, replace=False) + 1).tolist())
    bad_day = pd.Timestamp("2024-02-21")
    a = int((session_for(bad_day).start - raw.index[0]) // pd.Timedelta(minutes=1))
    drop |= set(range(a + 100, a + 130))                   # 30 of 390 bars missing (7.7%)
    raw = raw.drop(raw.index[sorted(drop)])
    return regularize(raw), bad_day


@pytest.fixture(scope="session")
def synth_flip_df():
    return synth_v_sessions()


@pytest.fixture(scope="session")
def synth_portfolio_dfs():
    return {s: synth("2023-08-01", "2024-04-20", seed=k + 3) for k, s in enumerate(SYMS)}


@pytest.fixture(scope="session")
def real_dfs():
    from crypto_intraday_momentum.data import load_klines
    return {s: load_klines(s, REAL_START, REAL_END) for s in SYMS}
