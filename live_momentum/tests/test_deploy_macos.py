"""macOS deployment files: configs match the Windows ones, launchd jobs render correctly, scripts parse."""
import dataclasses
import importlib.util
import plistlib
import shutil
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from live_momentum.config import load_config

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
MAC = DEPLOY / "macos"


def _mk():
    spec = importlib.util.spec_from_file_location("make_plists", MAC / "make_plists.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ["config.paper.toml", "config.live.toml"])
def test_macos_config_equals_windows(name):
    mac, win = load_config(MAC / name), load_config(DEPLOY / "windows" / name)
    assert dataclasses.asdict(mac) == dataclasses.asdict(win)


def test_macos_live_config_needs_user_approval(monkeypatch):
    monkeypatch.delenv("LIVE_MOMENTUM_ACK", raising=False)
    cfg = load_config(MAC / "config.live.toml")
    assert cfg.mode == "live" and cfg.dry_run is False and cfg.size_mode == "min"
    assert cfg.sends_orders is False                 # no token -> no orders
    assert load_config(MAC / "config.paper.toml").sends_orders is False


def test_plists_render(tmp_path):
    mk = _mk()
    mk.main([str(tmp_path), "--user", "trader"])
    jobs = {p.stem: plistlib.loads(p.read_bytes()) for p in tmp_path.glob("*.plist")}
    assert set(jobs) == {"com.livemomentum.paper", "com.livemomentum.live", "com.livemomentum.report"}
    for name, d in jobs.items():
        short = name.rsplit(".", 1)[1]
        assert d["Label"] == name and d["UserName"] == "trader"
        assert d["ProgramArguments"][0] == "/bin/bash"
        script = Path(d["ProgramArguments"][1])
        assert script.name == f"run_{short}.sh" and script.exists()
        assert Path(d["WorkingDirectory"]) == mk.REPO
        assert "LIVE_MOMENTUM_ACK" not in d["EnvironmentVariables"]     # approval is never baked in
        assert not any("secret" in str(v).lower() for v in d["EnvironmentVariables"].values())
    for short in ("paper", "live"):
        d = jobs[f"com.livemomentum.{short}"]
        assert d["RunAtLoad"] is True and d["KeepAlive"] == {"SuccessfulExit": False}
    assert "live/log" in jobs["com.livemomentum.live"]["StandardOutPath"].replace("\\", "/")
    assert "KeepAlive" not in jobs["com.livemomentum.report"]


def test_plist_refuses_root(tmp_path):
    with pytest.raises(SystemExit):
        _mk().main([str(tmp_path), "--user", "root"])


def test_report_calendar_local_time():
    mk = _mk()
    assert mk.local_calendar(tz=ZoneInfo("Asia/Seoul")) == [{"Hour": 6, "Minute": 20}, {"Hour": 21, "Minute": 0}]
    assert mk.local_calendar(tz=ZoneInfo("UTC")) == [{"Hour": 21, "Minute": 20}, {"Hour": 12, "Minute": 0}]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize("script", ["run_paper.sh", "run_live.sh", "run_report.sh", "install.sh"])
def test_scripts_parse(script):
    r = subprocess.run(["bash", "-n", str(MAC / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_single_instance_lock(tmp_path):
    from live_momentum.run_live import AlreadyRunning, acquire_single_instance
    first = acquire_single_instance(tmp_path)
    with pytest.raises(AlreadyRunning):
        acquire_single_instance(tmp_path)
    first.close()                                     # released -> the next trader may start
    acquire_single_instance(tmp_path).close()


def test_bad_secrets_file_stops_with_exit_3(tmp_path, monkeypatch):
    import datetime as dt
    from live_momentum import run_live
    cfg = (MAC / "config.live.toml").read_text(encoding="utf-8")
    for k in ("data_dir", "state_dir", "log_dir"):
        cfg = cfg.replace(f'{k} = "live_momentum/runtime/live/{k.split("_")[0]}"', f'{k} = "{(tmp_path / k).as_posix()}"')
    cfg = cfg.replace('secrets_file = "live_momentum/runtime/live.secrets"',
                      f'secrets_file = "{(tmp_path / "missing.secrets").as_posix()}"')
    assert str(tmp_path.as_posix()) in cfg and "missing.secrets" in cfg
    p = tmp_path / "config.toml"
    p.write_text(cfg, encoding="utf-8")
    until = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=5)).isoformat()
    monkeypatch.setenv("LIVE_MOMENTUM_ACK", f"phase3-live:{until}")
    import logging
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        with pytest.raises(SystemExit) as e:
            run_live.main(["--config", str(p)])
        assert e.value.code == 3
    finally:                                          # main() adds a live.log file handler: remove it
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
