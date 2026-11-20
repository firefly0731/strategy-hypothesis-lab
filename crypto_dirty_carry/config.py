"""Configuration for the factor-neutral dirty carry backtest.

Windows are durations (pandas Timedelta strings such as "30D"), not bar counts, so one
configuration works at any bar frequency. They are converted to bars with the data's bar length.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def td(x: str | pd.Timedelta) -> pd.Timedelta:
    return pd.Timedelta(x)


@dataclass(frozen=True)
class CostConfig:
    """Costs charged on traded notional sum(|Δw|) × equity at every execution.

    Defaults: Binance USDC-M taker 4 bp (user-provided fee, research/mm/06 §7) + 1 bp slippage.
    For USDT-M use `CostConfig.binance("USDT")` (VIP0 taker 5 bp, RESEARCH_PROTOCOL.md).
    """
    fee_bps: float = 4.0
    slippage_bps: float = 1.0

    def __post_init__(self):
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps must be non-negative")

    @property
    def rate(self) -> float:
        return (self.fee_bps + self.slippage_bps) * 1e-4

    @classmethod
    def binance(cls, quote: str = "USDC", slippage_bps: float = 1.0) -> "CostConfig":
        fees = {"USDC": 4.0, "USDT": 5.0}
        if quote not in fees:
            raise ValueError(f"unknown quote {quote!r}; expected one of {sorted(fees)}")
        return cls(fee_bps=fees[quote], slippage_bps=slippage_bps)


@dataclass(frozen=True)
class StrategyConfig:
    # --- schedule -------------------------------------------------------------------------
    rebalance_every: str = "8h"       # decision times: bar closes on this grid (anchored at 00:00 UTC)
    rebalance_offset: str = "0h"      # shift of the grid, a multiple of the bar (e.g. "1h" on 1h bars)
    exec_lag_bars: int = 1            # decision at close t, execution at close t + lag bars

    # --- signal ---------------------------------------------------------------------------
    funding_lookback: str = "3D"      # carry = time-weighted funding rate over (t - lookback, t]
    min_funding_events: int = 3       # settlements needed inside the lookback

    # --- basket selection -----------------------------------------------------------------
    k: int | None = 5                 # names per side (set None to use `quantile`)
    quantile: float | None = None     # fraction of eligible names per side
    short_min_signal: float | None = 0.0   # short only if carry > this (None: no condition)
    long_max_signal: float | None = 0.0    # long only if carry < this (None: no condition)
    min_names_per_side: int = 1       # otherwise stay flat at this decision
    buffer_mult: float | None = None  # rank buffer: a held name stays while ranked < buffer_mult·k on its side

    # --- eligibility ----------------------------------------------------------------------
    min_history: str = "30D"          # the name must have prices over this span
    liquidity_window: str = "30D"
    min_median_quote_volume: float = 0.0   # per bar, quote currency
    liquidity_top_n: int | None = None     # keep only the n most liquid names (same median) at each decision
    min_obs_frac: float = 0.8         # share of finite observations required in every window

    # --- volatility -----------------------------------------------------------------------
    vol_window: str = "30D"
    vol_floor: float = 0.10           # annualised
    vol_fallback: str = "median"      # "median" (cross-sectional median) or "drop"

    # --- sizing ---------------------------------------------------------------------------
    gross_leverage: float = 1.0       # baskets: short sum = -gross/2, long sum = +gross/2
    max_weight: float = 0.25          # |w_i| cap, also for hedge legs
    gross_cap: float = 2.0            # hard cap on sum |w| after hedging and vol targeting
    target_vol: float | None = None   # annualised ex-ante portfolio vol target (None: off)

    # --- factor neutralisation ------------------------------------------------------------
    factors: tuple[str, ...] = ("BTC",)            # columns of MarketData.factors
    hedge_instruments: tuple[str, ...] = ("BTCUSDC",)  # traded symbols the projection may use
    neutralize: bool = True
    # "projection": closest weights with Σw = 0 AND B'w = target (re-weights inside the baskets;
    #               the book shrinks when the carry ranking is collinear with beta — see README).
    # "hedge":      keep the baskets, add hedge legs so B'w = target; Σw = Σ hedge legs ≠ 0.
    neutral_mode: str = "projection"
    target_exposure: tuple[float, ...] | None = None  # per factor, default 0
    beta_window: str = "60D"
    ridge: float = 0.0                # penalty λ · trace(X'X)/k on the factor slopes
    shrinkage: float = 0.0            # β ← (1-δ) β + δ · cross-sectional mean (hedge legs excluded)
    hedge_penalty: float = 0.1        # projection cost of moving a hedge leg, relative to 1 for basket names
    keep_sign: bool = True            # a basket name may shrink to 0 but never flip side

    costs: CostConfig = field(default_factory=CostConfig)

    def __post_init__(self):
        if (self.k is None) == (self.quantile is None):
            raise ValueError("set exactly one of k and quantile")
        if self.k is not None and self.k < 1:
            raise ValueError("k must be >= 1")
        if self.quantile is not None and not 0 < self.quantile <= 0.5:
            raise ValueError("quantile must be in (0, 0.5]")
        for name in ("rebalance_every", "funding_lookback", "min_history", "liquidity_window",
                     "vol_window", "beta_window"):
            if td(getattr(self, name)) <= pd.Timedelta(0):
                raise ValueError(f"{name} must be a positive duration")
        if td(self.rebalance_offset) < pd.Timedelta(0) or td(self.rebalance_offset) >= td(self.rebalance_every):
            raise ValueError("rebalance_offset must be in [0, rebalance_every)")
        if self.exec_lag_bars < 0:
            raise ValueError("exec_lag_bars must be >= 0")
        if self.min_funding_events < 2:
            raise ValueError("min_funding_events must be >= 2 (one interval needs two settlements)")
        if self.buffer_mult is not None and self.buffer_mult < 1:
            raise ValueError("buffer_mult must be >= 1")
        if self.min_names_per_side < 1:
            raise ValueError("min_names_per_side must be >= 1")
        if not 0 < self.min_obs_frac <= 1:
            raise ValueError("min_obs_frac must be in (0, 1]")
        if self.vol_floor <= 0:
            raise ValueError("vol_floor must be > 0")
        if self.vol_fallback not in ("median", "drop"):
            raise ValueError("vol_fallback must be 'median' or 'drop'")
        if self.gross_leverage <= 0 or self.max_weight <= 0 or self.gross_cap <= 0:
            raise ValueError("gross_leverage, max_weight and gross_cap must be > 0")
        if self.target_vol is not None and self.target_vol <= 0:
            raise ValueError("target_vol must be > 0")
        if self.target_exposure is not None and len(self.target_exposure) != len(self.factors):
            raise ValueError("target_exposure needs one value per factor")
        if self.ridge < 0 or not 0 <= self.shrinkage <= 1 or self.hedge_penalty <= 0:
            raise ValueError("need ridge >= 0, 0 <= shrinkage <= 1, hedge_penalty > 0")
        if self.neutralize and not self.factors:
            raise ValueError("neutralize=True needs at least one factor")
        if self.neutral_mode not in ("projection", "hedge"):
            raise ValueError("neutral_mode must be 'projection' or 'hedge'")
        if self.neutralize and self.neutral_mode == "hedge" and len(self.hedge_instruments) < len(self.factors):
            raise ValueError("neutral_mode='hedge' needs at least one hedge instrument per factor")

    @property
    def targets(self) -> tuple[float, ...]:
        return self.target_exposure if self.target_exposure is not None else (0.0,) * len(self.factors)

    @property
    def lookback(self) -> pd.Timedelta:
        """Price history any single decision needs."""
        return max(td(self.min_history), td(self.liquidity_window), td(self.vol_window),
                   td(self.beta_window))

    @property
    def funding_history(self) -> pd.Timedelta:
        """Funding history any single decision needs: the lookback plus room for the settlement
        just before it (intervals up to one day)."""
        return 2 * td(self.funding_lookback) + pd.Timedelta(days=1)
