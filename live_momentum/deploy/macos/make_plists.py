"""Render the launchd job definitions for the macOS host.

    python live_momentum/deploy/macos/make_plists.py OUTDIR --user NAME [--only paper live report]

Jobs (LaunchDaemons: they start at boot without a login session and run as --user):
  com.livemomentum.paper   paper trader supervisor (run_paper.sh), started at load, restarted if the
                           supervisor itself dies with a non-zero code
  com.livemomentum.live    LIVE trader supervisor (run_live.sh), same; REAL ORDERS once approved
  com.livemomentum.report  daily paper report at 21:20 and 12:00 UTC, converted to the host's local time
                           at render time (launchd calendars use local time; re-render after a time zone
                           change or, in a zone with DST, after each DST switch)
The supervisors exit 0 when they must stop for good (region restriction, failed preflight, no approval),
so KeepAlive {SuccessfulExit: false} does not restart them in those cases.
"""
from __future__ import annotations

import argparse
import datetime as dt
import plistlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
JOBS = ("paper", "live", "report")
REPORT_UTC = ((21, 20), (12, 0))


def label(name: str) -> str:
    return f"com.livemomentum.{name}"


def local_calendar(times_utc=REPORT_UTC, tz=None, on: dt.date | None = None) -> list[dict]:
    """UTC wall times -> launchd StartCalendarInterval entries in `tz` (default: host local zone)."""
    on = on or dt.datetime.now(dt.timezone.utc).date()
    out = []
    for h, m in times_utc:
        t = dt.datetime(on.year, on.month, on.day, h, m, tzinfo=dt.timezone.utc).astimezone(tz)
        out.append({"Hour": t.hour, "Minute": t.minute})
    return out


def job(name: str, user: str, repo: Path = REPO, tz=None) -> dict:
    if name not in JOBS:
        raise ValueError(f"unknown job {name!r}, expected one of {JOBS}")
    log_dir = repo / "live_momentum" / "runtime" / ("live/log" if name == "live" else "log")
    d = {
        "Label": label(name),
        "UserName": user,
        "WorkingDirectory": str(repo),
        "ProgramArguments": ["/bin/bash", str(repo / "live_momentum" / "deploy" / "macos" / f"run_{name}.sh")],
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": f"/Users/{user}",
                                 "LANG": "en_US.UTF-8"},
        "StandardOutPath": str(log_dir / f"launchd_{name}.log"),
        "StandardErrorPath": str(log_dir / f"launchd_{name}.log"),
    }
    if name == "report":
        d["StartCalendarInterval"] = local_calendar(tz=tz)
    else:
        d["RunAtLoad"] = True
        d["KeepAlive"] = {"SuccessfulExit": False}
        d["ThrottleInterval"] = 30
        # On stop launchd sends SIGTERM to the supervisor, which forwards it to the trader. The trader has no
        # SIGTERM handler, so a stop acts like a crash. State files are written atomically, and the next
        # start reconciles positions and open orders with the exchange. Use the kill switch before stopping
        # while a position is open.
        d["ExitTimeOut"] = 60
    return d


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--user", required=True, help="account that owns the checkout (not root)")
    ap.add_argument("--only", nargs="+", choices=JOBS, default=list(JOBS))
    a = ap.parse_args(argv)
    if a.user == "root":
        raise SystemExit("--user must be the account that owns the checkout, not root")
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name in a.only:
        p = out / f"{label(name)}.plist"
        p.write_bytes(plistlib.dumps(job(name, a.user)))
        print(p)


if __name__ == "__main__":
    main()
