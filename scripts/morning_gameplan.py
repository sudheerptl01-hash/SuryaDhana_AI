#!/usr/bin/env python
"""Morning Game Plan digest builder (terminal_final PLAN W7 / F-11, wave E).

Renders the GPLN payload (`GET /api/gameplan` on ui-api) as plain Telegram-ready text lines — the SAME assembly the
GPLN page shows, one tile per line, every line dated. This script only READS the ui-api endpoint and prints; the
controller's 08:50 job (registered by the PM, never by this script) imports `render_digest` and sends the text
through the controller's own Telegram path.

Honesty rules (PLAN §1, binding): no direction words, no score, no recommendation — facts assembled, the trader
decides. The digest ends with the mandatory line: "assembled from stored/live reads — describes, does not predict".
Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/morning_gameplan.py            # print the digest
    ... morning_gameplan.py --symbol BANKNIFTY --base http://127.0.0.1:8010 --json       # raw payload instead
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8010"
DESCRIBES = "describes, does not predict"


# ── formatting helpers (pure) ───────────────────────────────────────────────────────────────────────────────


def _n(v: Any, digits: int = 0) -> str:
    """An Indian-grouped number or an em dash."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    s = f"{v:,.{digits}f}"
    return s


def _pct(v: Any, digits: int = 2) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.{digits}f}%"


def _pts(v: Any, digits: int = 1) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.{digits}f}"


def _day(iso: Any) -> str:
    """'2026-11-13' → '13 Nov' ('' when absent)."""
    s = str(iso or "")[:10]
    if len(s) != 10:
        return ""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        return f"{int(s[8:10])} {months[int(s[5:7]) - 1]}"
    except (ValueError, IndexError):
        return s


def _tile(payload: dict[str, Any], key: str) -> dict[str, Any]:
    t = (payload.get("tiles") or {}).get(key)
    return t if isinstance(t, dict) else {}


# ── the digest (pure; unit-tested on a fixture payload) ─────────────────────────────────────────────────────


def render_digest(payload: dict[str, Any]) -> str:
    """The GPLN payload as Telegram text lines. Pure: no I/O, no clock — everything comes from the payload."""
    sym = payload.get("symbol") or "NIFTY"
    lines: list[str] = [f"MORNING GAME PLAN · {sym} · {_day(payload.get('date')) or payload.get('date') or '—'}"]

    o = _tile(payload, "overnight")
    if o.get("ok"):
        parts: list[str] = []
        gift = o.get("gift") or {}
        if gift.get("last") is not None or gift.get("implied_gap_pct") is not None:
            parts.append(f"GIFT {_n(gift.get('last'))} · implied open gap {_pct(gift.get('implied_gap_pct'))}")
        gold = o.get("gold") or {}
        if gold.get("last") is not None:
            partial = " (in-progress session)" if gold.get("partial") else ""
            parts.append(f"COMEX gold {_n(gold.get('last'))} · {_pct(gold.get('change_pct'))} vs prior close"
                         f" · as of {_day(gold.get('last_date'))}{partial}")
        if parts:
            lines.append("OVERNIGHT · " + " │ ".join(parts) + " · context")
    else:
        lines.append(f"OVERNIGHT · unavailable ({o.get('error', 'no read')})")

    lv = _tile(payload, "levels")
    if lv.get("ok"):
        lines.append(f"PRIOR SESSION ({_day(lv.get('session'))}) · close {_n(lv.get('close'))}"
                     f" ({_pct(lv.get('change_pct'))}) · high {_n(lv.get('high'))} · low {_n(lv.get('low'))} · arithmetic")
    else:
        lines.append(f"PRIOR SESSION · unavailable ({lv.get('error', 'no read')})")

    oi = _tile(payload, "oi")
    if oi.get("ok"):
        cw = " / ".join(_n(x) for x in (oi.get("call_walls") or [])[:2]) or "—"
        pw = " / ".join(_n(x) for x in (oi.get("put_walls") or [])[:2]) or "—"
        lines.append(f"CHAIN (EOD {_day(oi.get('date'))}, expiry {_day(oi.get('expiry'))} · {oi.get('days_to_expiry', '—')} DTE)"
                     f" · max pain {_n(oi.get('max_pain'))} · PCR {_n(oi.get('pcr_oi'), 2)}"
                     f" · largest call OI {cw} · largest put OI {pw} · context")
    else:
        lines.append(f"CHAIN · unavailable ({oi.get('error', 'no read')})")

    iv = _tile(payload, "iv")
    if iv.get("ok"):
        t, ch = iv.get("today") or {}, iv.get("change") or {}
        lines.append(f"IV ({_day(t.get('date'))}) · IV30 {_n(t.get('iv30_cm'), 1)} ({_pts(ch.get('iv30_cm'))} vs prior)"
                     f" · pctile {_n(t.get('iv_pctile_252'))} · rank {_n(t.get('iv_rank_252'))}"
                     f" · IV−RV20 {_pts(t.get('iv_minus_rv20'))} (close-to-close) · context")
    else:
        lines.append(f"IV · unavailable ({iv.get('error', 'no read')})")

    ev = _tile(payload, "events")
    if ev.get("ok"):
        eco = ev.get("eco") or []
        eco_txt = "; ".join(f"{e.get('what') or e.get('kind')} {_day(e.get('date'))}"
                            + (f" {e.get('time')}" if e.get("time") else "") for e in eco[:5]) or "none listed today/tomorrow"
        corp = ev.get("corporate") or {}
        corp_txt = f" │ corporate: {corp.get('count', 0)} rows today" if corp else ""
        lines.append(f"EVENTS · {eco_txt}{corp_txt} · context")
    else:
        lines.append(f"EVENTS · unavailable ({ev.get('error', 'no read')})")

    fo = _tile(payload, "focus")
    if fo.get("ok"):
        wl = fo.get("watchlist") or []
        wl_txt = ", ".join(wl[:8]) + (f" +{len(wl) - 8}" if len(wl) > 8 else "") if wl else "empty"
        fires = fo.get("fires") or {}
        fire_rows = fires.get("rows") or []
        fire_txt = f"{fires.get('count', 0)} since {_day(fires.get('since'))} 15:30"
        if fire_rows:
            fire_txt += " (" + "; ".join(str(r.get("text") or r.get("symbol") or "") for r in fire_rows[:3]) + ")"
        lines.append(f"FOCUS · watchlist: {wl_txt} │ alert fires: {fire_txt} · context")
    else:
        lines.append(f"FOCUS · unavailable ({fo.get('error', 'no read')})")

    lines.append(f"assembled from stored/live reads — {DESCRIBES}")
    return "\n".join(lines)


# ── fetch + CLI ─────────────────────────────────────────────────────────────────────────────────────────────


def fetch_payload(base: str = DEFAULT_BASE, symbol: str = "NIFTY", timeout: float = 30.0) -> dict[str, Any]:
    """GET /api/gameplan from ui-api (127.0.0.1 only — the terminal's own backend)."""
    url = f"{base.rstrip('/')}/api/gameplan?symbol={urllib.parse.quote(symbol)}"
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — localhost ui-api
        return json.loads(r.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print the Morning Game Plan digest (reads ui-api /api/gameplan)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--symbol", default="NIFTY", choices=["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
    ap.add_argument("--json", action="store_true", help="print the raw payload instead of the digest")
    args = ap.parse_args(argv)
    try:
        payload = fetch_payload(args.base, args.symbol)
    except Exception as exc:  # noqa: BLE001
        print(f"gameplan unavailable: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2) if args.json else render_digest(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
