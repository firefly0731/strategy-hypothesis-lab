"""Operator commands.

    python -m live_momentum.cli kill   --config CONFIG   # cancel all + flatten + stop new entries
    python -m live_momentum.cli unkill --config CONFIG   # allow new entries again (next boundary)
    python -m live_momentum.cli status --config CONFIG
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .persistence import read_json


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["kill", "unkill", "status"])
    ap.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    kill = Path(cfg.risk.kill_switch_file)
    if a.cmd == "kill":
        kill.parent.mkdir(parents=True, exist_ok=True)
        kill.write_text("kill requested\n")
        print(f"kill switch set: {kill} (takes effect at the next minute boundary)")
    elif a.cmd == "unkill":
        kill.unlink(missing_ok=True)
        print("kill switch cleared; new entries resume next session (the current one stays halted)")
    else:
        st = read_json(Path(cfg.state_dir) / "paper_state.json") or {}
        out = {"kill_switch": kill.exists(), "date": st.get("date"), "last_t": st.get("last_t"),
               "halted": st.get("halted"), "finished": st.get("finished"),
               "positions": {s: b["ex"]["pos"] * b["ex"]["qty"] for s, b in st.get("books", {}).items()}}
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
