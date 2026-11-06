#!/usr/bin/env python
"""Weekly decision journal (A2, QuantLab adoption 15 Oct 2026) — deterministic template, no LLM.

Composes one screenful of markdown answering "what did the system decide this week and why":
Decision Desk actions (rebalances, orders, costs), the S1/S1H paper shadow, vetoes that fired,
regime state, NAV vs NIFTY for the week, the next decision date, and job failures. Every section
degrades honestly when its source is down — the journal never fabricates and never blocks.

Sources (localhost only — ui-api proxies the controller's telemetry; shadow artifacts are files):
  GET /api/desk/status        Desk NAV history, positions, plans/orders, events (routers/desk.py)
  GET /api/market/monitor     regime score 0–4, breadth (data-service market_monitor)
  GET /api/telemetry/status   controller scheduler job list incl. last_status (proxied :8008)
  GET /api/telemetry/logs     controller log ring tail (ERROR lines → failures)
  alpha_lab/reports/shadow_nav.csv, shadow_status.md, today_book.md   (alpha_shadow_daily 19:50)

This script NEVER sends a Telegram message. The scheduled sender is master_controller's
`weekly_journal` job (Fri 20:10 IST), which runs this with no flags, writes
reports/journal/<YYYY-WW>.md and forwards the compact digest via the controller's AlertDispatcher.

    PYTHONPATH=. python scripts/journal_composer.py --dry-run          # print only, write nothing
    PYTHONPATH=. python scripts/journal_composer.py [--date 2026-10-17] [--out reports/journal]
                                                    [--base http://localhost:8010]

Prints `RESULT {json}` (week, path, summary, telegram) as the last line for the scheduler.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from daily_wrap import Api, inr, pct  # noqa: E402 — the wrap's honest GET helper and formatters

SHADOW_DIR = ROOT / "alpha_lab" / "reports"
SCORE_WORD = ["RISK-OFF", "DEFENSIVE", "MIXED", "CONSTRUCTIVE", "STRONG"]


# ── Calendar ─────────────────────────────────────────────────────────────────────
def week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_window(day: date) -> tuple[date, date]:
    """Monday → Friday of `day`'s ISO week."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=4)


def last_weekday_of_month(day: date) -> date:
    nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1)   # first of next month
    end = nxt - timedelta(days=1)
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    return end


def weekdays_until(day: date, target: date) -> int:
    return sum(1 for i in range(1, max((target - day).days, 0) + 1)
               if (day + timedelta(days=i)).weekday() < 5)


def _d(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


# ── Decision Desk ────────────────────────────────────────────────────────────────
def desk_lines(desk: Optional[dict], monday: date, friday: date) -> list[str]:
    if not desk:
        return ["- Desk status unavailable (ui-api /api/desk/status did not answer)."]
    meta, latest = desk.get("meta") or {}, desk.get("latest") or {}
    nav_rows = [r for r in desk.get("nav") or [] if _d(r.get("date"))]
    week_rows = [r for r in nav_rows if monday <= _d(r["date"]) <= friday]
    out = []
    nav = latest.get("nav")
    if nav is not None:
        start_cap = meta.get("start_capital")
        bits = [f"NAV {inr(nav)}"]
        if len(week_rows) >= 2 and week_rows[0].get("nav"):
            bits.append(f"{pct((nav / week_rows[0]['nav'] - 1) * 100)} this week ({len(week_rows)} marks)")
        elif nav_rows:
            bits.append("week change n/a (fewer than 2 marks this week)")
        if start_cap:
            bits.append(f"{pct((nav / start_cap - 1) * 100)} since start")
        bits.append(f"{int(latest.get('positions') or 0)} positions")
        if latest.get("drawdown") is not None:
            bits.append(f"drawdown {pct(latest['drawdown'])}")
        out.append("- " + " · ".join(bits))
    else:
        out.append("- Desk has no NAV marks yet.")
    if meta.get("stopped"):
        out.append("- ⛔ EMERGENCY-STOPPED (−20% from peak rule): manual /api/desk/reenable required.")
    plans = [p for p in desk.get("plans") or [] if _d(p.get("created_at")) and
             monday <= _d(p["created_at"]) <= friday]
    for p in plans:
        orders = p.get("orders") or []
        buys = sum(1 for o in orders if str(o.get("side", "")).lower() == "buy")
        sells = len(orders) - buys
        s = p.get("summary") or {}
        cost = s.get("est_costs") or s.get("costs")
        out.append(f"- Rebalance plan {str(p.get('plan_id', ''))[:24]}: {buys} buys / {sells} sells"
                   + (f" · est costs {inr(cost)}" if cost is not None else ""))
    if not plans:
        out.append("- No rebalance this week (monthly cadence — see Next decisions).")
    events = [e for e in desk.get("events") or [] if _d(e.get("ts")) and monday <= _d(e["ts"]) <= friday]
    if events:
        kinds: dict[str, int] = {}
        for e in events:
            kinds[str(e.get("kind") or e.get("type") or "event")] = kinds.get(
                str(e.get("kind") or e.get("type") or "event"), 0) + 1
        out.append("- Events: " + " · ".join(f"{k} ×{n}" for k, n in sorted(kinds.items())))
    return out


# ── S1/S1H paper shadow (files written by the 19:50 job) ─────────────────────────
def shadow_lines(monday: date, friday: date, shadow_dir: Path = SHADOW_DIR) -> list[str]:
    nav_csv = shadow_dir / "shadow_nav.csv"
    status_md = shadow_dir / "shadow_status.md"
    if not nav_csv.exists():
        return ["- Shadow artifacts missing (alpha_shadow_daily has not produced shadow_nav.csv)."]
    rows = [ln.split(",") for ln in nav_csv.read_text().strip().splitlines()]
    head, body = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
    if not body or head[0] != "date":
        return ["- shadow_nav.csv is empty or malformed."]
    last = body[-1]
    cols = {name: i for i, name in enumerate(head)}
    out = ["- Since 15 Oct start: " + " · ".join(
        f"{name} {pct(float(last[cols[name]]) - 100)}" for name in head[1:] if name in cols)]
    wk = [r for r in body if (d := _d(r[0])) and monday <= d <= friday]
    if len(wk) >= 2:
        out.append("- This week: " + " · ".join(
            f"{name} {pct(float(wk[-1][cols[name]]) / float(wk[0][cols[name]]) * 100 - 100)}"
            for name in head[1:]) + f" ({len(wk)} sessions)")
    else:
        out.append(f"- Week change n/a ({len(wk)} session(s) of shadow NAV inside this week).")
    if status_md.exists():
        txt = status_md.read_text()
        m = re.search(r"Rebalances so far: (\d+)", txt)
        out.append(f"- Rebalances so far: {m.group(1)}" if m else
                   "- No rebalance yet — armed and flat; first signal = the last October session.")
    out.append("- Benchmarks: NIFTY above; the EW-universe benchmark is a gate-time artifact "
               "(FINDINGS.md), not tracked live.")
    return out


# ── Vetoes (run_today.py's book) ─────────────────────────────────────────────────
def veto_lines(shadow_dir: Path = SHADOW_DIR, max_names: int = 6) -> list[str]:
    book = shadow_dir / "today_book.md"
    if not book.exists():
        return ["- today_book.md missing (run_today.py has not been run)."]
    txt = book.read_text()
    out = []
    m = re.search(r"as of (\d{4}-\d{2}-\d{2})", txt)
    blocked = re.search(r"top (\d+) by liquidity.*?blocked today: (\d+)", txt)
    if blocked:
        out.append(f"- {blocked.group(2)} of {blocked.group(1)} universe names blocked"
                   + (f" (as of {m.group(1)})" if m else ""))
    refused = re.findall(r"^- ([A-Z0-9&-]+) \(rank (\d+)\): (.+)$", txt, re.M)
    if refused:
        shown = " · ".join(f"{sym} r{rank} [{why}]" for sym, rank, why in refused[:max_names])
        more = f" · +{len(refused) - max_names} more" if len(refused) > max_names else ""
        out.append(f"- Momentum leaders refused: {shown}{more}")
    return out or ["- today_book.md present but no veto lines parsed."]


# ── Regime ───────────────────────────────────────────────────────────────────────
def regime_lines(monitor: Optional[dict], shadow_dir: Path = SHADOW_DIR) -> list[str]:
    out = []
    reg = (monitor or {}).get("regime") or {}
    if reg.get("score") is not None:
        score = int(reg["score"])
        word = SCORE_WORD[score] if 0 <= score < len(SCORE_WORD) else "?"
        days = reg.get("days_at_score")
        out.append(f"- Market monitor: {score}/4 {word} · exposure guide {reg.get('exposure', '—')}"
                   + (f" · {days} days at this score"
                      + (" (changed this week)" if isinstance(days, int) and days < 5 else "")
                      if days is not None else ""))
    else:
        out.append("- Market monitor regime unavailable.")
    status_md = shadow_dir / "shadow_status.md"
    if status_md.exists():
        m = re.search(r"regime now: (RISK-\w+) \(([^)]+)\)", status_md.read_text())
        if m:
            out.append(f"- S1 crash filter: {m.group(1)} ({m.group(2)})")
    return out


# ── Next decisions ───────────────────────────────────────────────────────────────
def next_decision_lines(today: date) -> list[str]:
    signal = last_weekday_of_month(today)
    if signal == today:
        return ["- TODAY was the month-end momentum signal (decided at tonight's close); "
                "fills at the next session's open.",
                "- Desk and S1 shadow decide on the same cadence; crash filter is evaluated at the signal."]
    if signal < today:                                       # month end already passed this week
        signal = last_weekday_of_month(today + timedelta(days=7))
    n = weekdays_until(today, signal)
    return [f"- Month-end momentum signal: {signal:%a %d %b} (last weekday of the month), "
            f"{n} weekday(s) away; fills at the next open. NSE holidays not subtracted.",
            "- Desk and S1 shadow decide on the same cadence; crash filter is evaluated at the signal."]


# ── Job health ───────────────────────────────────────────────────────────────────
def failure_lines(telemetry: Optional[dict], logs: Optional[list[str]], monday: date) -> list[str]:
    out = []
    jobs = ((telemetry or {}).get("scheduler") or {}).get("jobs") or []
    # Healthy statuses observed from the controller: "done" (its actual word — PM integration
    # caught the 15 Oct false positive where every successful job was reported as errored),
    # plus ok/success for safety and None for never-ran. Anything else surfaces.
    bad = [j["id"] for j in jobs if j.get("last_status") not in (None, "ok", "success", "done", "no new data", "skipped")]
    if bad:
        out.append(f"- Jobs whose LAST run errored: {', '.join(sorted(bad))}")
    errors: dict[str, int] = {}
    window_start = None
    for ln in logs or []:
        try:
            rec = json.loads(ln)
        except (TypeError, ValueError):
            continue
        ts = rec.get("ts", "")
        try:
            when = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        window_start = window_start or when
        if rec.get("level") == "ERROR" and when.date() >= monday:
            errors[rec.get("job", "?")] = errors.get(rec.get("job", "?"), 0) + 1
    if errors:
        out.append("- ERROR lines this week: " + " · ".join(
            f"{j} ×{n}" for j, n in sorted(errors.items(), key=lambda kv: -kv[1])[:8]))
    elif logs:
        out.append("- No ERROR lines in the controller log window.")
    else:
        out.append("- Controller telemetry unavailable (is master-controller on :8008 up?).")
    if window_start and window_start.date() > monday:
        out.append(f"- Honesty note: the log ring only reaches back to {window_start:%a %d %b %H:%M} — "
                   "earlier failures this week are not visible here.")
    return out


# ── Composition ──────────────────────────────────────────────────────────────────
def compose_weekly(api: Api, today: date, root: Path = ROOT) -> tuple[str, str]:
    """The week's journal → (markdown page, compact Telegram digest). Deterministic given inputs."""
    monday, friday = week_window(today)
    shadow_dir = root / "alpha_lab" / "reports"
    desk = api.get("/api/desk/status")
    monitor = api.get("/api/market/monitor")
    telemetry = api.get("/api/telemetry/status")
    logs = api.get("/api/telemetry/logs", limit=500)

    d_lines = desk_lines(desk, monday, friday)
    s_lines = shadow_lines(monday, friday, shadow_dir)
    v_lines = veto_lines(shadow_dir)
    r_lines = regime_lines(monitor, shadow_dir)
    n_lines = next_decision_lines(today)
    f_lines = failure_lines(telemetry, logs, monday)

    md = [f"# Weekly decision journal — {week_key(today)} ({monday:%d %b} → {friday:%d %b %Y})",
          "", "PAPER ONLY — nothing below is a live order or a trade instruction.", "",
          "## Decision Desk (paper, monthly momentum)", *d_lines, "",
          "## S1/S1H paper shadow (alpha_lab)", *s_lines, "",
          "## Vetoes that fired (S1 avoid rules)", *v_lines, "",
          "## Regime", *r_lines, "",
          "## Next decisions", *n_lines, "",
          "## Job health this week", *f_lines]
    if api.missing:
        md += ["", "Sources that did not answer: " + " · ".join(api.missing)]
    md += ["", "Deterministic template (scripts/journal_composer.py, no LLM) · evidence: "
           "alpha_lab/reports/FINDINGS.md · plan: docs/PRODUCT_STRATEGY.md"]

    tg = "\n".join([f"🗒 Weekly journal {week_key(today)} ({monday:%d %b}–{friday:%d %b})",
                    "Desk: " + d_lines[0].lstrip("- "),
                    "Shadow: " + s_lines[0].lstrip("- "),
                    "Regime: " + "; ".join(x.lstrip("- ") for x in r_lines[:1]),
                    "Vetoes: " + v_lines[0].lstrip("- "),
                    "Next: " + n_lines[0].lstrip("- "),
                    "Jobs: " + f_lines[0].lstrip("- "),
                    f"Full page: reports/journal/{week_key(today)}.md"])[:3500]
    return "\n".join(md) + "\n", tg


def main() -> None:
    ap = argparse.ArgumentParser(description="Compose the weekly decision journal (deterministic, "
                                             "paper-only; the controller sends the Telegram digest).")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out", default="reports/journal")
    ap.add_argument("--base", default=os.getenv("UI_API_URL", "http://localhost:8010"))
    ap.add_argument("--dry-run", action="store_true", help="print the markdown; write and send nothing")
    args = ap.parse_args()
    today = date.fromisoformat(args.date)
    md, tg = compose_weekly(Api(args.base), today)
    if args.dry_run:
        print(md)
        print("── Telegram digest (dry-run — NOT sent, composer never sends) ──")
        print(tg)
        return
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{week_key(today)}.md"
    path.write_text(md)
    print(md)
    summary = md.splitlines()[0].lstrip("# ")
    print("RESULT " + json.dumps({"week": week_key(today), "path": str(path.relative_to(ROOT)),
                                  "summary": summary, "telegram": tg}))


if __name__ == "__main__":
    main()
