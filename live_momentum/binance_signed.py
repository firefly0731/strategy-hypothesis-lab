"""Signed Binance USDⓈ-M futures REST (orders, positions, balances, listenKey).

Safety:
  * the client is built only from a LiveConfig whose `sends_orders` is True (mode live/testnet,
    dry_run=false, valid config, unexpired LIVE_MOMENTUM_ACK). There is no other constructor path
    that can send orders.
  * the API key / secret / signature never appear in logs, exceptions or reprs. Errors carry
    the HTTP status, the Binance error code and message, and the endpoint path only.
  * HTTP 403/451 raise AccessRestricted (stop, never route around it). 418 raises RateLimited.
  * order requests are NOT retried blindly: a timeout or 5xx on POST /order is resolved by
    querying the order by its newClientOrderId (idempotent client ids, see `new_order`).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import urllib.parse

import requests

from .binance_public import AccessRestricted, RateLimited
from .config import LiveConfig, Secrets

log = logging.getLogger("live_momentum.signed")

BASES = {"live": "https://fapi.binance.com", "testnet": "https://demo-fapi.binance.com"}
RECV_WINDOW_MS = 5000


class BinanceError(RuntimeError):
    def __init__(self, status: int, code: int | None, msg: str, path: str):
        self.status, self.code, self.msg, self.path = status, code, msg, path
        super().__init__(f"{path}: HTTP {status} code {code}: {msg}")


class OrderUnknown(BinanceError):
    """-2011 / -2013: no such order (cancel of a filled or never-placed order)."""


# Binance error codes handled explicitly
UNKNOWN_ORDER = (-2011, -2013)
POST_ONLY_REJECT = -5022          # GTX would execute immediately as taker
DUPLICATE_CID = (-4116,)
TIMESTAMP = -1021


class SignedRest:
    def __init__(self, base: str, secrets: Secrets, clock_offset_ms=lambda: 0.0, session=None, timeout=10.0):
        if not secrets.api_key or not secrets.api_secret:
            raise ValueError("API key and secret are required")
        self.base = base
        self._key = secrets.api_key
        self._secret = secrets.api_secret.encode()
        self.offset = clock_offset_ms          # local - exchange (ms); subtracted from timestamps
        self.s = session or requests.Session()
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"SignedRest(base={self.base!r}, key=***)"

    @classmethod
    def from_config(cls, cfg: LiveConfig, **kw) -> "SignedRest":
        if not cfg.sends_orders:
            raise PermissionError("orders are not enabled (mode/dry_run/validate/LIVE_MOMENTUM_ACK)")
        return cls(BASES[cfg.mode], Secrets.load(cfg.secrets_file), **kw)

    # ------------------------------------------------------------------ transport
    def _sign(self, params: dict) -> str:
        p = {k: v for k, v in params.items() if v is not None}
        p["timestamp"] = int(time.time() * 1000 - self.offset())
        p["recvWindow"] = RECV_WINDOW_MS
        q = urllib.parse.urlencode(p)
        return q + "&signature=" + hmac.new(self._secret, q.encode(), hashlib.sha256).hexdigest()

    def request(self, method: str, path: str, signed: bool = True, **params):
        q = self._sign(params) if signed else urllib.parse.urlencode(params)
        url = f"{self.base}{path}" + (f"?{q}" if q else "")
        r = self.s.request(method, url, headers={"X-MBX-APIKEY": self._key}, timeout=self.timeout)
        if r.status_code in (403, 451):
            raise AccessRestricted(f"{path}: HTTP {r.status_code} (access restricted: stop, do not route around it)")
        if r.status_code == 418:
            raise RateLimited(f"{path}: HTTP 418 (IP banned for exceeding rate limits)")
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code != 200:
            code = body.get("code") if isinstance(body, dict) else None
            msg = (body.get("msg") if isinstance(body, dict) else r.text[:200]) or ""
            cls = OrderUnknown if code in UNKNOWN_ORDER else BinanceError
            raise cls(r.status_code, code, msg, path)
        return body

    # ------------------------------------------------------------------ account
    def position_mode_dual(self) -> bool:
        return bool(self.request("GET", "/fapi/v1/positionSide/dual")["dualSidePosition"])

    def multi_assets(self) -> bool:
        return bool(self.request("GET", "/fapi/v1/multiAssetsMargin")["multiAssetsMargin"])

    def balances(self) -> dict[str, dict]:
        return {x["asset"]: {"balance": float(x["balance"]), "available": float(x["availableBalance"]),
                             "upnl": float(x.get("crossUnPnl", 0.0))}
                for x in self.request("GET", "/fapi/v2/balance")}

    def positions(self, symbols) -> dict[str, float]:
        """Signed position amount per symbol (one-way mode)."""
        out = {s: 0.0 for s in symbols}
        for x in self.request("GET", "/fapi/v2/positionRisk"):
            if x["symbol"] in out:
                out[x["symbol"]] += float(x["positionAmt"])
        return out

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        return self.request("GET", "/fapi/v1/openOrders", symbol=symbol)

    def user_trades(self, symbol: str, start_ms: int, end_ms: int) -> list[dict]:
        return self.request("GET", "/fapi/v1/userTrades", symbol=symbol, startTime=start_ms,
                            endTime=end_ms, limit=1000)

    # ------------------------------------------------------------------ orders
    def new_order(self, symbol: str, side: int, qty: str, cid: str, *, limit: str | None = None,
                  post_only: bool = False, reduce_only: bool = False) -> dict:
        """Place an order with an idempotent client id. On a transport error or 5xx the order
        may or may not exist, so it is looked up by `cid` instead of being re-sent."""
        params = dict(symbol=symbol, side="BUY" if side > 0 else "SELL", quantity=qty,
                      newClientOrderId=cid, newOrderRespType="RESULT")
        if limit is not None:
            params.update(type="LIMIT", price=limit, timeInForce="GTX" if post_only else "GTC")
        else:
            params.update(type="MARKET")
        if reduce_only:
            params["reduceOnly"] = "true"
        try:
            return self.request("POST", "/fapi/v1/order", **params)
        except BinanceError as e:
            if e.code in DUPLICATE_CID:
                return self.query_order(symbol, cid)
            if e.status >= 500:
                return self._resolve(symbol, cid, e)
            raise
        except (requests.Timeout, requests.ConnectionError) as e:
            return self._resolve(symbol, cid, e)

    def _resolve(self, symbol, cid, err):
        log.warning("order %s: %s; resolving by client id", cid, type(err).__name__)
        for i in range(4):
            time.sleep(0.25 * (i + 1))
            try:
                return self.query_order(symbol, cid)
            except OrderUnknown:
                continue                                    # not (yet) visible
            except (requests.Timeout, requests.ConnectionError, BinanceError):
                continue
        raise RuntimeError(f"order {cid}: state unknown after {type(err).__name__}")

    def query_order(self, symbol: str, cid: str) -> dict:
        return self.request("GET", "/fapi/v1/order", symbol=symbol, origClientOrderId=cid)

    def cancel_order(self, symbol: str, cid: str) -> dict | None:
        """Cancel by client id. Returns the order after the cancel; None if it is unknown."""
        try:
            return self.request("DELETE", "/fapi/v1/order", symbol=symbol, origClientOrderId=cid)
        except OrderUnknown:
            try:
                return self.query_order(symbol, cid)         # filled (or expired) before the cancel
            except OrderUnknown:
                return None

    def cancel_all(self, symbol: str) -> None:
        self.request("DELETE", "/fapi/v1/allOpenOrders", symbol=symbol)

    # ------------------------------------------------------------------ user data stream
    def listen_key(self) -> str:
        return self.request("POST", "/fapi/v1/listenKey", signed=False)["listenKey"]

    def keepalive(self) -> None:
        self.request("PUT", "/fapi/v1/listenKey", signed=False)

    # ------------------------------------------------------------------ key permissions (spot API host)
    def api_restrictions(self) -> dict:
        """Permissions of this key (GET /sapi/v1/account/apiRestrictions on api.binance.com)."""
        base, self.base = self.base, "https://api.binance.com"
        try:
            return self.request("GET", "/sapi/v1/account/apiRestrictions")
        finally:
            self.base = base


def check_key_permissions(r: dict) -> list[str]:
    """Problems that forbid trading with this key (empty list = OK)."""
    bad = []
    if r.get("enableWithdrawals"):
        bad.append("withdrawals are enabled on this key (disable them)")
    if not r.get("ipRestrict"):
        bad.append("the key has no IP whitelist (restrict it to this machine's IP)")
    if not r.get("enableFutures"):
        bad.append("futures trading is not enabled on this key")
    if r.get("enableInternalTransfer") or r.get("permitsUniversalTransfer"):
        bad.append("transfers are enabled on this key (disable them)")
    return bad
