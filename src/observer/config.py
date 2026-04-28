"""Runtime configuration loaded from environment.

Required: BITHUMB_API_KEY, BITHUMB_API_SECRET, OBSERVER_RUN_DIR.
Optional (with defaults): OBSERVER_DURATION_SEC=14400, OBSERVER_MAX_RESTARTS=10, OBSERVER_SYMBOL=USDT_KRW.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    api_secret: str
    run_dir: Path
    duration_sec: int
    max_restarts: int
    symbol: str


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise ConfigError(f"Missing required env var: {name}")
    return value


def load_config(*, use_dotenv: bool = True) -> Config:
    if use_dotenv:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    return Config(
        api_key=_require("BITHUMB_API_KEY"),
        api_secret=_require("BITHUMB_API_SECRET"),
        run_dir=Path(_require("OBSERVER_RUN_DIR")),
        duration_sec=int(os.environ.get("OBSERVER_DURATION_SEC", "14400")),
        max_restarts=int(os.environ.get("OBSERVER_MAX_RESTARTS", "10")),
        symbol=os.environ.get("OBSERVER_SYMBOL", "USDT_KRW"),
    )
