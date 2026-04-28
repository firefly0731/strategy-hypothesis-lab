from pathlib import Path

import pytest

from observer.config import Config, ConfigError, load_config


def test_load_config_with_all_required_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BITHUMB_API_KEY", "key123")
    monkeypatch.setenv("BITHUMB_API_SECRET", "secret456")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("OBSERVER_DURATION_SEC", "14400")
    monkeypatch.setenv("OBSERVER_MAX_RESTARTS", "10")
    monkeypatch.setenv("OBSERVER_SYMBOL", "USDT_KRW")
    cfg = load_config(use_dotenv=False)
    assert isinstance(cfg, Config)
    assert cfg.api_key == "key123"
    assert cfg.api_secret == "secret456"
    assert cfg.run_dir == tmp_path
    assert cfg.duration_sec == 14400
    assert cfg.max_restarts == 10
    assert cfg.symbol == "USDT_KRW"


def test_load_config_applies_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BITHUMB_API_KEY", "k")
    monkeypatch.setenv("BITHUMB_API_SECRET", "s")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("OBSERVER_DURATION_SEC", raising=False)
    monkeypatch.delenv("OBSERVER_MAX_RESTARTS", raising=False)
    monkeypatch.delenv("OBSERVER_SYMBOL", raising=False)
    cfg = load_config(use_dotenv=False)
    assert cfg.duration_sec == 14400
    assert cfg.max_restarts == 10
    assert cfg.symbol == "USDT_KRW"


def test_load_config_missing_required_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BITHUMB_API_KEY", raising=False)
    monkeypatch.setenv("BITHUMB_API_SECRET", "s")
    monkeypatch.setenv("OBSERVER_RUN_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="BITHUMB_API_KEY"):
        load_config(use_dotenv=False)
