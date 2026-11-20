from pathlib import Path

import pytest

import datetime as dt

from live_momentum.config import (ACK_ENV, ConfigError, LiveConfig, RiskLimits, Secrets, ack_valid,
                                  load_config)

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"


def test_defaults_are_safe():
    c = load_config()
    assert c.dry_run and c.mode == "replay" and not c.sends_orders


def test_example_config_loads():
    c = load_config(EXAMPLE)
    assert c.dry_run and not c.sends_orders


def test_orders_need_mode_dry_run_off_and_ack(monkeypatch):
    risk = RiskLimits(max_notional_per_symbol=1000.0)
    c = LiveConfig(mode="testnet", dry_run=False, risk=risk).validate()
    today = dt.datetime.now(dt.timezone.utc).date()
    ok = f"phase2-testnet:{today + dt.timedelta(days=3)}"
    monkeypatch.delenv(ACK_ENV, raising=False)
    assert not c.sends_orders
    for bad in ("phase2-testnet",                                     # no expiry
                f"phase3-live:{today + dt.timedelta(days=3)}",        # wrong phase
                f"phase2-testnet:{today - dt.timedelta(days=1)}",     # expired
                f"phase2-testnet:{today + dt.timedelta(days=90)}",    # too far ahead
                "phase2-testnet:tomorrow"):
        monkeypatch.setenv(ACK_ENV, bad)
        assert not c.sends_orders, bad
    monkeypatch.setenv(ACK_ENV, ok)
    assert c.sends_orders
    assert not LiveConfig(mode="testnet", dry_run=True, risk=risk).sends_orders
    # non-boolean dry_run or an invalid config never sends, even with a valid approval
    assert not LiveConfig(mode="testnet", dry_run=0, risk=risk).sends_orders
    assert not LiveConfig(mode="testnet", dry_run=False).sends_orders       # no notional limit


def test_ack_valid_boundaries():
    d = dt.date(2026, 11, 20)
    assert ack_valid("live", "phase3-live:2026-11-20", d)
    assert ack_valid("live", "phase3-live:2026-12-21", d)
    assert not ack_valid("live", "phase3-live:2026-12-22", d)
    assert not ack_valid("replay", "phase3-live:2026-11-20", d)


def test_toml_dry_run_must_be_boolean(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('mode = "testnet"\ndry_run = 0\n[risk]\nmax_notional_per_symbol = 100.0\n')
    with pytest.raises(ConfigError):
        load_config(p)


@pytest.mark.parametrize("kw", [dict(mode="paper", dry_run=False), dict(mode="x"),
                                dict(symbols=("BTCUSDT",)), dict(history_start="2022-01"),
                                dict(mode="live", dry_run=False),            # no notional limit
                                dict(risk=RiskLimits(max_gross_leverage=5))])
def test_invalid_configs_rejected(kw):
    with pytest.raises(ConfigError):
        LiveConfig(**kw).validate()


def test_secrets_never_printed(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "AKEY123456")
    monkeypatch.setenv("BINANCE_API_SECRET", "SSECRET98765")
    s = Secrets.load()
    assert s.api_key == "AKEY123456"
    for txt in (repr(s), str(s), f"{s}", repr(LiveConfig())):
        assert "AKEY123456" not in txt and "SSECRET98765" not in txt


def test_secrets_file_only_no_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "ENVKEY")
    monkeypatch.setenv("BINANCE_API_SECRET", "ENVSEC")
    f = tmp_path / "s.env"
    f.write_text("# keys\nexport BINANCE_API_KEY = FILEKEY\nBINANCE_API_SECRET='FILESEC'\n")
    f.chmod(0o600)
    s = Secrets.load(str(f))
    assert (s.api_key, s.api_secret) == ("FILEKEY", "FILESEC")
    f.write_text("BINANCE_API_KEY = FILEKEY\n")                     # secret missing in the file
    with pytest.raises(ConfigError):
        Secrets.load(str(f))


def test_risk_values_must_be_numbers():
    with pytest.raises(ConfigError):
        LiveConfig(risk=RiskLimits(daily_max_loss_pct="0.02")).validate()


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('mode = "replay"\napi_key = "x"\n')
    with pytest.raises(ConfigError):
        load_config(p)
