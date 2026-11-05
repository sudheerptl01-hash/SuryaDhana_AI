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


def build(api: Api, day: date) -> tuple[str, str]:
    """Return (markdown, one-line summary)."""
    if day == date.today():                   # NSE posts FII/DII in the evening: fetch it now rather than rely on 20:30
        try:
            api.client.post("/api/market/fii-dii-cash/refresh")
        except Exception:  # noqa: BLE001 — the figure is optional
            pass
    mon = api.get("/api/market/monitor") or {}
    today = day == date.today()
    live = (api.get("/api/market/live-movers", universe="FOSec") or {}) if today else {}   # live = today's session only
    crash = api.get("/api/market/crash-filter") or {}
    cash = api.get("/api/market/fii-dii-cash", days=30) or {}
    parts = api.get("/api/market/participants", days=20) or {}
    deals = api.get("/api/market/deals", days=max(1, (date.today() - day).days + 1), min_value=1e7) or {}
    insiders = api.get("/api/market/insider-buys", days=7, min_value=1e6) or {}
    results = api.get("/api/market/results-recent", days=3) or {}
    events = api.get("/api/market/events") or {}
    opt = api.get("/api/market/option-chain/NIFTY") or {}
    desk = api.get("/api/desk/status") or {}
    held = api.get("/api/positions/open-positions") or {}
    watched = api.get("/api/monitor/list") or {}
    price_alerts = api.get("/api/alerts") or {}
    internals = api.get("/api/market/internals", day=day.isoformat()) or {}

    iso = day.isoformat()
    L: list[str] = [f"# Market wrap · {day:%a %d %b %Y}", "",
                    f"Written {datetime.now():%H:%M} IST from the terminal's data (NSE end of day {mon.get('as_of', '—')}). "
                    "Facts only: nothing here is a trade signal.", ""]
    stale = mon.get("as_of") and mon["as_of"] != iso
    if stale:
        L += [f"> ⚠ End-of-day breadth is from {mon['as_of']}: today's NSE files had not been processed when this was written.", ""]

    # ── the session ──
    idx = {i["index"]: i for i in live.get("indices") or []}
    s: list[str] = []
    row = [f"{name} {num(i.get('last'), 2)} ({pct(i.get('change_pct'))})" for name in
           ("NIFTY 50", "NIFTY BANK", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100") if (i := idx.get(name))]
    if row:
        s.append("- " + " · ".join(row))
    elif crash.get("date") == iso:
        s.append(f"- NIFTY 50 {num(crash.get('nifty'), 2)}")
    b = mon.get("breadth") or {}
    if b:
        s.append(f"- Breadth ({mon.get('index_name', 'Nifty 500')}): {num(b.get('adv'))} up / {num(b.get('dec'))} down · "
                 f"{num(b.get('pct_above50'), 0)}% above the 50-day, {num(b.get('pct_above200'), 0)}% above the 200-day · "
                 f"new highs / lows {num(b.get('new_highs'))} / {num(b.get('new_lows'))} · India VIX {num(b.get('vix'), 2)}")
    s += internals_lines(internals.get("summary") or {})
    if today:
        line = movers_line((api.get("/api/market/index-contribution", index="NIFTY 50") or {}))
        if line:
            s.append(line)
        iv = api.get("/api/market/index-valuation") or {}
        line = valuation_line(iv.get("indices") or {}, iv.get("vs_history"), iv.get("rel_history"))
        if line:
            s.append(line)
    reg = mon.get("regime") or {}
    if reg:
        sc = int(reg.get("score", 0))
        s.append(f"- Regime **{sc}/4 {SCORE_WORD[max(0, min(sc, 4))]}** (exposure guide {reg.get('exposure', '—')}, "
                 f"{reg.get('days_at_score', '—')} sessions at this score)")
    if crash:
        s.append(f"- Desk crash filter: NIFTY {num(crash.get('nifty'), 0)} vs 200-day {num(crash.get('sma200'), 0)} → "
                 + ("**risk-on**" if crash.get("risk_on") else f"**in the liquid fund**, needs {pct(crash.get('move_needed_pct'), 1)}")
                 + f" · next signal {crash.get('next_signal_date', '—')}")
    L += section("The session", s)

    # ── sectors ──
    secs = sorted((x for x in mon.get("sectors") or [] if x.get("ret_1d_pct") is not None), key=lambda x: -x["ret_1d_pct"])
    if secs:
        fmt: Callable[[dict], str] = lambda x: f"{x['industry']} {pct(x['ret_1d_pct'], 1)}"  # noqa: E731
        L += section("Sectors (NSE industries, equal-weighted, 1 day)" + (f" · as of {mon['as_of']}" if stale else ""),
                     [f"- Best: {' · '.join(fmt(x) for x in secs[:3])}", f"- Worst: {' · '.join(fmt(x) for x in secs[-3:][::-1])}"])

    # ── money flows ──
    f: list[str] = []
    cs = cash.get("summary") or {}
    if cs.get("latest_date"):
        lat = cs.get("latest") or {}
        when = "today" if cs["latest_date"] == iso else cs["latest_date"]
        f.append(f"- Cash market ({when}, provisional): FII {crore(lat.get('FII'))} · DII {crore(lat.get('DII'))}"
                 + (f" · month to date FII {crore((cs.get('mtd') or {}).get('FII'))}, DII {crore((cs.get('mtd') or {}).get('DII'))}"
                    if (cs.get("sessions_mtd") or 0) > 1 else ""))
    fii = next((r for r in parts.get("snapshot") or [] if r.get("client_type") == "FII"), None)
    if fii:
        f.append(f"- FII index futures: {fii.get('fut_long_pct')}% long, net change {num(fii.get('fut_net_chg_1d'))} contracts on the day "
                 f"(positioning does not predict NIFTY: RSCH)")
    day_deals = [r for r in deals.get("rows") or [] if r.get("date") == iso]
    net: dict[str, float] = {}
    for r in day_deals:
        net[r["symbol"]] = net.get(r["symbol"], 0.0) + (r["value"] if r["direction"] == "buy" else -r["value"])
    top = sorted((kv for kv in net.items() if abs(kv[1]) >= 1e7), key=lambda kv: -abs(kv[1]))
    if top:
        f.append("- Biggest net block / bulk deal flows: " + " · ".join(f"{sym} {crore(v / 1e7)}" for sym, v in top[:6]))
    inst = [r for r in day_deals if r.get("institution")]
    if inst:
        f.append("- Mutual fund / insurer deals: " + " · ".join(
            f"{r['symbol']} {r['direction']} {crore(r['value'] / 1e7).lstrip('+')}" for r in sorted(inst, key=lambda r: -r["value"])[:5]))
    fresh = [r for r in insiders.get("rows") or [] if r.get("last_date") == iso]
    if fresh:
        f.append("- Insider buying disclosed today (promoters / directors, market purchases): " + " · ".join(
            f"{r['symbol']} {crore(r['total_value'] / 1e7).lstrip('+')}" for r in fresh[:6]))
    shorts = short_line((api.get("/api/market/short-selling", days=5) or {}).get("rows") or [])
    if shorts:
        f.append(shorts)
    L += section("Money flows", f)

    # ── movers ──
    mv = mon.get("movers") or {}
    m: list[str] = []
    for key, label in (("gainers", "Gainers"), ("losers", "Losers"), ("volume_shockers", "Volume shockers")):
        rows = mv.get(key) or []
        if rows:
            extra = (lambda r: f" ({r['vol_x']:.0f}× vol)") if key == "volume_shockers" else (lambda r: "")
            m.append(f"- {label}: " + " · ".join(f"{r['symbol']} {pct(r.get('chg_pct'), 1)}{extra(r)}" for r in rows[:5]))
    L += section("Movers (liquid NSE stocks)" + (f" · as of {mon['as_of']}" if stale else ""), m)

    # ── results ──
    reacted = [r for r in results.get("rows") or [] if r.get("reaction_date") == iso and r.get("move_pct") is not None]
    if reacted:
        reacted.sort(key=lambda r: -abs(r.get("vs_nifty_pct") or 0))
        L += section("Results reactions today", [
            f"- {r['symbol']} {pct(r['move_pct'], 1)} ({pct(r.get('vs_nifty_pct'), 1)} vs NIFTY"
            + (f", typical ±{r['typical_move_pct']:.1f}%" if r.get("typical_move_pct") else "") + ")"
            + (" · ⚠ bad-results drift flag" if r.get("avoid") else "") for r in reacted[:10]])

    # ── results announced today (react tomorrow) ──
    announced = [r for r in results.get("rows") or [] if str(r.get("released_at", "")).startswith(iso)]
    if announced:
        announced.sort(key=lambda r: -(r.get("turnover_cr") or 0))
        fin = (api.get("/api/market/financials-latest", symbols=",".join(r["symbol"] for r in announced[:15])) or {}).get("latest") or {}
        L += section("Results announced today (they react next session)", [
            "- " + " · ".join(f"{r['symbol']} ({r.get('timing', '')}" + numbers_note(fin.get(r["symbol"]), iso)
                             + (f", typically ±{r['typical_move_pct']:.1f}%" if r.get("typical_move_pct") else "") + ")"
                             for r in announced[:15])
            + (f" · and {len(announced) - 15} more" if len(announced) > 15 else "")])

    # ── your stocks: holdings, Desk positions, watchlist, alerted symbols ──
    mine: dict[str, list[str]] = {}
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
        # NSE surveillance flags (ASM / GSM / ESM / bands / F&O ban) for these stocks
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
            move = pct(qq.get("change_pct"), 1) if qq.get("available") and today else "—"
            y.append(f"- **{sym}** ({', '.join(tags)}) {move}" + (f" · {' · '.join(notes)}" if notes else ""))
        book_line = concentration_line(held.get("positions") or ((held.get("last_known") or {}).get("positions")) or [], q)
        L += section("Your stocks", ([book_line] if book_line else []) + y)

    # ── tomorrow ──
    nxt = next_weekday(day)
    t: list[str] = []
    ev = [e for e in events.get("rows") or [] if e.get("event_date") == nxt.isoformat()]
    if ev:
        ev.sort(key=lambda e: -(e.get("turnover_cr") or 0))
        kinds: dict[str, int] = {}
        for e in ev:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        lab = lambda k: "board meeting" if k == "OTHER" else k.lower().replace("_", " ")  # noqa: E731
        t.append(f"- {len(ev)} corporate events on {nxt:%a %d %b} (" + ", ".join(f"{n} {lab(k)}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])) + ")")
        t.append("- Largest names: " + " · ".join(f"{e['symbol']} ({lab(e['kind'])})" for e in ev[:8]))
    eco = [e for e in (api.get("/api/market/eco-calendar", back=0, ahead=7) or {}).get("events") or [] if e.get("date") == nxt.isoformat()]
    if eco:                                           # CPI / WPI / IIP / GDP releases, RBI and Fed decisions (ECO)
        t.append("- Economic data: " + " · ".join(f"{e['what']} at {e.get('time') or '?'} IST" for e in eco))
    gift = api.get("/api/market/gift-nifty") or {}
    if today and gift.get("implied_gap_pct") is not None:
        t.append(f"- GIFT NIFTY {num(gift.get('last'), 1)} at {str(gift.get('time', ''))[12:]} implies {pct(gift['implied_gap_pct'])} "
                 "vs today's NIFTY close (it trades until 02:45 IST, so this moves overnight)")
    nxt_exp = next_expiry(opt, iso)
    if nxt_exp:                                       # expiry day: today's contracts are settled, read the next series
        opt = api.get("/api/market/option-chain/NIFTY", expiry=nxt_exp) or opt
    if opt.get("found"):
        t.append(f"- NIFTY options ({opt.get('expiry')} expiry): ±{opt.get('expected_move_pct')}% priced in, PCR {opt.get('pcr_oi')}, "
                 f"max pain {num(opt.get('max_pain'))}, call wall {num((opt.get('resistance') or [None])[0])}, put wall {num((opt.get('support') or [None])[0])}")
    L += section("Tomorrow", t)

    # ── the book ──
    lat = desk.get("latest") or {}
    meta = desk.get("meta") or {}
    if lat:
        start = meta.get("start_capital") or 0
        ret = (lat["nav"] / start - 1) * 100 if start else None
        L += section("Decision Desk (paper)", [
            f"- NAV {inr(lat['nav'])} ({pct(ret)} since start) · {lat.get('positions', 0)} positions · drawdown {pct((lat.get('drawdown') or 0) * 100)}"])

    if api.missing:
        L += ["---", "", "Sources that did not answer: " + "; ".join(api.missing), ""]

    n50 = idx.get("NIFTY 50") or {}
    lat_cash = (cs.get("latest") or {}) if cs.get("latest_date") == iso else {}
    summary = " · ".join(filter(None, [
        f"NIFTY {pct(n50.get('change_pct'))}" if n50 else None,
        f"breadth {num(b.get('adv'))}/{num(b.get('dec'))}" if b and not stale else None,
        f"FII {crore(lat_cash.get('FII'))}" if lat_cash else None,
        f"regime {reg.get('score')}/4" if reg else None]))
    return "\n".join(L), summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--out", default="reports/daily_wrap")
    ap.add_argument("--base", default=os.getenv("UI_API_URL", "http://localhost:8010"))
    args = ap.parse_args()
    day = date.fromisoformat(args.date)
    md, summary = build(Api(args.base), day)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{day.isoformat()}.md"
    path.write_text(md + "\n", encoding="utf-8")
    print(md)
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    print("RESULT " + json.dumps({"date": day.isoformat(), "path": rel, "summary": summary}))


if __name__ == "__main__":
    main()
