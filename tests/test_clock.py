import time
from observer.clock import stamp


def test_stamp_returns_envelope_with_four_keys() -> None:
    raw = {"hello": "world"}
    env = stamp(channel="transaction", server_ts_ms=1714287000123, raw=raw)
    assert set(env.keys()) == {"channel", "server_ts_ms", "recv_monotonic_ns", "recv_utc_ms", "raw"}
    assert env["channel"] == "transaction"
    assert env["server_ts_ms"] == 1714287000123
    assert env["raw"] is raw  # raw payload preserved by reference, not copied


def test_recv_monotonic_ns_is_strictly_increasing() -> None:
    a = stamp(channel="x", server_ts_ms=0, raw={})
    b = stamp(channel="x", server_ts_ms=0, raw={})
    assert b["recv_monotonic_ns"] > a["recv_monotonic_ns"]


def test_recv_utc_ms_is_close_to_wall_clock() -> None:
    before = int(time.time() * 1000)
    env = stamp(channel="x", server_ts_ms=0, raw={})
    after = int(time.time() * 1000)
    assert before <= env["recv_utc_ms"] <= after + 1
