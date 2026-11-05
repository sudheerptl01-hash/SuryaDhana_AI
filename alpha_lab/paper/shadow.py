#!/usr/bin/env python
"""S1 / S1H paper forward shadow (owner's decision 14 Oct 2026: start 15 Oct 2026).

Runs every evening after EOD ingest (master-controller job `alpha_shadow_daily`, 19:50 IST).
PAPER ONLY — this file never talks to ICICI and never places an order of any kind.

Design: deterministic REPLAY, not incremental state. Each run reloads the panel and replays the
entire forward period (from START) through `backtest.engine.run` with the same `s1_sentinel.build`
targets that passed Gates A and B — so the paper track can never drift from the validated code,
catch-up after a missed day is automatic, and every number is reproducible from scratch.

Rules recap (PLAN.md §S1 + Amendments v2): signals at each month's last close, fills at the next
open; the shadow starts FLAT on 15 Oct 2026, so its first possible fill is the first session of
November 2026, off the 30 Oct signal. Variants: S1 ₹10L plain; S1H ₹50L, 85/15, whole-lot NIFTY
futures hedge while risk-off.

    PYTHONPATH=alpha_lab python alpha_lab/paper/shadow.py --daily      # the scheduled entry point
    PYTHONPATH=alpha_lab python alpha_lab/paper/shadow.py --status     # print status, no messages
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parent
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from backtest import engine  # noqa: E402
from backtest import mc  # noqa: E402
from backtest.data_access import load  # noqa: E402
from strategies.s1_sentinel import build  # noqa: E402

START = pd.Timestamp("2026-10-15")          # owner-fixed; never move after launch
STATE = LAB / "paper" / "state.json"
NAV_CSV = LAB / "reports" / "shadow_nav.csv"
STATUS_MD = LAB / "reports" / "shadow_status.md"
VARIANTS = {
    "S1": engine.EngineConfig(capital=1_000_000),
    "S1H": engine.EngineConfig(capital=5_000_000, hedge=True, sleeve_frac=0.15),
}


def signal_rows(sessions: pd.DatetimeIndex, start: pd.Timestamp) -> list[int]:
    """Month-end rows on/after `start` whose NEXT session already exists in the panel (the fill
    session defines the signal — no future calendar needed). The panel's last session therefore
    never signals until the following session's data arrives."""
    out = []
    for s in range(len(sessions) - 1):
        if sessions[s] >= start and sessions[s + 1].month != sessions[s].month:
            out.append(s)
    return out


def replay_picks(data: dict, rows: list[int]) -> list[dict]:
    """The book decided at each signal row, exactly as the engine sees it (fresh build, same order)."""
    targets = build(data)
    out = []
    for s in rows:
        picks, risk_on = targets(s)
        out.append({"signal": data["panel"]["close"].index[s], "picks": list(picks), "risk_on": risk_on})
    return out


def span_of(sessions: pd.DatetimeIndex, start: pd.Timestamp) -> pd.DatetimeIndex:
    """Sessions the shadow covers; before launch day arrives, the latest session as an 'armed' anchor."""
    span = sessions[sessions >= start]
    return span if len(span) else sessions[-1:]


def nav_frame(results: dict[str, engine.Result], nifty: pd.Series, sessions: pd.DatetimeIndex,
              start: pd.Timestamp) -> pd.DataFrame:
    """Daily NAV per variant from `start` (flat at capital before the first fill) + NIFTY, rebased to 100."""
    span = span_of(sessions, start)
    out = pd.DataFrame(index=span)
    for name, res in results.items():
        cap = res.config.capital
        eq = res.equity.reindex(span)
        out[name] = (eq.fillna(cap) if eq.notna().any() else pd.Series(cap, index=span)) / cap * 100
    n = nifty.reindex(span).ffill()
    out["NIFTY"] = n / n.iloc[0] * 100
    return out


def run_shadow(data: dict) -> tuple[dict[str, engine.Result], list[int], list[dict]]:
    sessions = data["panel"]["close"].index
    rows = signal_rows(sessions, START)
    results = {}
    for name, cfg in VARIANTS.items():
        if rows:
            results[name] = engine.run(data["panel"], data["nifty"], rows, build(data), cfg)
        else:                                            # armed, nothing decided yet: flat at capital
            flat = pd.Series(cfg.capital, index=span_of(sessions, START))
            bench = data["nifty"].reindex(flat.index).ffill()
            results[name] = engine.Result(flat, bench / bench.iloc[0] * cfg.capital,
                                          pd.DataFrame(), 0.0, cfg, ["armed, no signal yet"])
    return results, rows, (replay_picks(data, rows) if rows else [])


def telegram(text: str) -> bool:
    try:
        from dotenv import dotenv_values
        env = {**dotenv_values(ROOT / ".env")}
        import httpx
        tok, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
        if not tok or not chat:
            return False
        r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                       json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def render_status(nav: pd.DataFrame, rows: list[int], picks: list[dict], results: dict,
                  data: dict) -> str:
    sessions = data["panel"]["close"].index
    last = sessions[-1]
    nifty = data["nifty"].reindex(sessions).ffill()
    ma = nifty.rolling(200, min_periods=180).mean()
    risk_on = bool(nifty.iloc[-1] > ma.iloc[-1])
    lines = [f"# S1 paper shadow (started {START.date()}; PAPER ONLY, no orders)",
             f"As of {last.date()} · regime now: {'RISK-ON' if risk_on else 'RISK-OFF'} "
             f"(NIFTY {nifty.iloc[-1]:,.0f} vs 200-DMA {ma.iloc[-1]:,.0f})", ""]
    r = nav.iloc[-1]
    lines.append("| Track | NAV (100 = start) | vs NIFTY |")
    lines.append("|---|---|---|")
    for name in list(VARIANTS) + ["NIFTY"]:
        lines.append(f"| {name} | {r[name]:.2f} | {r[name] - r['NIFTY']:+.2f} |" if name != "NIFTY"
                     else f"| NIFTY | {r['NIFTY']:.2f} | — |")
    if not rows:
        pre = last < START
        nxt = "first signal = the last October session (fill at the first November open); flat until then"
        lines += ["", ("Tracking begins tomorrow — armed and flat. " if pre else
                       "No rebalance yet — armed and flat. ") + f"Next decision: {nxt}."]
    else:
        p = picks[-1]
        book = ", ".join(p["picks"]) if (p["risk_on"] and p["picks"]) else "liquid fund (risk-off)"
        reb = results["S1"].rebalances
        lines += ["", f"Last signal {p['signal'].date()} → {'RISK-ON' if p['risk_on'] else 'RISK-OFF'} · "
                  f"book: {book}", f"Rebalances so far: {len(reb)} · S1 costs paid ₹{results['S1'].costs_paid:,.0f}"]
        if results["S1H"].rebalances.shape[0]:
            h = results["S1H"].rebalances.iloc[-1]
            lines.append(f"S1H hedge: {int(h.get('hedge_lots', 0))} lot(s), notional ₹{h.get('hedge', 0):,.0f}")
    lines += mc.shadow_status_lines()
    lines += ["", "Gated evidence: alpha_lab/reports/FINDINGS.md · rules: alpha_lab/PLAN.md §S1 + Amendments v2."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true", help="scheduled run: refresh + Telegram notices")
    ap.add_argument("--status", action="store_true", help="refresh files and print, no messages")
    args = ap.parse_args()
    t0 = time.time()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    data = load()
    sessions = data["panel"]["close"].index
    last = sessions[-1]
    results, rows, picks = run_shadow(data)
    nav = nav_frame(results, data["nifty"], sessions, START)
    NAV_CSV.parent.mkdir(parents=True, exist_ok=True)
    nav.round(4).to_csv(NAV_CSV)
    status = render_status(nav, rows, picks, results, data)
    STATUS_MD.write_text(status + "\n")
    print(status)
    print(f"[{time.time() - t0:.0f}s] sessions≥start: {len(nav)} · signals: {len(rows)}")

    if not args.daily:
        return
    # one-time arming notice
    if not state.get("armed_notified"):
        state["armed_notified"] = True
        telegram("📄 S1 paper shadow is live (from 15 Oct 2026). Flat until the October month-end signal; "
                 "fills at the first November open. I'll message fills and a Friday NAV line. /shadow any time. "
                 "Paper only — no orders.")
    # fill-day notice: a rebalance executed at today's open
    fill_key = None
    if rows and len(results["S1"].rebalances):
        reb = results["S1"].rebalances.iloc[-1]
        if pd.Timestamp(reb["exec"]) == last:
            fill_key = str(last.date())
    if fill_key and state.get("last_fill_notified") != fill_key:
        state["last_fill_notified"] = fill_key
        p = picks[-1]
        book = ", ".join(p["picks"][:20]) if (p["risk_on"] and p["picks"]) else "liquid fund (risk-off)"
        r = nav.iloc[-1]
        h = results["S1H"].rebalances.iloc[-1]
        telegram(f"📄 S1 shadow: rebalance filled at today's open ({last.date()}).\n"
                 f"Signal {p['signal'].date()} → {'RISK-ON' if p['risk_on'] else 'RISK-OFF'}\n"
                 f"Book: {book}\n"
                 f"S1H hedge: {int(h.get('hedge_lots', 0))} lot(s)\n"
                 f"NAV since start — S1 {r['S1'] - 100:+.2f}% · S1H {r['S1H'] - 100:+.2f}% · "
                 f"NIFTY {r['NIFTY'] - 100:+.2f}%\nPaper only.")
    # Friday NAV line (keyed to the session date, so holidays/catch-ups never double-send)
    if last.weekday() == 4 and state.get("last_friday_notified") != str(last.date()):
        state["last_friday_notified"] = str(last.date())
        r = nav.iloc[-1]
        telegram(f"📄 Shadow week ({last.date()}): S1 {r['S1'] - 100:+.2f}% · S1H {r['S1H'] - 100:+.2f}% · "
                 f"NIFTY {r['NIFTY'] - 100:+.2f}% since 15 Oct. /shadow for details.")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
