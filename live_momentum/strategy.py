"""The adopted configuration, in one place.

Source of truth: crypto_intraday_momentum/daily_report.py and walkforward.py (FINAL):
US session 09:30-16:00 NY, entry cutoff 14:00, VWAP confirmation 0.6 sigma, maker_chase,
rv24 sizing, BTC+ETH+SOL equal weight, 25% portfolio vol target, 3x per-trade cap,
15% drawdown throttle.
"""
from __future__ import annotations

from dataclasses import dataclass

from crypto_intraday_momentum.backtest import Config
from crypto_intraday_momentum.cpcv import EXEC
from crypto_intraday_momentum.run import TICKS
from crypto_intraday_momentum.sessions import US

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SESSION = US
RULES = dict(entry_cutoff_min=270, vwap_confirm_k=0.6)
EXEC_NAME = "maker_chase"
# history anchor: build_portfolio drops the first 31 sessions by position and the drawdown
# throttle is path dependent, so live sizing must start from the same history as the backtest
HISTORY_START = "2021-01"


def backtest_config(symbol: str, tick: float | None = None, **over) -> Config:
    """Config used by the research code for this symbol (ticks: exchangeInfo in live).

    sizing="fixed" (1x): the adopted pipeline runs the backtest through `unit_trades`, which
    forces fixed sizing. With the backtest default sizing="vol" a session would additionally
    need a finite 14-session close-to-close vol to be `ready`, a rule the adopted configuration
    does not have (leverage comes from rv24 in the sizing layer)."""
    kw = dict(tick=TICKS[symbol] if tick is None else tick, sizing="fixed", fixed_leverage=1.0,
              **EXEC[EXEC_NAME], **RULES)
    kw.update(over)
    return Config(**kw)


@dataclass(frozen=True)
class SizingParams:
    scheme: str = "rv24"
    target_daily: float = 0.02      # per-symbol leverage = target_daily / RV24
    target_ann: float = 0.25        # portfolio vol target
    vol_lookback: int = 60          # sessions of unscaled portfolio returns
    vol_min_periods: int = 20
    scale_cap: float = 20.0
    max_lev: float = 3.0            # per-trade effective leverage on total equity
    dd_max: float = 0.15            # drawdown throttle
    dd_floor: float = 0.25
    warmup: int = 31                # build_portfolio's WARMUP (positional)
    ppy: int = 252
