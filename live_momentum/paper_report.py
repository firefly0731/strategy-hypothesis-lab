"""Daily Phase 1 report: paper trading vs the backtest on the same session.

    python -m live_momentum.paper_report --config CONFIG --date 2026-11-23

Three views of the same session, all with the multipliers fixed at that day's open:
  paper        virtual orders on the live tape / book (events.jsonl)
  replay_live  backtest rules replayed on the bars collected live
  replay_arch  backtest rules replayed on the public archive (once it is published, ~1 day later)

Reported: decisions, trades, maker fill rates, post-only rejects, queue diagnostics, market fill
slippage vs the backtest's price model, P&L in % of equity, and bar differences live vs archive.
Output: <data_dir>/reports/paper/<date>.md and .json, plus a row in summary.csv.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_intraday_momentum.data import load_klines

from .bar_store import BarStore, merged_history
from .bars import ONE_MIN
from .config import load_config
from .persistence import EventLog
from .replay import replay_session
from .signal_engine import session_for
from .strategy import SYMBOLS, backtest_config


def unit_ret(t: pd.DataFrame, cfg) -> pd.Series:
    """Per-trade return on notional after fees (same as the backtest's ret_notional w/o funding)."""
    if t.empty:
        return pd.Series(dtype=float)
    fin = np.where(t["entry_maker"], cfg.maker_fee, cfg.taker_fee)
    fout = np.where(t["exit_maker"], cfg.maker_fee, cfg.taker_fee)
    gross = t["side"] * (t["exit_px"] - t["entry_px"])
    return (gross - t["entry_px"] * fin - t["exit_px"] * fout) / t["entry_px"]


def _rate(x: pd.Series) -> float:
    return float(x.mean()) if len(x) else float("nan")


def build_report(data_dir: Path, day, archive_cache=None, live_history_days: int = 50) -> dict:
    day = pd.Timestamp(day)
    sess = session_for(day)
    if sess is None:
        raise ValueError(f"{day.date()} is not a trading session")
    ev = EventLog(Path(data_dir) / "paper" / f"{day:%Y-%m-%d}" / "events.jsonl").read()
    start = next((e for e in ev if e["type"] == "session_start"), None)
    end = next((e for e in ev if e["type"] == "session_end"), None)
    if start is None:
        raise ValueError("no session_start event: the paper trader did not run that day")
    mult, eq0 = start["multiplier"], start["equity_open"]
    out = dict(date=str(day.date()), sizing={k: start.get(k) for k in ("g", "dd", "scale", "eff", "multiplier")},
               equity_open=eq0, symbols={}, issues=[])
    paper_trades = pd.DataFrame(end["trades"]) if end else pd.DataFrame()
    if end is None:
        out["issues"].append("no session_end event (crash before 16:00 or still running)")
    venue = (end or {}).get("venue", {})
    for k in ("data_gap", "risk_entry", "halt", "kill_switch", "daily_loss_flatten", "catchup_start",
              "bar_repair", "ws_connect", "entry_too_small"):
        n = sum(e["type"] == k for e in ev)
        if n:
            out.setdefault("event_counts", {})[k] = n

    tot = dict(paper=0.0, paper_ex_funding=0.0, replay_live=0.0, replay_arch=0.0)
    for sym in SYMBOLS:
        cfg = backtest_config(sym, tick=start["ticks"][sym], include_funding=False)
        store = BarStore(Path(data_dir), sym)
        store.load(sess.start - pd.Timedelta(days=live_history_days))
        live = store.frame()
        arch = None
        try:
            kw = {} if archive_cache is None else {"cache": archive_cache}
            # the replay needs 45 days of history before the session
            arch = load_klines(sym, (day - pd.DateOffset(months=2)).strftime("%Y-%m"), day.strftime("%Y-%m"), **kw)
        except Exception as e:                     # noqa: BLE001
            out["issues"].append(f"{sym}: archive unavailable ({type(e).__name__})")
        arch_has_day = arch is not None and arch.index[-1] >= sess.end - ONE_MIN
        s = {}
        # replay on live-collected bars for the session (history before it from the archive)
        hist_before = arch[arch.index < sess.start] if arch is not None else None
        try:
            df_live = merged_history(hist_before, live)
            rl, _, first = replay_session(df_live, day, cfg)
        except Exception as e:                     # noqa: BLE001
            rl, first = pd.DataFrame(), None
            out["issues"].append(f"{sym}: replay on live bars failed ({e})")
        ra = pd.DataFrame()
        if arch_has_day:
            ra, _, _ = replay_session(arch, day, cfg)
        pt = paper_trades[paper_trades["sym"] == sym] if len(paper_trades) else pd.DataFrame()
        m = mult[sym]
        s["trades"] = dict(paper=len(pt), replay_live=len(rl), replay_arch=len(ra) if arch_has_day else None)
        s["ret_pct"] = dict(
            paper=float(pt["pnl"].sum() / eq0 * 100) if len(pt) else 0.0,
            paper_ex_funding=float((pt["pnl"] + pt["funding"]).sum() / eq0 * 100) if len(pt) else 0.0,
            replay_live=float((m * unit_ret(rl, cfg)).sum() * 100),
            replay_arch=float((m * unit_ret(ra, cfg)).sum() * 100) if arch_has_day else None)
        tot["paper"] += s["ret_pct"]["paper"]
        tot["paper_ex_funding"] += s["ret_pct"]["paper_ex_funding"]
        tot["replay_live"] += s["ret_pct"]["replay_live"]
        if arch_has_day:
            tot["replay_arch"] += s["ret_pct"]["replay_arch"]
        s["maker_rate"] = dict(
            paper_entry=_rate(pt["entry_maker"]) if len(pt) else None,
            paper_exit=_rate(pt["exit_maker"]) if len(pt) else None,
            replay_live_entry=_rate(rl["entry_maker"]) if len(rl) else None,
            replay_live_exit=_rate(rl["exit_maker"]) if len(rl) else None)
        # same trades? compare entry/exit minutes and sides with the live-bar replay
        if len(pt) or len(rl):
            a = pt[["side", "entry_bar", "exit_bar"]].astype(int).values.tolist() if len(pt) else []
            b = []
            if len(rl):
                eb = ((rl["entry_time"] - sess.start) // ONE_MIN).astype(int)
                b = list(zip(rl["side"].astype(int), eb, eb + rl["hold_min"].astype(int)))
                b = [list(x) for x in b]
            s["same_trades_as_replay_live"] = a == b
            if a != b:
                out["issues"].append(f"{sym}: paper trades differ from the live-bar replay: {a} vs {b}")
        # market fills: paper price vs the backtest model (next bar open +/- 1 bp)
        bars = (arch if arch_has_day else live)
        slips = []
        for e in [x for x in ev if x["type"] == "order_fill" and x["sym"] == sym and x["info"] == "taker"]:
            t = int(e["t"])
            k = sess.start + t * ONE_MIN
            if t < sess.n_min and k in bars.index:
                model = bars.loc[k, "open"] * (1 + e["side"] * cfg.taker_slippage_bps * 1e-4)
            else:
                model = bars.loc[sess.end - ONE_MIN, "close"] * (1 + e["side"] * cfg.taker_slippage_bps * 1e-4) \
                    if sess.end - ONE_MIN in bars.index else np.nan
            slips.append(e["side"] * (e["px"] / model - 1) * 1e4)
        s["market_fill_vs_model_bp"] = dict(n=len(slips), mean=float(np.nanmean(slips)) if slips else None)
        orders = venue.get(sym, {}).get("orders", [])
        filled = [o for o in orders if o.get("first_through_ts")]
        s["post_only"] = dict(
            orders=len(orders), rejected=sum(bool(o["rejected"]) for o in orders), filled=len(filled),
            filled_with_through_qty_ge_order=sum(o["through_qty"] >= o["qty"] for o in filled),
            mean_queue_ahead=float(np.nanmean([o["queue_ahead"] for o in orders if o["queue_ahead"] is not None]))
            if orders else None)
        # bar data: live vs archive for the session
        if arch_has_day:
            idx = pd.date_range(sess.start, sess.end, freq="1min", inclusive="left", tz="UTC")
            la = live.reindex(idx)
            aa = arch.reindex(idx)
            miss = int(la["close"].isna().sum())
            diff = (la["close"] - aa["close"]).abs() / aa["close"]
            s["bars_live_vs_archive"] = dict(missing_live=miss, close_mismatch=int((diff > 1e-12).sum()),
                                             max_rel_diff=float(diff.max()) if diff.notna().any() else None,
                                             volume_rel_diff=float(((la["volume"] - aa["volume"]).abs().sum())
                                                                   / max(aa["volume"].sum(), 1e-12)))
        if first is not None:
            s["ready"] = first.ready
        out["symbols"][sym] = s
    out["portfolio_ret_pct"] = tot if any(v is not None for v in tot.values()) else None
    if out["symbols"] and any(x["trades"]["replay_arch"] is None for x in out["symbols"].values()):
        out["portfolio_ret_pct"]["replay_arch"] = None
    return out


def to_markdown(r: dict) -> str:
    L = [f"# Paper report {r['date']}", "",
         f"equity at open {r['equity_open']:.2f} USDT; throttle g={r['sizing']['g']:.2f} "
         f"(DD {r['sizing']['dd']:.2%}), scale {r['sizing']['scale']:.2f}", ""]
    p = r.get("portfolio_ret_pct") or {}
    fmt = lambda v: "n/a" if v is None else f"{v:+.3f}%"
    L += ["| view | portfolio return |", "|---|---|",
          f"| paper (after funding) | {fmt(p.get('paper'))} |",
          f"| paper before funding (compare with the replays) | {fmt(p.get('paper_ex_funding'))} |",
          f"| replay on live bars (no funding) | {fmt(p.get('replay_live'))} |",
          f"| replay on archive (no funding) | {fmt(p.get('replay_arch'))} |", ""]
    L += ["| symbol | trades paper/live/arch | maker entry paper/replay | maker exit paper/replay | "
          "market fill vs model (bp) | post-only rejects | same trades |", "|---|---|---|---|---|---|---|"]
    for s, x in r["symbols"].items():
        mr = x["maker_rate"]
        f2 = lambda v: "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.0%}"
        mk = x["market_fill_vs_model_bp"]
        mk_s = "-" if mk["mean"] is None else f"{mk['mean']:+.2f} (n={mk['n']})"
        tr = x["trades"]
        L.append(f"| {s} | {tr['paper']}/{tr['replay_live']}/{tr['replay_arch']} | "
                 f"{f2(mr['paper_entry'])}/{f2(mr['replay_live_entry'])} | {f2(mr['paper_exit'])}/{f2(mr['replay_live_exit'])} | "
                 f"{mk_s} | {x['post_only']['rejected']}/{x['post_only']['orders']} | "
                 f"{x.get('same_trades_as_replay_live', '-')} |")
    L.append("")
    for s, x in r["symbols"].items():
        if "bars_live_vs_archive" in x:
            b = x["bars_live_vs_archive"]
            L.append(f"- {s} bars live vs archive: missing {b['missing_live']}, close mismatches "
                     f"{b['close_mismatch']}, volume diff {b['volume_rel_diff']:.2e}")
    if r.get("event_counts"):
        L += ["", "events: " + ", ".join(f"{k}={v}" for k, v in r["event_counts"].items())]
    if r["issues"]:
        L += ["", "## issues"] + [f"- {i}" for i in r["issues"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--date", default=None, help="NYSE session date (default: previous session)")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if a.date is None:                      # latest completed session
        now = pd.Timestamp.now(tz="UTC")
        d = now.tz_convert("America/New_York").normalize().tz_localize(None)
        while session_for(d) is None or session_for(d).end > now:
            d -= pd.Timedelta(days=1)
        a.date = str(d.date())
    r = build_report(Path(cfg.data_dir), a.date)
    out = Path(cfg.data_dir) / "reports" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.date}.json").write_text(json.dumps(r, indent=2, default=str))
    (out / f"{a.date}.md").write_text(to_markdown(r), encoding="utf-8")
    row = dict(date=a.date, **{f"ret_{k}": v for k, v in (r.get("portfolio_ret_pct") or {}).items()},
               trades=sum(x["trades"]["paper"] for x in r["symbols"].values()), issues=len(r["issues"]))
    summ = out / "summary.csv"
    df = pd.read_csv(summ) if summ.exists() else pd.DataFrame()
    if "date" in df.columns:
        df = df[df["date"].astype(str) != a.date]
    df = pd.concat([df, pd.DataFrame([row])])
    df.sort_values("date").to_csv(summ, index=False)
    print(to_markdown(r))


if __name__ == "__main__":
    main()
