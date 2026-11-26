"""Phase 3 runtime: live Binance market data -> LiveTrader -> REAL ORDERS on Binance USDⓈ-M.

    LIVE_MOMENTUM_ACK=phase3-live:<YYYY-MM-DD> \\
        python -m live_momentum.run_live --config live_momentum/runtime/config.live.toml

Refuses to start unless ALL hold:
  * config: mode="live", dry_run=false, passes validate(), LIVE_MOMENTUM_ACK valid for today
  * API key: withdrawals and transfers disabled, IP whitelist set, futures enabled
  * account: one-way position mode; at a fresh session start no position / open order in the
    traded symbols
Exit codes: 2 access restricted (403/451), 3 account/key check failed, 4 orders not enabled
(config / LIVE_MOMENTUM_ACK). The supervisor does not restart on any of them.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path

import websockets

from .binance_public import AccessRestricted, ws_status
from .binance_signed import SignedRest, check_key_permissions
from .config import ACK_ENV, ConfigError, load_config
from .live import LiveTrader, ReconcileError, flatten_account
from .persistence import RedactFilter
from .run_paper import App

log = logging.getLogger("live_momentum")
WS_USER = "wss://fstream.binance.com/private/ws/"
KEEPALIVE_S = 30 * 60


class LiveApp(App):
    FATAL_OPEN = (AccessRestricted, ReconcileError, PermissionError)
    # The live venue never reads the book (orders are priced off the last trade), and the
    # bookTicker firehose (thousands of messages/s) only costs event-loop time next to orders.
    # The stale-data guard then runs on aggTrade alone: fine for BTC/ETH/SOL perps (sub-second
    # trades) with stale_data_sec=10; review before adding an illiquid symbol or a tighter limit.
    BOOK_STREAM = False

    def __init__(self, cfg, rest: SignedRest):
        super().__init__(cfg, equity=0.0)
        self.signed = rest
        self.offset_ms = 0.0
        rest.offset = lambda: self.offset_ms

    def clock_offset_ms(self) -> float:
        self.offset_ms = super().clock_offset_ms()
        return self.offset_ms

    def equity_now(self) -> float:
        return float(self.signed.balances().get("USDT", {}).get("balance", 0.0))

    def new_trader(self, exch):
        return LiveTrader(self.cfg, exch, lambda: int(time.time() * 1000), self.eventlog,
                          Path(self.cfg.state_dir) / "live_state.json", self.signed, self.equity_now())

    # ---------------------------------------------------------------- user data stream
    async def user_stream(self):
        backoff = 1.0
        while not self.stop.is_set():
            try:
                key = await asyncio.to_thread(self.signed.listen_key)
                async with websockets.connect(WS_USER + key, open_timeout=10, ping_interval=20,
                                              ping_timeout=20) as ws:
                    log.info("user data stream connected")
                    backoff, opened, kept = 1.0, time.monotonic(), time.monotonic()
                    while not self.stop.is_set():
                        if time.monotonic() - kept > KEEPALIVE_S:
                            await asyncio.to_thread(self.signed.keepalive)
                            kept = time.monotonic()
                        if time.monotonic() - opened > 23 * 3600:
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        except asyncio.TimeoutError:
                            continue                        # a quiet account is normal
                        msg = json.loads(raw)
                        e = msg.get("e")
                        if e == "ORDER_TRADE_UPDATE" and self.trader is not None:
                            self.trader.on_order_update(msg["o"])
                        elif e == "ACCOUNT_UPDATE" and self.eventlog is not None:
                            a = msg.get("a", {})
                            self.eventlog.write("account_update", reason=a.get("m"),
                                                positions=[(p.get("s"), p.get("pa")) for p in a.get("P", [])])
                        elif e == "listenKeyExpired":
                            log.warning("listenKey expired; reconnecting")
                            break
            except AccessRestricted:
                raise
            except Exception as e:                          # noqa: BLE001 - reconnect on anything else
                if ws_status(e) in (403, 451):
                    raise AccessRestricted(f"user data stream: {e}") from e
                log.warning("user data stream error %s: %s; reconnect in %.0fs", type(e).__name__, e, backoff)
            if not self.stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    async def run(self):
        user = asyncio.create_task(self.user_stream())
        main = asyncio.create_task(super().run())
        done, _ = await asyncio.wait([user, main], return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception():
                self.stop.set()
                raise t.exception()


def preflight(cfg, rest: SignedRest) -> dict:
    bad = check_key_permissions(rest.api_restrictions())
    if rest.position_mode_dual():
        bad.append("account is in hedge (dual-side) position mode; switch to one-way")
    bal = rest.balances()
    usdt = bal.get("USDT", {}).get("balance", 0.0)
    if usdt <= 0:
        bad.append("no USDT in the futures wallet (USDT-margined contracts need USDT margin)")
    if bad:
        raise ReconcileError("; ".join(bad))
    return dict(usdt=usdt, multi_assets=rest.multi_assets())


class AlreadyRunning(RuntimeError):
    """Another live trader holds the lock on this state directory."""


def acquire_single_instance(state_dir) -> object:
    """Exclusive, non-blocking lock on <state_dir>/run_live.lock, held for the life of the process
    (the OS releases it when the process dies, so a crash never leaves a stale lock).
    One account, one trader: a second trader on the same state would duplicate orders."""
    p = Path(state_dir)
    p.mkdir(parents=True, exist_ok=True)
    fh = open(p / "run_live.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        fh.close()
        raise AlreadyRunning(f"another live trader is running on {p} (lock {p / 'run_live.lock'})") from e
    return fh


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--flatten", action="store_true",
                    help="cancel all open orders and close all positions in the traded symbols, then exit")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if cfg.mode != "live":
        raise SystemExit("run_live requires mode='live'")
    if not cfg.sends_orders:
        print(f"orders are disabled: need dry_run=false and {ACK_ENV}=phase3-live:<YYYY-MM-DD> "
              "(valid today, at most 31 days ahead)", flush=True)
        raise SystemExit(4)
    Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(Path(cfg.log_dir) / "live.log")])
    for h in logging.getLogger().handlers:              # no request signature / listenKey in any log line
        h.addFilter(RedactFilter())
    try:
        rest = SignedRest.from_config(cfg)
    except (ConfigError, OSError) as e:          # unreadable / bad secrets file: stop, do not restart
        log.error("secrets: %s", e)
        raise SystemExit(3)
    try:
        if not a.flatten:
            _lock = acquire_single_instance(cfg.state_dir)  # noqa: F841 - held until the process exits
        if a.flatten:
            from .binance_public import PublicRest
            exch = PublicRest().exchange_info(cfg.symbols)
            print(json.dumps(flatten_account(rest, cfg.symbols, exch), indent=2))
            return
        info = preflight(cfg, rest)
        log.info("preflight ok: USDT wallet %.4f, multi-assets %s", info["usdt"], info["multi_assets"])
        asyncio.run(LiveApp(cfg, rest).run())
    except AccessRestricted as e:
        log.error("%s", e)
        raise SystemExit(2)
    except (ReconcileError, PermissionError, AlreadyRunning) as e:
        log.error("%s", e)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
