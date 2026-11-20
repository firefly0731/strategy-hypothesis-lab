"""Factor-neutral dirty carry on crypto perpetuals (Binance USDⓈ-M; USDC-margined by default)."""
from .backtest import BacktestResult, compute_schedule, run_backtest, simulate
from .config import CostConfig, StrategyConfig
from .data import MarketData, from_binance
from .portfolio import Targets, compute_targets

__all__ = ["BacktestResult", "CostConfig", "MarketData", "StrategyConfig", "Targets",
           "compute_schedule", "compute_targets", "from_binance", "run_backtest", "simulate"]
