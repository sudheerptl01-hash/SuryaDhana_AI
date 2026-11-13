#!/usr/bin/env python
"""
Daily market wrap: one markdown page per session, written after the evening data has landed (scheduled 21:00 IST
by the master controller; the WRAP page in the terminal shows the archive). Facts only, from the terminal's own
endpoints: no forecasts and nothing here is a trade signal.

    PYTHONPATH=. python scripts/daily_wrap.py [--date 2026-10-12] [--out reports/daily_wrap] [--base http://localhost:8010]

Prints `RESULT {json}` (date, path, one-line summary) as the last line for the scheduler.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

ROOT = Path(__file__).resolve().parents[1]
SCORE_WORD = ["RISK-OFF", "DEFENSIVE", "MIXED", "CONSTRUCTIVE", "STRONG"]


def pct(v: Optional[float], d: int = 2) -> str:
    if v is None:
        return "—"
    r = round(float(v), d) or 0.0
    return f"{'+' if r > 0 else ''}{r:.{d}f}%"


def crore(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}₹{abs(v):,.0f} cr"


def inr(v: float) -> str:
    """Indian digit grouping: 501042 → 5,01,042."""
    neg, n = v < 0, f"{abs(v):.0f}"
    head, tail = n[:-3], n[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    out = ",".join(([head] if head else []) + groups + [tail]) if head or groups else tail
    return f"{'−' if neg else ''}₹{out}"


def num(v: Optional[float], d: int = 0) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def next_weekday(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


class Api:
    """GET helper: a failing endpoint yields None and is listed under 'missing' instead of breaking the wrap."""

    def __init__(self, base: str) -> None:
        self.client = httpx.Client(base_url=base.rstrip("/"), timeout=60)
        self.missing: list[str] = []

    def get(self, path: str, **params: Any) -> Any:
        try:
            r = self.client.get(path, params=params or None)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 — one source down must not lose the whole wrap
            self.missing.append(f"{path} ({str(exc)[:60]})")
            return None


def section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", "", *lines, ""] if lines else []


def ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 11 → '11th', 23 → '23rd'."""
    n = int(n)
    return f"{n}{'th' if 11 <= abs(n) % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(abs(n) % 10, 'th')}"


def valuation_line(ix: dict[str, Any], vs: dict[str, Any] | None = None, rel: dict[str, Any] | None = None) -> str:
    """'- Valuation (NSE): NIFTY P/E 19.4× (12th percentile since Mar 2021, median 22.1×) · P/B 2.79 · dividend yield
    1.51% · Midcap 150 28.3× · Smallcap 250 34.4×'. `vs` = index-valuation's vs_history (same-basis days only)."""
    n = ix.get("NIFTY 50") or {}
    if n.get("pe") is None:
        return ""
    h = (vs or {}).get("NIFTY 50") or {}
    since = ""
    if h.get("pctl") is not None and h.get("since"):
        since = f" ({ordinal(h['pctl'])} percentile since {date.fromisoformat(h['since']):%b %Y}, median {h['median']}×)"
    out = f"- Valuation (NSE): NIFTY P/E {n['pe']:.1f}×{since} · P/B {n.get('pb') or 0:.2f} · dividend yield {n.get('dy') or 0:.2f}%"
    for name, label in (("NIFTY MIDCAP 150", "Midcap 150"), ("NIFTY SMALLCAP 250", "Smallcap 250")):
        if (ix.get(name) or {}).get("pe") is not None:
            out += f" · {label} {ix[name]['pe']:.1f}×"
            r = (rel or {}).get(name) or {}
            if r.get("pctl") is not None and (r["pctl"] >= 80 or r["pctl"] <= 20):    # only a stretched premium / discount
                out += f" ({r['ratio']}× NIFTY, {ordinal(r['pctl'])} percentile)"
    return out


def short_line(rows: list[dict[str, Any]], min_pct: float = 1.0, min_days: int = 2) -> str:
    """'- Institutional short selling, last 5 sessions: HEROMOTOCO 4.2% of volume (4 days) · …' — persistent short
    sales that are a real share of trading (NSE disclosure; no client names)."""
    hit = [r for r in rows if (r.get("short_pct_of_volume") or 0) >= min_pct and (r.get("days") or 0) >= min_days][:4]
    if not hit:
        return ""
    return "- Institutional short selling, last 5 sessions: " + " · ".join(
        f"{r['symbol']} {r['short_pct_of_volume']:.1f}% of volume ({r['days']} days)" for r in hit)


def movers_line(contrib: dict[str, Any]) -> str:
    """'- Who moved NIFTY (points): TCS +31 · INFY +31 · ICICIBANK +30 · drag KOTAKBANK −7 (explains +357 of +359)'."""
    ms = [m for m in contrib.get("members") or [] if m.get("points") is not None]
    if len(ms) < 5:
        return ""
    up = [m for m in ms if m["points"] > 0][:3]
    dn = [m for m in reversed(ms) if m["points"] < 0][:2]
    txt = " · ".join(f"{m['symbol']} {m['points']:+.0f}" for m in up)
    if dn:
        txt += " · drag " + " · ".join(f"{m['symbol']} {m['points']:+.0f}" for m in dn)
    if contrib.get("change") is not None:
        txt += f" (weights rebuilt from filings explain {contrib.get('explained_points', 0):+.0f} of {contrib['change']:+.0f})"
    return f"- Who moved NIFTY (points): {txt}"


def internals_lines(sm: dict[str, Any]) -> list[str]:
    """Breadth through the session (market-internals samples): the closing A/D, the day's swing in net breadth,
    and a flag when NIFTY and the average stock went different ways."""
    if not sm or not sm.get("samples"):
        return []
    line = (f"- Through the day (NIFTY 500, {sm['samples']} samples {str(sm.get('first', ''))[12:]}–{str(sm.get('last', ''))[12:]}): "
            f"net breadth ranged {num(sm.get('net_worst'))} to {num(sm.get('net_best'))}, ended {num(sm.get('net_now'))}")
    if sm.get("small_minus_n50") is not None:
        line += f" · small caps {pct(sm['small_minus_n50'])} vs NIFTY 50"
    out = [line]
    if sm.get("divergence"):
        out.append(f"- ⚠ **{sm['divergence'][:1].upper() + sm['divergence'][1:]}**: the index move came from a few heavyweights.")
    return out


def numbers_note(f: Optional[dict[str, Any]], iso: str) -> str:
    """', revenue +11% / profit +21% y/y' from the filing's XBRL, only if the cached quarter was filed that day."""
    if not f or not str(f.get("filed_at") or "").startswith(iso):
        return ""
    rev = f"revenue {pct(f['revenue_yoy'], 0)}" if f.get("revenue_yoy") is not None else None
    pat = f"profit {f['pat_yoy_turn']}" if f.get("pat_yoy_turn") else f"profit {pct(f['pat_yoy'], 0)}" if f.get("pat_yoy") is not None else None
    parts = [x for x in (rev, pat) if x]
    return f", {' / '.join(parts)} y/y" if parts else ""


def concentration_line(book: list[dict], quotes: dict) -> str:
    """'- Book ₹1,36,472: CUPID 52% · AEROFLEX 41% · … (behaves like 2.3 equal positions)' at today's prices, or ''."""
    vals = []
    for p in book:
        sym = str(p.get("symbol", "")).upper()
        qq = quotes.get(f"{sym}.NS") or {}
        if qq.get("available") and qq.get("price") and p.get("quantity"):
            vals.append((sym, float(qq["price"]) * float(p["quantity"])))
    total = sum(v for _, v in vals)
    if len(vals) < 2 or total <= 0:
        return ""
    vals.sort(key=lambda x: -x[1])
    eff = 1 / sum((v / total) ** 2 for _, v in vals)
    parts = " · ".join(f"{s} {v / total * 100:.0f}%" for s, v in vals[:4])
    return f"- Book {inr(total)}: {parts} (behaves like {eff:.1f} equal positions)"


def next_expiry(opt: dict[str, Any], iso: str) -> Optional[str]:
    """The expiry to describe for 'tomorrow': None if the chain's own expiry is still ahead, else the first later one."""
    exp = str(opt.get("expiry") or "")
    if not opt.get("found") or not exp or exp > iso:
        return None
    later = sorted(e for e in opt.get("expiries") or [] if str(e) > iso)
    return later[0] if later else None


# ── one date per wrap (review M10) ─────────────────────────────────────────────────────────────────────────────
# Every section is built from data dated the wrap's day, or says "data for <day> not stored". The 04 Nov 2026 wrap
# printed 30 Oct breadth, sectors, movers, the crash-filter line and a 30 Oct option chain under a 04 Nov heading.
# A machine-readable marker at the end records each section's status, so a later run (and --backfill-missing)
# knows which wraps are incomplete or stale.
REQUIRED = ("session", "breadth", "regime", "crash_filter", "sectors", "movers", "cash_flows", "results", "desk")
MARKER = "<!-- wrap-sections "
NOT_STORED = "not_stored"


def dmy(iso: str) -> str:
    """'2026-11-04' → '04 Nov'."""
    try:
        return f"{date.fromisoformat(str(iso)[:10]):%d %b}"
    except ValueError:
        return str(iso)


def not_stored(day: date, what: str, latest: Optional[str] = None) -> str:
    return f"- {what}: data for {day:%d %b} not stored" + (f" (latest stored {dmy(latest)})" if latest else "")


def closes_by_date(payload: Any) -> dict[str, float]:
    return {str(r["date"])[:10]: float(r["close"]) for r in (payload or {}).get("rows") or [] if r.get("close") is not None}


def session_change(closes: dict[str, float], iso: str) -> Optional[tuple[float, float]]:
    """(close, % vs the previous stored session) for `iso`, or None when that session is not stored."""
    if iso not in closes:
        return None
    prev = [d for d in closes if d < iso]
    if not prev:
        return None
    c, p = closes[iso], closes[max(prev)]
    return c, (c / p - 1) * 100 if p else 0.0


def crash_filter_on(closes: dict[str, float], iso: str) -> Optional[dict[str, Any]]:
    """The Desk crash filter recomputed for a past session from stored NIFTY 50 closes (200-session mean, at least 180
    sessions, as data-service's /db/crash-filter does)."""
    days = sorted(d for d in closes if d <= iso)
    if not days or days[-1] != iso or len(days) < 180:
        return None
    last = [closes[d] for d in days[-200:]]
    sma = sum(last) / len(last)
    nifty = closes[iso]
    d = date.fromisoformat(iso)
    month_end = date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)
    while month_end.weekday() >= 5:
        month_end -= timedelta(days=1)
    return {"date": iso, "nifty": nifty, "sma200": sma, "risk_on": nifty > sma,
            "move_needed_pct": 0.0 if nifty > sma else (sma / nifty - 1) * 100, "next_signal_date": month_end.isoformat()}


def mtd_flows(rows: list[dict[str, Any]], sessions: list[str], iso: str) -> Optional[dict[str, Any]]:
    """Month-to-date FII / DII through `iso` counted against the stored session calendar: sums over the sessions that
    have figures and the 'n of m sessions' label (review M09: never a silent skip)."""
    month = iso[:7]
    cal = sorted({d for d in sessions if d.startswith(month) and d <= iso} | {str(r["date"])[:10] for r in rows
                                                                             if str(r["date"]).startswith(month) and str(r["date"]) <= iso})
    have = {str(r["date"])[:10] for r in rows}
    sums: dict[str, float] = {}
    for r in rows:
        d = str(r["date"])[:10]
        if d.startswith(month) and d <= iso and r.get("net_cr") is not None:
            sums[r["category"]] = sums.get(r["category"], 0.0) + float(r["net_cr"])
    n = sum(1 for d in cal if d in have)
    return {"sums": sums, "present": n, "expected": len(cal), "missing": [d for d in cal if d not in have]} if cal else None


def next_session(day: date, holidays: set[str]) -> date:
    """The next NSE session after `day`: weekends and NSE holidays (ECO's HOLIDAY rows) skipped."""
    n = next_weekday(day)
    while n.isoformat() in holidays:
        n = next_weekday(n)
    return n


def sections_marker(status: dict[str, str]) -> str:
    return MARKER + json.dumps(status, sort_keys=True) + " -->"


def read_marker(text: str) -> Optional[dict[str, str]]:
    for ln in reversed(text.splitlines()):
        if ln.startswith(MARKER) and ln.endswith("-->"):
            try:
                return json.loads(ln[len(MARKER):-3].strip())
            except ValueError:
                return None
    return None


def wrap_needs_rebuild(text: str, iso: str) -> Optional[str]:
    """Why an existing wrap should be rebuilt: a legacy wrap written from another day's end-of-day data (the 04 Nov
    2026 file says 'NSE end of day 2026-10-30'), or one whose marker lists sections that were not stored. None when
    the wrap is complete."""
    marker = read_marker(text)
    if marker is not None:
        gaps = sorted(k for k, v in marker.items() if v == NOT_STORED)
        return f"incomplete: {', '.join(gaps)}" if gaps else None
    import re as _re
    m = _re.search(r"NSE end of day (\d{4}-\d{2}-\d{2})", text)
    if m and m.group(1) != iso:
        return f"legacy wrap written from {m.group(1)} data"
    return None


def build(api: Api, day: date, *, refresh: bool = True) -> tuple[str, str]:
    """Return (markdown, one-line summary). `build_report` also returns the per-section status."""
    md, summary, _ = build_report(api, day, refresh=refresh)
    return md, summary


def written_line(day: date, now: datetime) -> str:
    """The header's provenance clause. A wrap written on a later day says so with the write date ('Backfilled 06 Nov
    08:55 IST … for 04 Nov'), so it never reads as written before that session's open (checker, 6 Nov)."""
    if now.date() == day:
        return f"Written {now:%H:%M} IST from the terminal's stored data for {day:%d %b %Y}"
    return f"Backfilled {now:%d %b %Y %H:%M} IST from the terminal's stored data for {day:%d %b %Y}"


def build_report(api: Api, day: date, *, refresh: bool = True, now: Optional[datetime] = None) -> tuple[str, str, dict[str, str]]:
    """Every section from data dated `day`, or a 'data for <day> not stored' line. Returns (markdown, summary,
    status) where status maps each section to 'ok' / 'not_stored' / 'n/a' (live-only sections on a past day)."""
    iso = day.isoformat()
    today = day == date.today()
    if today and refresh:                     # NSE posts FII/DII in the evening: fetch it now rather than rely on 20:30
        try:
            api.client.post("/api/market/fii-dii-cash/refresh")
        except Exception:  # noqa: BLE001 — the figure is optional
            pass
    back = max(0, (date.today() - day).days)
    st: dict[str, str] = {}
    # a past day reads the snapshot as of that session; a data-service without that read returns the latest one,
    # whose stored breadth history still covers the day (the as_of check below keeps its sections out)
    mon = (None if today else api.get("/api/market/monitor", as_of=iso)) or api.get("/api/market/monitor") or {}
    mon_ok = mon.get("as_of") == iso
    hist_row = next((h for h in mon.get("history") or [] if str(h.get("date")) == iso), None)
    hist_prev = max((h for h in mon.get("history") or [] if str(h.get("date")) < iso), key=lambda h: str(h["date"]), default=None)
    n50 = closes_by_date(api.get("/api/market/index-daily", symbol="NIFTY50", days=400))
    sessions = sorted(n50)
    cash = api.get("/api/market/fii-dii-cash", days=back + 40) or {}
    parts = api.get("/api/market/participants", days=back + 20) or {}
    deals = api.get("/api/market/deals", days=back + 1, min_value=1e7) or {}
    insiders = api.get("/api/market/insider-buys", days=back + 7, min_value=1e6) or {}
    results = api.get("/api/market/results-recent", days=back + 3) or {}
    events = api.get("/api/market/events") or {}
    desk = api.get("/api/desk/status") or {}
    internals = api.get("/api/market/internals", day=iso) or {}
    eco_all = (api.get("/api/market/eco-calendar", back=back, ahead=10) or {}).get("events") or []
    holidays = {e["date"] for e in eco_all if e.get("kind") == "HOLIDAY"}

    L: list[str] = [f"# Market wrap · {day:%a %d %b %Y}", "",
                    written_line(day, now or datetime.now())
                    + (f" (NSE end of day {mon.get('as_of')})" if mon_ok else "") + ". Facts only: nothing here is a trade signal.", ""]
    gap_note_at = len(L)

    # ── the session ──
    s: list[str] = []
    row = []
    for sym, name in (("NIFTY50", "NIFTY 50"), ("NIFTYBANK", "NIFTY BANK"), ("NIFTYMIDCAP100", "NIFTY MIDCAP 100"),
                      ("NIFTYSMALLCAP100", "NIFTY SMALLCAP 100")):
        got = session_change(n50 if sym == "NIFTY50" else closes_by_date(api.get("/api/market/index-daily", symbol=sym, days=back + 10)), iso)
        if got:
            row.append(f"{name} {num(got[0], 2)} ({pct(got[1])})")
    live: dict[str, Any] = {}
    if not row and today:                      # the EOD index file has not landed: NSE's live feed, if it is today's
        live = api.get("/api/market/live-movers", universe="FOSec") or {}
        if str(live.get("timestamp", ""))[:11] == f"{day:%d-%b-%Y}":
            idx = {i["index"]: i for i in live.get("indices") or []}
            row = [f"{name} {num(i.get('last'), 2)} ({pct(i.get('change_pct'))})" for name in
                   ("NIFTY 50", "NIFTY BANK", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100") if (i := idx.get(name))]
    if row:
        s.append("- " + " · ".join(row))
        st["session"] = "ok"
    else:
        s.append(not_stored(day, "Index closes", sessions[-1] if sessions else None))
        st["session"] = NOT_STORED
    b = mon.get("breadth") or {} if mon_ok else {}
    if b:
        uni = f"liquid NSE universe, {num(b.get('universe'))} stocks" if b.get("universe") else "liquid NSE universe"
        s.append(f"- Breadth ({uni}): {num(b.get('adv'))} up / {num(b.get('dec'))} down · "
                 f"{num(b.get('pct_above50'), 0)}% above the 50-day, {num(b.get('pct_above200'), 0)}% above the 200-day · "
                 f"new highs / lows {num(b.get('new_highs'))} / {num(b.get('new_lows'))} · India VIX {num(b.get('vix'), 2)}")
        st["breadth"] = "ok"
    elif hist_row:                             # the stored breadth history keeps the day's shape, not its A/D counts
        net = (hist_row["ad_line"] - hist_prev["ad_line"]) if hist_prev and hist_row.get("ad_line") is not None else None
        s.append(f"- Breadth (liquid NSE universe, from the stored breadth history): net advances {num(net)} · "
                 f"{num(hist_row.get('pct_above50'), 0)}% above the 50-day, {num(hist_row.get('pct_above200'), 0)}% above the 200-day · "
                 f"new highs − lows {num(hist_row.get('nh_nl'))} (advances / declines and VIX for that day are not stored)")
        st["breadth"] = "ok"
    else:
        s.append(not_stored(day, "Breadth", mon.get("as_of")))
        st["breadth"] = NOT_STORED
    sm = internals.get("summary") or {}
    if str(internals.get("day")) == iso and sm.get("samples"):
        s += internals_lines(sm)
    drv = api.get("/api/market/index-drivers", index="NIFTY 50", horizon="1d", as_of=iso) or {}
    if drv.get("as_of") == iso and drv.get("members"):
        line = movers_line({"members": drv["members"], "change": drv.get("index_move_pts"), "explained_points": drv.get("explained_pts")})
        if line:
            s.append(line.replace("weights rebuilt from filings explain", "stored driver fit explains"))
    elif today:
        line = movers_line((api.get("/api/market/index-contribution", index="NIFTY 50") or {}))
        if line:
            s.append(line)
    iv = api.get("/api/market/index-valuation") or {}
    if str(iv.get("timestamp", ""))[:11] == f"{day:%d-%b-%Y}":
        line = valuation_line(iv.get("indices") or {}, iv.get("vs_history"), iv.get("rel_history"))
        if line:
            s.append(line)
    else:
        pts = (api.get("/api/market/index-valuation-history", index="NIFTY 50") or {}).get("points") or []
        pe = next((p.get("v") for p in pts if str(p.get("date")) == iso), None)
        if pe is not None:
            s.append(f"- Valuation (NSE): NIFTY P/E {pe:.1f}× (that day's NSE figure)")
    reg = mon.get("regime") or {} if mon_ok else {}
    if reg:
        sc = int(reg.get("score", 0))
        s.append(f"- Regime **{sc}/4 {SCORE_WORD[max(0, min(sc, 4))]}** (exposure guide {reg.get('exposure', '—')}, "
                 f"{reg.get('days_at_score', '—')} sessions at this score)")
        st["regime"] = "ok"
    elif hist_row and hist_row.get("score") is not None:
        sc = int(hist_row["score"])
        s.append(f"- Regime **{sc}/4 {SCORE_WORD[max(0, min(sc, 4))]}** (from the stored breadth history)")
        st["regime"] = "ok"
    else:
        s.append(not_stored(day, "Regime", mon.get("as_of")))
        st["regime"] = NOT_STORED
    crash = api.get("/api/market/crash-filter") or {}
    if crash.get("date") != iso:
        crash = crash_filter_on(n50, iso) or {}
    if crash:
        s.append(f"- Desk crash filter: NIFTY {num(crash.get('nifty'), 0)} vs 200-day {num(crash.get('sma200'), 0)} → "
                 + ("**risk-on**" if crash.get("risk_on") else f"**in the liquid fund**, needs {pct(crash.get('move_needed_pct'), 1)}")
                 + f" · next signal {crash.get('next_signal_date', '—')}")
        st["crash_filter"] = "ok"
    else:
        s.append(f"- Desk crash filter: not computed for {day:%d %b} (fewer than 180 stored NIFTY 50 closes)" if iso in n50
                 else not_stored(day, "Desk crash filter", sessions[-1] if sessions else None))
        st["crash_filter"] = NOT_STORED
    L += section("The session", s)

    # ── sectors ──
    secs = sorted((x for x in mon.get("sectors") or [] if x.get("ret_1d_pct") is not None), key=lambda x: -x["ret_1d_pct"]) if mon_ok else []
    if secs:
        fmt: Callable[[dict], str] = lambda x: f"{x['industry']} {pct(x['ret_1d_pct'], 1)}"  # noqa: E731
        L += section("Sectors (NSE industries, equal-weighted, 1 day)",
                     [f"- Best: {' · '.join(fmt(x) for x in secs[:3])}", f"- Worst: {' · '.join(fmt(x) for x in secs[-3:][::-1])}"])
        st["sectors"] = "ok"
    else:
        L += section("Sectors (NSE industries, equal-weighted, 1 day)", [not_stored(day, "Sector returns", mon.get("as_of"))])
        st["sectors"] = NOT_STORED

    # ── money flows ──
    f: list[str] = []
    crow = [r for r in cash.get("rows") or [] if str(r.get("date"))[:10] == iso]
    if crow:
        lat = {r["category"]: r.get("net_cr") for r in crow}
        mtd = mtd_flows(cash.get("rows") or [], sessions, iso)
        line = f"- Cash market ({'today' if today else dmy(iso)}, provisional): FII {crore(lat.get('FII'))} · DII {crore(lat.get('DII'))}"
        if mtd and mtd["expected"] > 1:
            line += (f" · month to date FII {crore(mtd['sums'].get('FII'))}, DII {crore(mtd['sums'].get('DII'))} "
                     f"({mtd['present']} of {mtd['expected']} sessions"
                     + (f"; no figures for {', '.join(dmy(d) for d in mtd['missing'])}" if mtd["missing"] else "") + ")")
        f.append(line)
        st["cash_flows"] = "ok"
    else:
        f.append(not_stored(day, "FII / DII cash", (cash.get("summary") or {}).get("latest_date"))
                 + " (NSE publishes only the latest session, so a missed evening cannot be re-fetched)")
        st["cash_flows"] = NOT_STORED
    fii = next((r for r in parts.get("snapshot") or [] if r.get("client_type") == "FII"), None) if parts.get("date") == iso else None
    if fii:
        f.append(f"- FII index futures: {fii.get('fut_long_pct')}% long, net change {num(fii.get('fut_net_chg_1d'))} contracts on the day "
                 f"(positioning does not predict NIFTY: RSCH)")
    else:
        fh = sorted(parts.get("fii_history") or [], key=lambda r: str(r.get("date")))
        i = next((k for k, r in enumerate(fh) if str(r.get("date")) == iso), None)
        if i is not None:
            chg = fh[i]["net"] - fh[i - 1]["net"] if i > 0 and fh[i].get("net") is not None and fh[i - 1].get("net") is not None else None
            f.append(f"- FII index futures: {fh[i].get('long_pct')}% long, net change {num(chg)} contracts on the day "
                     f"(positioning does not predict NIFTY: RSCH)")
    day_deals = [r for r in deals.get("rows") or [] if r.get("date") == iso]
    deal_net: dict[str, float] = {}
    for r in day_deals:
        deal_net[r["symbol"]] = deal_net.get(r["symbol"], 0.0) + (r["value"] if r["direction"] == "buy" else -r["value"])
    top = sorted((kv for kv in deal_net.items() if abs(kv[1]) >= 1e7), key=lambda kv: -abs(kv[1]))
    if top:
        f.append("- Biggest net block / bulk deal flows: " + " · ".join(f"{sym} {crore(v / 1e7)}" for sym, v in top[:6]))
    inst = [r for r in day_deals if r.get("institution")]
    if inst:
        f.append("- Mutual fund / insurer deals: " + " · ".join(
            f"{r['symbol']} {r['direction']} {crore(r['value'] / 1e7).lstrip('+')}" for r in sorted(inst, key=lambda r: -r["value"])[:5]))
    fresh = [r for r in insiders.get("rows") or [] if r.get("last_date") == iso]
    if fresh:
        f.append("- Insider buying disclosed that day (promoters / directors, market purchases): " + " · ".join(
            f"{r['symbol']} {crore(r['total_value'] / 1e7).lstrip('+')}" for r in fresh[:6]))
    if today:
        shorts = short_line((api.get("/api/market/short-selling", days=5) or {}).get("rows") or [])
        if shorts:
            f.append(shorts)
    L += section("Money flows", f)

    # ── movers ──
    mv = mon.get("movers") or {} if mon_ok else {}
    m: list[str] = []
    for key, label in (("gainers", "Gainers"), ("losers", "Losers"), ("volume_shockers", "Volume shockers")):
        rows = mv.get(key) or []
        if rows:
            extra = (lambda r: f" ({r['vol_x']:.0f}× vol)") if key == "volume_shockers" else (lambda r: "")
            m.append(f"- {label}: " + " · ".join(f"{r['symbol']} {pct(r.get('chg_pct'), 1)}{extra(r)}" for r in rows[:5]))
    st["movers"] = "ok" if m else NOT_STORED
    L += section("Movers (liquid NSE stocks)", m or [not_stored(day, "Gainers / losers", mon.get("as_of"))])

    # ── results ──
    st["results"] = "ok" if results else NOT_STORED
    reacted = [r for r in results.get("rows") or [] if r.get("reaction_date") == iso and r.get("move_pct") is not None]
    if reacted:
        reacted.sort(key=lambda r: -abs(r.get("vs_nifty_pct") or 0))
        L += section("Results reactions that session", [
            f"- {r['symbol']} {pct(r['move_pct'], 1)} ({pct(r.get('vs_nifty_pct'), 1)} vs NIFTY"
            + (f", typical ±{r['typical_move_pct']:.1f}%" if r.get("typical_move_pct") else "") + ")"
            + (" · ⚠ bad-results drift flag" if r.get("avoid") else "") for r in reacted[:10]])
    announced = [r for r in results.get("rows") or [] if str(r.get("released_at", "")).startswith(iso)]
    after = [r for r in announced if r.get("timing") == "after close"]
    if after:
        after.sort(key=lambda r: -(r.get("turnover_cr") or 0))
        fin = (api.get("/api/market/financials-latest", symbols=",".join(r["symbol"] for r in after[:15])) or {}).get("latest") or {}
        L += section("Results announced after the close (they react next session)", [
            "- " + " · ".join(f"{r['symbol']} ({str(r.get('released_at', ''))[11:16]}" + numbers_note(fin.get(r["symbol"]), iso)
                             + (f", typically ±{r['typical_move_pct']:.1f}%" if r.get("typical_move_pct") else "") + ")"
                             for r in after[:15])
            + (f" · and {len(after) - 15} more" if len(after) > 15 else "")])

    # ── your stocks: holdings, Desk positions, watchlist, alerted symbols (live quotes: today only) ──
    mine: dict[str, list[str]] = {}
    held = (api.get("/api/positions/open-positions") or {}) if today else {}
    if today:
        watched = api.get("/api/monitor/list") or {}
        price_alerts = api.get("/api/alerts") or {}
        for p in held.get("positions") or ((held.get("last_known") or {}).get("positions")) or []:
            mine.setdefault(str(p.get("symbol", "")).upper(), []).append("held")
        for p in desk.get("positions") or []:
            mine.setdefault(str(p.get("symbol", "")).upper(), []).append("Desk")
        for sym in watched.get("symbols") or []:
            mine.setdefault(str(sym).upper().replace(".NS", ""), []).append("watch")
        for sym in (price_alerts.get("alerts") or {}):
            mine.setdefault(sym.upper(), []).append("alert")
        mine.pop("", None)
    if mine:
        q = (api.get("/api/news-scanner/quotes", symbols=",".join(f"{m}.NS" for m in list(mine)[:60])) or {}).get("quotes") or {}
        soon: dict[str, str] = {}
        for e in events.get("rows") or []:
            if e.get("symbol") in mine and iso < e.get("event_date", "") <= (day + timedelta(days=7)).isoformat():
                label = "board meeting" if e["kind"] == "OTHER" else e["kind"].lower().replace("_", " ")   # as the UI's EventBadge
                soon.setdefault(e["symbol"], f"{label} {date.fromisoformat(e['event_date']):%a %d %b}")
        risk = (api.get("/api/market/surveillance", symbols=",".join(list(mine)[:200])) or {}).get("flags") or {}
        y: list[str] = []
        for sym, tags in sorted(mine.items(), key=lambda kv: -abs((q.get(f"{kv[0]}.NS") or {}).get("change_pct") or 0)):
            qq = q.get(f"{sym}.NS") or {}
            notes = []
            chips = [c["code"] for c in (risk.get(sym) or {}).get("chips") or []]
            if chips:
                notes.append("NSE surveillance: " + ", ".join(chips))
            if sym in soon:
                notes.append(f"next: {soon[sym]}")
            notes += [f"{r['direction']} deal {crore(r['value'] / 1e7).lstrip('+')} ({(r.get('client_name') or '')[:28]})" for r in day_deals if r["symbol"] == sym][:2]
            notes += [f"insider buy {crore(r['total_value'] / 1e7).lstrip('+')}" for r in fresh if r["symbol"] == sym]
            notes += [f"results reaction {pct(r['move_pct'], 1)}" for r in reacted if r["symbol"] == sym]
            notes += [f"alert {h['side']} {h['level']:,.0f} fired" for h in price_alerts.get("history") or []
                      if h.get("sym") == sym and str(h.get("at", "")).startswith(iso)]
            if len(mine) <= 15:                       # one headline of the day per stock (Google News, filtered)
                hl = (api.get(f"/api/market/stock-news/{sym}", days=1) or {}).get("headlines") or []
                if hl:
                    notes.append(f"news: \"{hl[0]['title'][:110]}\" ({hl[0]['publisher']})")
            move = pct(qq.get("change_pct"), 1) if qq.get("available") else "—"
            y.append(f"- **{sym}** ({', '.join(tags)}) {move}" + (f" · {' · '.join(notes)}" if notes else ""))
        book_line = concentration_line(held.get("positions") or ((held.get("last_known") or {}).get("positions")) or [], q)
        L += section("Your stocks", ([book_line] if book_line else []) + y)

    # ── the next session ──
    nxt = next_session(day, holidays)
    t: list[str] = []
    ev = [e for e in events.get("rows") or [] if e.get("event_date") == nxt.isoformat()
          and (today or not e.get("first_seen") or str(e["first_seen"])[:10] <= iso)]     # a backfill shows what was known
    if ev:
        ev.sort(key=lambda e: -(e.get("turnover_cr") or 0))
        kinds: dict[str, int] = {}
        for e in ev:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        lab = lambda k: "board meeting" if k == "OTHER" else k.lower().replace("_", " ")  # noqa: E731
        t.append(f"- {len(ev)} corporate events on {nxt:%a %d %b} (" + ", ".join(f"{n} {lab(k)}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])) + ")")
        t.append("- Largest names: " + " · ".join(f"{e['symbol']} ({lab(e['kind'])})" for e in ev[:8]))
    eco = [e for e in eco_all if iso < e.get("date", "") <= nxt.isoformat() and e.get("kind") != "HOLIDAY"]
    if eco:                                           # data releases, RBI / Fed decisions, expiries, special sessions (ECO)
        t.append("- Calendar before the next session: " + " · ".join(
            f"{e['what']}" + (f" ({e['country']})" if e.get("country") and e["country"] != "IN" else "")
            + (f" {date.fromisoformat(e['date']):%a} {e['time']} IST" if e.get("time") else f" {date.fromisoformat(e['date']):%a}")
            for e in eco[:8]))
    if today:
        gift = api.get("/api/market/gift-nifty") or {}
        if gift.get("implied_gap_pct") is not None:
            t.append(f"- GIFT NIFTY {num(gift.get('last'), 1)} at {str(gift.get('time', ''))[12:]} implies {pct(gift['implied_gap_pct'])} "
                     "vs today's NIFTY close (it trades until 02:45 IST, so this moves overnight)")
    opt = api.get("/api/market/option-chain/NIFTY") or {}
    if opt.get("date") == iso or (today and not opt.get("date")):
        nxt_exp = next_expiry(opt, iso)
        if nxt_exp:                                   # expiry day: today's contracts are settled, read the next series
            opt = api.get("/api/market/option-chain/NIFTY", expiry=nxt_exp) or opt
        if opt.get("found"):
            t.append(f"- NIFTY options ({opt.get('expiry')} expiry): ±{opt.get('expected_move_pct')}% priced in, PCR {opt.get('pcr_oi')}, "
                     f"max pain {num(opt.get('max_pain'))}, call wall {num((opt.get('resistance') or [None])[0])}, put wall {num((opt.get('support') or [None])[0])}")
    else:
        oh = next((r for r in (api.get("/api/market/option-history/NIFTY", days=max(20, back + 5)) or {}).get("rows") or []
                   if str(r.get("date")) == iso), None)
        if oh:
            t.append(f"- NIFTY options ({oh.get('expiry')} expiry, that day's stored summary): ATM IV {oh.get('atm_iv')}%, "
                     f"PCR {oh.get('pcr')}, max pain {num(oh.get('max_pain'))} (strike walls are not stored per day)")
        else:
            t.append(not_stored(day, "NIFTY option chain", opt.get("date")))
    L += section(f"Next session ({nxt:%a %d %b})", t)

    # ── the book ──
    nav = next((r for r in desk.get("nav") or [] if str(r.get("date")) == iso), None)
    lat = nav or ((desk.get("latest") or {}) if str((desk.get("latest") or {}).get("date")) == iso else {})
    meta = desk.get("meta") or {}
    if lat:
        start = meta.get("start_capital") or 0
        ret = (lat["nav"] / start - 1) * 100 if start else None
        L += section("Decision Desk (paper)", [
            f"- NAV {inr(lat['nav'])} ({pct(ret)} since start) · {lat.get('positions', 0)} positions · drawdown {pct((lat.get('drawdown') or 0) * 100)}"])
        st["desk"] = "ok"
    else:
        L += section("Decision Desk (paper)", [not_stored(day, "Desk mark", (desk.get("latest") or {}).get("date"))])
        st["desk"] = NOT_STORED
    # ── paper F&O book (E-JRNL): one line when paper closes happened that day; the debrief holds the split ──
    fo_day = api.get("/api/options/book/day", date=iso) or {}
    if fo_day.get("closes"):
        L += section("Paper F&O book", [
            f"- {fo_day['closes']} paper close(s) journalled, realised {inr(fo_day.get('realised_inr') or 0)} net of the "
            "recorded costs (PAPER only) · the Θ/Δ/ν split and the week's facts: OSTR › Paper F&O book › DEBRIEF"])


    gaps = [k for k in REQUIRED if st.get(k) == NOT_STORED]
    if gaps:
        L[gap_note_at:gap_note_at] = [f"> ⚠ Data for {day:%d %b} not stored for: {', '.join(g.replace('_', ' ') for g in gaps)}. "
                                      "Those sections say so; nothing from another day is shown.", ""]
    if api.missing:
        L += ["---", "", "Sources that did not answer: " + "; ".join(api.missing), ""]
    L += [sections_marker({k: st.get(k, NOT_STORED) for k in REQUIRED})]

    n_line = session_change(n50, iso)
    b_ok = st.get("breadth") == "ok" and b
    lat_cash = {r["category"]: r.get("net_cr") for r in crow}
    summary = " · ".join(filter(None, [
        f"NIFTY {pct(n_line[1])}" if n_line else None,
        f"breadth {num(b.get('adv'))}/{num(b.get('dec'))} (liquid NSE universe)" if b_ok else None,
        f"FII {crore(lat_cash.get('FII'))}" if lat_cash else None,
        f"regime {reg.get('score')}/4" if reg else None,
        f"incomplete: {', '.join(gaps)}" if gaps else None]))
    return "\n".join(L), summary, st


def is_session(api: Api, day: date) -> bool:
    """A stored NIFTY 50 close (past days), or a weekday that is not an NSE holiday (today, before the EOD file)."""
    n50 = closes_by_date(api.get("/api/market/index-daily", symbol="NIFTY50", days=max(30, (date.today() - day).days + 10)))
    if day.isoformat() in n50:
        return True
    if day != date.today() or day.weekday() >= 5:
        return False
    eco = (api.get("/api/market/eco-calendar", back=0, ahead=1) or {}).get("events") or []
    return not any(e.get("kind") == "HOLIDAY" and e.get("date") == day.isoformat() for e in eco)


def backfill(api: Api, out: Path, since: date, until: date, *, allow_partial: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Write the missing wraps (and rebuild stale or incomplete ones) for stored NSE sessions in [since, until] from
    stored data. A wrap is written only when every REQUIRED section's data exists for that day, unless
    `allow_partial` (then the missing sections say 'not stored'). Never touches a complete wrap."""
    n50 = closes_by_date(api.get("/api/market/index-daily", symbol="NIFTY50", days=max(30, (date.today() - since).days + 10)))
    report: dict[str, Any] = {"written": [], "skipped": {}, "complete_already": 0, "dry_run": dry_run}
    for iso in sorted(d for d in n50 if since.isoformat() <= d <= until.isoformat()):
        path = out / f"{iso}.md"
        reason: Optional[str] = "missing"
        if path.exists():
            reason = wrap_needs_rebuild(path.read_text(encoding="utf-8", errors="replace"), iso)
            if reason is None:
                report["complete_already"] += 1
                continue
        api.missing = []
        md, _, st = build_report(api, date.fromisoformat(iso), refresh=False)
        gaps = [k for k in REQUIRED if st.get(k) == NOT_STORED]
        if gaps and not allow_partial:
            report["skipped"][iso] = f"{reason}; not stored: {', '.join(gaps)}"
            continue
        if not dry_run:
            out.mkdir(parents=True, exist_ok=True)
            path.write_text(md + "\n", encoding="utf-8")
        report["written"].append({"date": iso, "was": reason, "not_stored": gaps})
    return report


def refuse_under_pytest(out: Path) -> Optional[str]:
    """A wrap run spawned from inside a pytest test (the controller's nse_evening_pass / catch-up tests inherit
    PYTEST_CURRENT_TEST) must neither GET the live ui-api nor write the repository's archive: refused unless the test
    passes its own --out. Checker 6 Nov (p03)."""
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if out.resolve() != (ROOT / "reports" / "daily_wrap").resolve():
        return None
    return "refused: running under pytest with the repository's reports/daily_wrap (pass --out <tmp>)"


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out", default="reports/daily_wrap")
    ap.add_argument("--base", default=os.getenv("UI_API_URL", "http://localhost:8010"))
    ap.add_argument("--backfill-missing", action="store_true", help="write missing / stale / incomplete wraps from stored data")
    ap.add_argument("--since", default=None, help="first session for --backfill-missing (default: 30 days back)")
    ap.add_argument("--until", default=None, help="last session for --backfill-missing (default: yesterday)")
    ap.add_argument("--allow-partial", action="store_true", help="with --backfill-missing: also write wraps with 'not stored' sections")
    ap.add_argument("--dry-run", action="store_true", help="with --backfill-missing: report, write nothing")
    args = ap.parse_args(argv)
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    refused = refuse_under_pytest(out)
    if refused:                                  # before any GET: the live stack is never read from a test
        print("RESULT " + json.dumps({"written": [], "skipped": {}, "refused": refused}))
        return
    api = Api(args.base)
    if args.backfill_missing:
        since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=30)
        until = date.fromisoformat(args.until) if args.until else date.today() - timedelta(days=1)
        rep = backfill(api, out, since, until, allow_partial=args.allow_partial, dry_run=args.dry_run)
        print("RESULT " + json.dumps(rep))
        return
    day = date.fromisoformat(args.date)
    if not is_session(api, day):
        print("RESULT " + json.dumps({"date": day.isoformat(), "path": None, "summary": f"no NSE session on {day:%a %d %b}: no wrap"}))
        return
    md, summary, st = build_report(api, day)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{day.isoformat()}.md"
    path.write_text(md + "\n", encoding="utf-8")
    print(md)
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    print("RESULT " + json.dumps({"date": day.isoformat(), "path": rel, "summary": summary,
                                  "not_stored": [k for k in REQUIRED if st.get(k) == NOT_STORED]}))


if __name__ == "__main__":
    main()
