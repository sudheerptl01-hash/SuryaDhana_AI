"""
SuryaDhana Telegram bot: commands from your phone, formatted answers, triggers, and the ICICI OTP hand-off.

Runs inside the master controller (long-polls Telegram's getUpdates). It answers **only** TELEGRAM_CHAT_ID:
anything from another chat is ignored. Messages are HTML with every value escaped (Telegram's Markdown rejects a
stray "_" or "*").

ICICI login with an SMS OTP:
  1. /login (or the 08:00 job) starts scripts/daily_session_refresh.py, which drives ICICI's login page.
  2. When ICICI shows the SMS-OTP panel, that script writes data/icici_otp_request.json and messages you.
  3. You reply with the 6 digits (or "/otp 123456"); this bot writes data/icici_otp.json.
  4. The login script reads it, submits the code, and the session token is applied. The files are deleted.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
OTP_REQUEST = ROOT / "data" / "icici_otp_request.json"
OTP_REPLY = ROOT / "data" / "icici_otp.json"
OTP_WINDOW_S = 360                      # an OTP reply counts only while a login is waiting (5 min + slack)

Get = Callable[..., Awaitable[Any]]

# command → (args, what it does). Order = the order in /help and Telegram's "/" menu.
COMMANDS: list[tuple[str, str, str]] = [
    ("help", "", "this list"),
    ("brief", "", "market, your book and today's events, right now"),
    ("market", "", "NIFTY / BANK / VIX, breadth, regime, valuation"),
    ("book", "", "your holdings: price, today, P&L, surveillance flags, risk"),
    ("quote", "TCS", "one stock: price, day move, P/E, flags, next event"),
    ("movers", "", "top gainers and losers (F&O stocks, live in market hours)"),
    ("results", "", "results filed since the last close and how they reacted"),
    ("events", "", "this week: your stocks' events, big results, data releases, holidays"),
    ("flags", "", "NSE surveillance flags (ASM / GSM / bands / F&O ban) on your holdings"),
    ("valuation", "", "index P/E against its own history and vs NIFTY"),
    ("desk", "", "Decision Desk: NAV, positions, crash filter, next signal"),
    ("wrap", "", "the latest end-of-day market wrap"),
    ("alerts", "", "your price / move alerts · /alerts list: every alert rule (typed engine)"),
    ("alert", "TCS above 2400", "set an alert: above / below a price, or move 3 (± % today) · "
                                "/alert add iv_pctile:NIFTY above 80 repeat: a typed rule"),
    ("unalert", "TCS", "remove a stock's alerts"),
    ("status", "", "system health: services, ICICI session, data dates"),
("shadow", "", "S1 paper-shadow NAV and book (alpha_lab forward test)"),
    ("login", "", "log in to ICICI now (asks you for the SMS OTP)"),
    ("otp", "123456", "the ICICI OTP (or just reply with the 6 digits)"),
    ("userid", "AB123456", "update the ICICI user ID (your message is deleted)"),
    ("password", "…", "update the ICICI password (your message is deleted at once)"),
]


def esc(v: Any) -> str:
    return html.escape(str(v), quote=False)


def pct(v: Optional[float], d: int = 2) -> str:
    return "—" if v is None else f"{'+' if v > 0 else ''}{v:.{d}f}%"


def num(v: Optional[float], d: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{d}f}"
    return ("−" if v < 0 else "") + s


def inr(v: Optional[float]) -> str:
    return "—" if v is None else f"{'−' if v < 0 else ''}₹{abs(v):,.0f}"


def ordinal(n: Any) -> str:
    """12 → "12th", 1 → "1st", 22 → "22nd"."""
    n = int(round(float(n)))
    suffix = "th" if 11 <= abs(n) % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(abs(n) % 10, "th")
    return f"{n}{suffix}"


def arrow(v: Optional[float]) -> str:
    return "▲" if (v or 0) > 0 else "▼" if (v or 0) < 0 else "·"


def help_text() -> str:
    lines = ["<b>SuryaDhana · commands</b>", ""]
    for cmd, args, what in COMMANDS:
        lines.append(f"/{cmd}{(' ' + esc(args)) if args else ''} — {esc(what)}")
    lines += ["", "Automatic messages: 08:50 pre-market note · price / move / filing / results alerts · 15:40 closing "
              "note · 21:00 wrap · job failures. ICICI OTP: when asked, reply with the 6 digits."]
    return "\n".join(lines)


def chunks(text: str, limit: int = 3900) -> list[str]:
    """Telegram caps a message at 4,096 characters: split on line breaks."""
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out


# ── formatters (pure: tested) ──────────────────────────────────────────────────────

def fmt_market(idx: dict, mon: dict, val: dict) -> str:
    q = idx.get("indices") or {}
    lines = [f"<b>Market</b> · {esc(idx.get('timestamp') or '')}"]
    for name in ("NIFTY 50", "NIFTY BANK", "INDIA VIX"):
        r = q.get(name) or {}
        if r.get("last") is not None:
            lines.append(f"{arrow(r.get('change_pct'))} {esc(name)} <b>{num(r['last'])}</b> ({pct(r.get('change_pct'))})")
    b, rg = mon.get("breadth") or {}, mon.get("regime") or {}
    if b:
        lines.append(f"Nifty 500 {num(b.get('index'), 0)} ({pct(b.get('index_chg_pct'))}) · breadth {num(b.get('adv'), 0)} up / "
                     f"{num(b.get('dec'), 0)} down · {num(b.get('pct_above50'), 0)}% above the 50-day")
    if rg:
        lines.append(f"Regime <b>{rg.get('score')}/4</b> · exposure guide {esc(rg.get('exposure'))}")
    n = (val.get("indices") or {}).get("NIFTY 50") or {}
    h = (val.get("vs_history") or {}).get("NIFTY 50") or {}
    if n.get("pe"):
        lines.append(f"NIFTY P/E {n['pe']:.1f}×" + (f" ({ordinal(h['pctl'])} percentile since 2021)" if h.get("pctl") is not None else "")
                     + f" · P/B {n.get('pb')} · yield {n.get('dy')}%")
    return "\n".join(lines)


def fmt_book(pos: dict, quotes: dict, flags: dict) -> str:
    rows = pos.get("positions") or []
    source = "ICICI (live)"
    if not rows:
        lk = pos.get("last_known") or {}
        rows, source = lk.get("positions") or [], f"last known book ({esc(str(lk.get('as_of', ''))[:16])})"
    if not rows:
        if pos.get("connected"):
            return "<b>Your book</b> · ICICI (live)\nICICI reports no holdings and no open positions on this account."
        return "<b>Your book</b>\nNo holdings known (ICICI not connected and nothing saved)."
    lines, tot_v, tot_c, tot_d = [f"<b>Your book</b> · {source}"], 0.0, 0.0, 0.0
    for r in rows:
        sym, qty, buy = r.get("symbol"), float(r.get("quantity") or 0), float(r.get("buy_price") or 0)
        qq = quotes.get(f"{sym}.NS") or {}
        px, ch = qq.get("price"), qq.get("change_pct")
        chips = [c["code"] for c in ((flags.get(sym) or {}).get("chips") or [])]
        if px is None:
            lines.append(f"• <b>{esc(sym)}</b> {qty:g} — no quote")
            continue
        value, cost = px * qty, buy * qty
        day = value - value / (1 + (ch or 0) / 100)
        tot_v, tot_c, tot_d = tot_v + value, tot_c + cost, tot_d + day
        lines.append(f"• <b>{esc(sym)}</b> {num(px)} {arrow(ch)} {pct(ch)} · P&amp;L {pct((px / buy - 1) * 100 if buy else None, 1)}"
                     + (f" · ⚑ {esc(', '.join(chips))}" if chips else ""))
    if tot_v:
        lines.append(f"\nValue {inr(tot_v)} · today {inr(tot_d)} · P&amp;L {inr(tot_v - tot_c)} ({pct((tot_v / tot_c - 1) * 100 if tot_c else None, 1)})")
    return "\n".join(lines)


def fmt_quote(sym: str, q: dict, fin: dict, flags: dict, events: list[dict]) -> str:
    if not q.get("available"):
        return f"No quote for {esc(sym)}."
    lines = [f"<b>{esc(sym)}</b> {esc(q.get('name') or '')}",
             f"{num(q.get('price'))} {arrow(q.get('change_pct'))} {pct(q.get('change_pct'))} "
             f"(prev {num(q.get('prev_close'))})"]
    if q.get("day_low") is not None:
        lines.append(f"Day {num(q.get('day_low'))} – {num(q.get('day_high'))} · 52w {num(q.get('low_52w'))} – {num(q.get('high_52w'))}")
    if fin:
        bits = []
        if fin.get("pe") is not None:
            bits.append(f"P/E {fin['pe']:.1f}×")
        if fin.get("pat_yoy") is not None:
            bits.append(f"profit {pct(fin['pat_yoy'], 0)} y/y")
        if fin.get("mcap"):
            bits.append(f"mcap ₹{fin['mcap'] / 1e7:,.0f} cr")
        if bits:
            lines.append(" · ".join(bits))
    chips = [c["code"] for c in (flags.get("chips") or [])]
    if chips:
        lines.append(f"⚑ NSE surveillance: {esc(', '.join(chips))}")
    ev = [e for e in events if e.get("symbol") == sym][:2]
    for e in ev:
        kind = "board meeting" if e.get("kind") == "OTHER" else str(e.get("kind", "")).lower()
        lines.append(f"Next: {esc(kind)} {esc(e.get('event_date'))}")
    return "\n".join(lines)


def fmt_movers(m: dict) -> str:
    lines = [f"<b>Movers</b> · {esc(m.get('timestamp') or '')}{'' if m.get('market_open') else ' (market closed)'}"]
    for key, title in (("gainers", "Gainers"), ("losers", "Losers")):
        rows = (m.get(key) or [])[:6]
        if rows:
            lines.append(f"<b>{title}</b>: " + " · ".join(f"{esc(r['symbol'])} {pct(r.get('change_pct'), 1)}" for r in rows))
    return "\n".join(lines)


def fmt_results(r: dict) -> str:
    rows = r.get("rows") or []
    if not rows:
        return f"<b>Results</b> since {esc(r.get('since') or 'the last close')}: none filed."
    lines = [f"<b>Results</b> since {esc(r.get('since'))} · {len(rows)} filed"]
    for x in rows[:15]:
        move = (f"{arrow(x['change_pct'])} {pct(x['change_pct'], 1)}" if x.get("change_pct") is not None
                else "reacts at the open")
        if x.get("vs_typical") is not None:
            move += f" ({x['vs_typical']:.1f}× its usual)"
        parts = [f"filed {esc(str(x.get('filed_at') or '')[11:16])}"] if x.get("filed_at") else []
        if x.get("revenue_yoy") is not None:
            parts.append(f"revenue {pct(x['revenue_yoy'], 0)} y/y")
        if x.get("pat_turn"):
            turn = {"to profit": "turned to a profit", "to loss": "swung to a loss", "loss both": "loss, as a year ago"}
            parts.append(esc(turn.get(x["pat_turn"], f"profit {x['pat_turn']}")))
        elif x.get("pat_yoy") is not None:
            parts.append(f"profit {pct(x['pat_yoy'], 0)} y/y")
        elif x.get("numbers") not in (None, "ok"):
            parts.append(esc(x["numbers"]))                 # e.g. "pending": NSE hasn't parsed the filing yet
        if x.get("typical_move_pct") is not None and x.get("change_pct") is None:
            parts.append(f"usually moves ±{x['typical_move_pct']:.1f}%")
        lines.append(f"• <b>{esc(x['symbol'])}</b> {move}" + (" · " + " · ".join(parts) if parts else ""))
    if len(rows) > 15:
        lines.append(f"… and {len(rows) - 15} more (RSLT tab)")
    return "\n".join(lines)


def fmt_events(eco: dict, events: list[dict], mine: set[str], today: str) -> str:
    lines = ["<b>This week</b>"]
    my = [e for e in events if e.get("symbol") in mine]
    if my:
        lines.append("Your stocks: " + "; ".join(
            f"{esc(e['symbol'])} {'board meeting' if e.get('kind') == 'OTHER' else esc(str(e.get('kind')).lower())} {esc(e['event_date'])}"
            for e in my[:6]))
    res = [e for e in events if e.get("kind") == "RESULTS" and e.get("event_date", "") >= today][:10]
    if res:
        lines.append("Results: " + " · ".join(f"{esc(e['symbol'])} {esc(e['event_date'][5:])}" for e in res))
    for e in (eco.get("events") or [])[:10]:
        lines.append(f"◆ {esc(e['date'][5:])} {esc(e.get('time') or 'all day')} · {esc(e['what'])}")
    return "\n".join(lines)


def fmt_flags(flags: dict) -> str:
    hit = {s: f for s, f in flags.items() if f.get("chips")}
    if not hit:
        return "<b>NSE surveillance</b>: none of your holdings is flagged."
    lines = ["<b>NSE surveillance on your holdings</b>"]
    for s, f in hit.items():
        for c in f["chips"]:
            lines.append(f"⚑ <b>{esc(s)}</b> {esc(c['code'])}: {esc(c['why'])}")
    return "\n".join(lines)


def fmt_valuation(val: dict) -> str:
    vs, rel, ix = val.get("vs_history") or {}, val.get("rel_history") or {}, val.get("indices") or {}
    lines = ["<b>Valuation (NSE)</b> · P/E, its percentile since Mar 2021, vs NIFTY"]
    for name in ("NIFTY 50", "NIFTY NEXT 50", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA", "NIFTY FMCG"):
        r, h, rr = ix.get(name) or {}, vs.get(name) or {}, rel.get(name) or {}
        if r.get("pe"):
            lines.append(f"• {esc(name if name == 'NIFTY 50' else name.replace('NIFTY ', ''))} {r['pe']:.1f}×"
                         + (f" · {ordinal(h['pctl'])} pct" if h.get("pctl") is not None else "")
                         + (f" · {rr['ratio']}× NIFTY ({ordinal(rr['pctl'])})" if rr.get("ratio") else ""))
    return "\n".join(lines)


def fmt_desk(d: dict, crash: dict) -> str:
    lat, meta = d.get("latest") or {}, d.get("meta") or {}
    start = meta.get("start_capital") or 0
    lines = ["<b>Decision Desk</b> (paper)"]
    if lat:
        lines.append(f"NAV {inr(lat.get('nav'))} ({pct((lat['nav'] / start - 1) * 100 if start else None)}) · "
                     f"{lat.get('positions', 0)} positions · drawdown {pct((lat.get('drawdown') or 0) * 100)}")
    if crash:
        state = "risk-on" if crash.get("risk_on") else f"in the liquid fund (needs {pct(crash.get('move_needed_pct'), 1)})"
        lines.append(f"Crash filter: NIFTY {num(crash.get('nifty'), 0)} vs 200-day {num(crash.get('sma200'), 0)} → {state}")
        lines.append(f"Next monthly signal: {esc(crash.get('next_signal_date'))}")
    return "\n".join(lines)


def fmt_alerts(a: dict) -> str:
    al = a.get("alerts") or {}
    if not al:
        return "No alerts. Set one: /alert TCS above 2400 · /alert TCS move 3"
    lines = ["<b>Alerts</b>"]
    for s, lv in al.items():
        parts = [f"above {num(lv['above'])}" if lv.get("above") is not None else "",
                 f"below {num(lv['below'])}" if lv.get("below") is not None else "",
                 f"move ±{lv['move']:g}%" if lv.get("move") is not None else ""]
        lines.append(f"• <b>{esc(s)}</b> " + " · ".join(p for p in parts if p))
    return "\n".join(lines)


def parse_alert(args: list[str]) -> Optional[tuple[str, dict]]:
    """['TCS', 'above', '2400'] → ('TCS', {'above': 2400.0}); kinds: above, below, move."""
    if len(args) != 3:
        return None
    sym, kind, val = args[0].upper().removesuffix(".NS"), args[1].lower(), args[2].rstrip("%")
    if kind not in ("above", "below", "move") or not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        return None
    try:
        v = float(val)
    except ValueError:
        return None
    return (sym, {kind: v}) if v > 0 else None


# ── OTP hand-off ───────────────────────────────────────────────────────────────────

def otp_pending(now: Optional[float] = None) -> bool:
    try:
        req = json.loads(OTP_REQUEST.read_text())
    except (OSError, ValueError):
        return False
    return (now or time.time()) - float(req.get("at", 0)) < OTP_WINDOW_S


def extract_otp(text: str) -> Optional[str]:
    """The one 6-digit code in a free-text reply (a pasted SMS, "otp: 482 913"); None when there is none or several."""
    found = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    if not found:
        found = re.findall(r"(?<!\d)\d{6}(?!\d)", re.sub(r"(?<=\d)[ -](?=\d)", "", text))
    return found[0] if len(set(found)) == 1 else None


def store_otp(code: str) -> None:
    OTP_REPLY.parent.mkdir(parents=True, exist_ok=True)
    OTP_REPLY.write_text(json.dumps({"code": code, "at": time.time()}))


HOLDINGS_FILE = ROOT / "data" / "last_holdings.json"


async def _positions(get: Get) -> dict:
    """Open positions from ui-api; when that doesn't answer, the saved last-known book."""
    pos = await get("/api/positions/open-positions")
    if pos:
        return pos
    try:
        return {"connected": False, "positions": [], "last_known": json.loads(HOLDINGS_FILE.read_text())}
    except (OSError, ValueError):
        return {}


# ── dispatcher ─────────────────────────────────────────────────────────────────────

async def handle(text: str, get: Get, put: Get, actions: dict[str, Callable[..., Awaitable[str]]]) -> str:
    """One incoming message → the reply (HTML). `get` / `put` call ui-api; `actions` are side effects owned by the
    controller (login, password / user ID update)."""
    text = (text or "").strip()
    if re.fullmatch(r"\d{4,8}", text):                         # a bare code: the OTP, if a login is waiting
        if otp_pending():
            store_otp(text)
            return "Got the OTP. Submitting it to ICICI…"
        return "No ICICI login is waiting for a code. Send /login to start one."
    if not text.startswith("/"):
        code = extract_otp(text) if otp_pending() else None    # the whole SMS pasted, "OTP 482 913", …
        if code:
            store_otp(code)
            return f"Got the OTP ({code[:2]}…{code[-2:]}). Submitting it to ICICI…"
        return "Send /help for the commands."
    cmd, *args = text.split()
    cmd = cmd[1:].split("@")[0].lower()

    if cmd in ("help", "start"):
        return help_text()
    if cmd == "otp":
        if not args or not re.fullmatch(r"\d{4,8}", args[0]):
            return "Usage: /otp 123456"
        if not otp_pending():
            return "No ICICI login is waiting for a code. Send /login to start one."
        store_otp(args[0])
        return "Got the OTP. Submitting it to ICICI…"
    if cmd in ("login", "password", "userid", "status", "shadow"):
        return await actions[cmd](args)
    if cmd == "market":
        idx = await get("/api/market/indices-live", names="NIFTY 50,NIFTY BANK,INDIA VIX")
        return fmt_market(idx or {}, await get("/api/market/monitor") or {}, await get("/api/market/index-valuation") or {})
    if cmd in ("book", "flags", "brief"):
        pos = await _positions(get)
        rows = pos.get("positions") or (pos.get("last_known") or {}).get("positions") or []
        syms = [r["symbol"] for r in rows if r.get("symbol")]
        flags = ((await get("/api/market/surveillance", symbols=",".join(syms))) or {}).get("flags") or {} if syms else {}
        if cmd == "flags":
            return fmt_flags(flags)
        quotes = ((await get("/api/news-scanner/quotes", symbols=",".join(f"{s}.NS" for s in syms))) or {}).get("quotes") or {} if syms else {}
        book = fmt_book(pos, quotes, flags)
        if cmd == "book":
            return book
        idx = await get("/api/market/indices-live", names="NIFTY 50,NIFTY BANK,INDIA VIX")
        today = datetime.now().date().isoformat()
        events = ((await get("/api/market/events")) or {}).get("rows") or []
        eco = await get("/api/market/eco-calendar", back=0, ahead=2) or {}
        mine = set(syms)
        todays = [e for e in events if e.get("event_date") == today and (e.get("symbol") in mine or (e.get("turnover_cr") or 0) >= 100)]
        ev = ("<b>Today</b>: " + " · ".join(f"{esc(e['symbol'])} {'board mtg' if e['kind'] == 'OTHER' else esc(e['kind'].lower())}"
                                            for e in todays[:10])) if todays else ""
        data = [e for e in eco.get("events") or [] if e.get("date") == today]
        dl = ("<b>Data / holidays today</b>: " + "; ".join(f"{esc(e['what'])} {esc(e.get('time') or '')}" for e in data)) if data else ""
        return "\n\n".join(x for x in (fmt_market(idx or {}, await get("/api/market/monitor") or {},
                                                  await get("/api/market/index-valuation") or {}), book, ev, dl) if x)
    if cmd == "quote":
        if not args:
            return "Usage: /quote TCS"
        sym = args[0].upper().removesuffix(".NS")
        q = (((await get("/api/news-scanner/quotes", symbols=f"{sym}.NS")) or {}).get("quotes") or {}).get(f"{sym}.NS") or {}
        fin = (((await get("/api/market/financials-latest", symbols=sym)) or {}).get("latest") or {}).get(sym) or {}
        fl = (((await get("/api/market/surveillance", symbols=sym)) or {}).get("flags") or {}).get(sym) or {}
        events = ((await get("/api/market/events")) or {}).get("rows") or []
        return fmt_quote(sym, q, fin, fl, events)
    if cmd == "movers":
        return fmt_movers(await get("/api/market/live-movers") or {})
    if cmd == "results":
        return fmt_results(await get("/api/market/results-reacting") or {})
    if cmd == "events":
        pos = await _positions(get)
        rows = pos.get("positions") or (pos.get("last_known") or {}).get("positions") or []
        return fmt_events(await get("/api/market/eco-calendar", back=0, ahead=7) or {},
                          ((await get("/api/market/events")) or {}).get("rows") or [],
                          {r["symbol"] for r in rows if r.get("symbol")}, datetime.now().date().isoformat())
    if cmd == "valuation":
        return fmt_valuation(await get("/api/market/index-valuation") or {})
    if cmd == "desk":
        return fmt_desk(await get("/api/desk/status") or {}, await get("/api/market/crash-filter") or {})
    if cmd == "wrap":
        lst = ((await get("/api/market/wraps")) or {}).get("wraps") or []
        if not lst:
            return "No wrap yet."
        md = ((await get(f"/api/market/wraps/{lst[0]['date']}")) or {}).get("markdown") or ""
        md = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
        out = []
        for line in md.splitlines():
            if line.startswith("# "):
                out.append(f"<b>{esc(line[2:])}</b>")
            elif line.startswith("## "):
                out.append(f"\n<b>{esc(line[3:])}</b>")
            elif line.strip():
                out.append(esc(line))
        return "\n".join(out)
    if cmd == "alerts":
        return fmt_alerts(await get("/api/alerts") or {})
    if cmd == "alert":
        parsed = parse_alert(args)
        if not parsed:
            return "Usage: /alert TCS above 2400 · /alert TCS below 2100 · /alert TCS move 3"
        sym, lv = parsed
        cur = ((await get("/api/alerts")) or {}).get("alerts", {}).get(sym) or {}
        body = {"above": cur.get("above"), "below": cur.get("below"), "move": cur.get("move"), **lv}
        res = await put(f"/api/alerts/{sym}", body)
        if res is None:
            return f"Could not set the alert for {esc(sym)}."
        kind, v = next(iter(lv.items()))
        return f"Alert set: {esc(sym)} {kind} {'±' + format(v, 'g') + '%' if kind == 'move' else num(v)}. Checked every minute in market hours."
    if cmd == "unalert":
        if not args:
            return "Usage: /unalert TCS"
        sym = args[0].upper().removesuffix(".NS")
        res = await put(f"/api/alerts/{sym}", {"above": None, "below": None, "move": None})
        return f"Removed {esc(sym)}'s alerts." if res is not None else f"Could not remove {esc(sym)}'s alerts."
    return f"Unknown command /{esc(cmd)}. Send /help."
