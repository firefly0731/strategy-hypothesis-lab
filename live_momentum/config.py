"""Runtime configuration (TOML file + environment for secrets).

Safety defaults: dry_run = true, mode = "replay". Real orders need ALL of
  * mode = "testnet" or "live" and dry_run = false (a real TOML boolean, not 0 / "false")
  * a config that passes validate()
  * LIVE_MOMENTUM_ACK = "<phase token>:<YYYY-MM-DD>" naming the phase the user approved and
    the last UTC day the approval is valid (at most 31 days ahead), e.g. "phase2-testnet:2026-12-05".
    An expired, malformed or wrong-phase token disables orders.
API keys come from the environment or, if `secrets_file` is set, ONLY from that file
(0600 permissions, both keys required, no fallback to the environment). They are never
read from the TOML file and never printed.
"""
from __future__ import annotations

import datetime as dt
import os
import stat
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .strategy import SYMBOLS

MODES = ("replay", "paper", "testnet", "live")
ACK_ENV = "LIVE_MOMENTUM_ACK"
ACK_VALUES = {"testnet": "phase2-testnet", "live": "phase3-live"}
ACK_MAX_DAYS = 31


def ack_valid(mode: str, value: str | None, today: dt.date | None = None) -> bool:
    """True if `value` approves `mode` today: "<token>:<YYYY-MM-DD>", not expired, <= 31 days."""
    if mode not in ACK_VALUES or not value or value.count(":") != 1:
        return False
    token, until = value.split(":")
    try:
        until_d = dt.date.fromisoformat(until)
    except ValueError:
        return False
    today = today or dt.datetime.now(dt.timezone.utc).date()
    return token == ACK_VALUES[mode] and today <= until_d <= today + dt.timedelta(days=ACK_MAX_DAYS)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RiskLimits:
    daily_max_loss_pct: float = 0.02        # of equity at the open: stop new entries + flatten
    max_notional_per_symbol: float = 0.0    # USDT; 0 = must be set before testnet/live
    max_gross_leverage: float = 1.0         # sum |notional| / equity (Phase 3 starts at <= 1x)
    stale_data_sec: float = 10.0            # no new orders if the market data is older
    kill_switch_file: str = "/var/lib/live_momentum/KILL"

    def validate(self, mode: str) -> None:
        for f in fields(self):
            v = getattr(self, f.name)
            if f.name == "kill_switch_file":
                if not isinstance(v, str) or not v:
                    raise ConfigError("kill_switch_file must be a non-empty path")
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ConfigError(f"risk.{f.name} must be a number")
        if not 0 < self.daily_max_loss_pct < 0.2:
            raise ConfigError("daily_max_loss_pct must be in (0, 0.2)")
        if self.max_gross_leverage <= 0 or self.max_gross_leverage > 3.0:
            raise ConfigError("max_gross_leverage must be in (0, 3]")
        if self.stale_data_sec <= 0:
            raise ConfigError("stale_data_sec must be > 0")
        if mode in ("testnet", "live") and self.max_notional_per_symbol <= 0:
            raise ConfigError("max_notional_per_symbol must be set for testnet/live")


@dataclass(frozen=True)
class Secrets:
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)

    def __repr__(self) -> str:
        return f"Secrets(api_key={'set' if self.api_key else 'unset'}, api_secret=***)"

    __str__ = __repr__

    @classmethod
    def load(cls, path: str | None = None) -> "Secrets":
        """From `path` only if given (no environment fallback), else from the environment."""
        if not path:
            return cls(os.environ.get("BINANCE_API_KEY", "").strip(),
                       os.environ.get("BINANCE_API_SECRET", "").strip())
        p = Path(path)
        if os.name == "posix" and stat.S_IMODE(p.stat().st_mode) & 0o077:
            raise ConfigError(f"{p} must have permissions 600")
        kv = {}
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            kv[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
        key, sec = kv.get("BINANCE_API_KEY", ""), kv.get("BINANCE_API_SECRET", "")
        if not key or not sec:
            raise ConfigError(f"{p} must define BINANCE_API_KEY and BINANCE_API_SECRET")
        return cls(key, sec)


@dataclass(frozen=True)
class LiveConfig:
    mode: str = "replay"
    dry_run: bool = True
    symbols: tuple = SYMBOLS
    capital_fraction: float = 0.0           # share of the target capital traded (Phase 3: small)
    history_start: str = "2021-01"
    data_dir: str = "/var/lib/live_momentum/data"
    state_dir: str = "/var/lib/live_momentum/state"
    log_dir: str = "/var/log/live_momentum"
    secrets_file: str | None = None
    risk: RiskLimits = RiskLimits()

    def validate(self) -> "LiveConfig":
        if not isinstance(self.dry_run, bool):
            raise ConfigError("dry_run must be a boolean (true / false)")
        if not isinstance(self.mode, str) or self.mode not in MODES:
            raise ConfigError(f"mode must be one of {MODES}")
        if tuple(self.symbols) != SYMBOLS:
            raise ConfigError(f"symbols must be {SYMBOLS} (the validated universe)")
        if self.history_start != "2021-01":
            raise ConfigError("history_start is part of the sizing specification (2021-01)")
        if not 0 <= self.capital_fraction <= 1:
            raise ConfigError("capital_fraction must be in [0, 1]")
        self.risk.validate(self.mode)
        if self.mode in ("replay", "paper") and not self.dry_run:
            raise ConfigError(f"mode={self.mode} never sends orders; dry_run must stay true")
        return self

    @property
    def sends_orders(self) -> bool:
        """True only for a valid testnet/live config with dry_run off and an unexpired approval."""
        try:
            self.validate()
        except ConfigError:
            return False
        return self.dry_run is False and ack_valid(self.mode, os.environ.get(ACK_ENV))


def load_config(path: str | Path | None = None) -> LiveConfig:
    if path is None:
        return LiveConfig().validate()
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    risk = RiskLimits(**raw.pop("risk", {}))
    known = {f.name for f in fields(LiveConfig)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    if "symbols" in raw:
        raw["symbols"] = tuple(raw["symbols"])
    return LiveConfig(risk=risk, **raw).validate()
