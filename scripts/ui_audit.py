"""
UI audit: open every tab of the SuryaDhana terminal in a real browser, capture a screenshot, per-tab load
timing, browser console errors, uncaught page errors and failed requests (HTTP >= 400 / network errors).

Used page-by-page during the terminal restyle to prove each page still works, and for the desktop-app
43-page Chromium + WebKit gate (reports/desktop_app/PLAN.md AC-3; how-to: reports/desktop_app/qa_harness.md;
43 since the gold program's GOLD page, reports/gold_program/PLAN.md §h T10).

Usage (the original CLI still works unchanged):
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py [--out reports/ui_audit/after] \
        [--tabs "desk,stocks" | --tabs all] [--base http://127.0.0.1:8010] [--wait 6] \
        [--browser chromium|webkit|both] [--strict] [--screenshots full|viewport|none]
    Terminal v2 (G10): `--tabs v2` audits the ten pages wave 1 changed; `--tabs all --browser both` is the 43/43 gate.

Failure classes per tab (the policy lives in scripts/desktop_qa/netpolicy.py):
    navigation (goto failed) · not_ready (content/title never rendered) · app_error (error overlay text)
    · crash · page_error (uncaught) · console_error · failed_request (first-party HTTP >= 400 or network
    failure; EventSource/fetch streams on the 6 known stream paths aborted *by navigation* are allowlisted)
    · websocket_error · repetition (gold program T9: the words "fair open" in the titles of more than one
    panel or heading of a page — the pre-open desk must render on one page only) · live (reports/live_nse: while
    NSE is open a chip reading LIVE for a market feed must carry its age and be <= --live-max-age s old, and with the
    Breeze feed LIVE every page shows one such chip; after the close none reads LIVE; --no-live-check turns it off;
    the market state comes from two GETs to /api/live/quotes and /api/live/status, the clock when they 404).
    --strict adds console warnings, third-party failures and visible ErrorBoxes.

Outputs: <out>/audit.json (per-tab, original shape + new fields; with --browser both: <out>/<engine>/audit.json),
<out>/audit_report.json and <out>/audit_report.md (all engines, timing, summary).
Exit code: 0 = every tab passed, 1 = at least one tab failed, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop_qa.netpolicy import endpoint_key
from desktop_qa.pages import PageSourceError, load_page_source
from desktop_qa.probe import ENGINES, PREFS_MODES, TabProbe, failure_lines, launch_browser, new_qa_context, non_seam_failures

ROOT = Path(__file__).resolve().parents[1]
# Default tab set: the 15 of the restyle plus `gold` since the gold program (docs/RUNBOOK_RESTORE.md expects
# "16/16 ok"). Use --tabs all for the 43 pages of ui/app/page.tsx TAB_IDS (parsed at run time, so the count follows
# page.tsx without an edit here).
TABS = {"desk": "Decision Desk", "overview": "Overview", "stocks": "Stocks", "backtest": "Backtest",
        "positions": "Portfolio", "broker": "Broker Account", "pipeline": "Pipeline", "scanner": "LW Scanner",
        "discovery": "Alpha Discovery", "commodity": "Commodity", "gold": "Gold terminal", "glassbox": "Glass-Box",
        "mlengine": "ML Engine", "explorer": "Data Explorer", "warehouse": "Warehouse", "system": "System"}

# Terminal v2 (reports/terminal_v2/PLAN.md G10): `--tabs v2` = the pages wave 1 changed (OMON chain-first + IV history,
# DERV › VOL, MEMB drivers, EVTS crush ledger, SYS › DATA, DESK attribution, MOV live panel, OSTR margin, BRF, MKT). The
# sub-views (VOL / DATA) are reached in-page, so they ride on their pages here.
TAB_SETS: dict[str, list[str]] = {
    "v2": ["options", "derivatives", "memb", "events", "system", "desk", "movers", "ostrategy", "brief", "markets"],
}

# Gold program T9 (reports/gold_program/PLAN.md §h): the pre-open desk's "fair open" may be the subject of at most one
# panel or heading per page (it lives on GOLD; CMDT and BRF keep a line or a chip, never a second panel). Matched
# against the normalised fingerprint titles (numbers masked), never against body text.
REPETITION = re.compile(r"fair open", re.IGNORECASE)
REPETITION_MAX = 1

# Terminal v2 G9/G10 placement ("the same number once per page" across pages): the live today panel renders on MOV (BRF
# keeps a one-line summary), the drivers' horizon views on MEMB only. Matched against the start of a panel header's
# normalised text (title first, then subtitle and chips), never body text; a page outside the allowed set fails.
PLACEMENT: tuple[tuple[str, re.Pattern[str], frozenset[str]], ...] = (
    ("who moved the index", re.compile(r"^who moved the index", re.IGNORECASE), frozenset({"movers", "brief"})),
    ("drivers: sector contribution", re.compile(r"^sector contribution", re.IGNORECASE), frozenset({"memb"})),
    ("drivers: monthly leaderboard", re.compile(r"^monthly leaderboard", re.IGNORECASE), frozenset({"memb"})),
    ("drivers: concentration & breadth", re.compile(r"^concentration & breadth", re.IGNORECASE), frozenset({"memb"})),
)


def resolve_tabs(spec: str, tab_ids: list[str]) -> list[str]:
    """``all`` → every TAB_ID in page order; a TAB_SETS name (``v2``) → that set (only ids page.tsx still lists, when it
    could be read); otherwise a comma list (unknown ids are kept: the page ignores them)."""
    key = spec.strip().lower()
    if key == "all":
        return list(tab_ids)
    if key in TAB_SETS:
        return [t for t in TAB_SETS[key] if not tab_ids or t in tab_ids]
    return [t.strip() for t in spec.split(",") if t.strip()]


def repetition_hits(fingerprint: dict[str, Any] | None) -> list[str]:
    """Panel titles and headings of a fingerprint that name the pre-open desk's "fair open" (T9)."""
    if not fingerprint:
        return []
    titles = list(fingerprint.get("panels") or []) + list(fingerprint.get("headings") or [])
    return [t for t in titles if REPETITION.search(t or "")]


def placement_failures(tab: str | None, fingerprint: dict[str, Any] | None) -> list[str]:
    """v2 placement rule: a panel that belongs on other pages (PLACEMENT) found on ``tab``. Unknown tab → nothing."""
    if not tab or not fingerprint:
        return []
    out: list[str] = []
    for name, pattern, allowed in PLACEMENT:
        hits = [p for p in (fingerprint.get("panels") or []) if pattern.search((p or "").strip())]
        if hits and tab not in allowed:
            out.append(f"placement: '{name}' panel on {tab} (belongs on {'/'.join(sorted(allowed))} only): {hits[:2]}")
    return out


# ── Live program (reports/live_nse): the live-freshness assertion ─────────────────────────────────────────────────────
# "Live means exchange data seconds old." While NSE is open, every chip on a page that says LIVE for a market feed
# (Breeze / ICICI / NSE, or a bare LIVE) must carry its age and be at most LIVE_MAX_AGE_S old; when the ui-api live
# service reports the Breeze feed LIVE, each audited page must show at least one such fresh chip (the header NIFTY is on
# every page). After the close (the live service's own market state, never the clock alone) no market chip may read LIVE:
# the last price is CLOSE <session date>. Skipped when the market is closed per the clock, in pre-open, or for the
# non-NSE pages (gold, MCX, commodities: other markets and hours, gold PLAN §f chip rules).
# A chip's age comes from `data-sd-age-s` (seconds), else the age its label prints ('LIVE · BREEZE · 2s'), else the age
# its hover text states ('· 1s old', the header chip), else `data-sd-asof` (ISO time the feed last confirmed the value),
# read in the browser at the end of the visit; the elements are SourceChip (`data-sd-chip`), the header's feed chip
# (`data-feed`) and the stock window's price marker (`data-sd-price`).
LIVE_MAX_AGE_S = 10.0
# A quiet name on a healthy Breeze socket (no trade or quote change for a while; L-CAPACITY: illiquid names go up to 78 s
# between ticks) may read LIVE with its last-trade age when the chip SAYS so ("quiet" / "last trade" in its label or
# title): such a chip is held to the data-service quiet bound instead (live_quotes.QUIET_LIVE_S), and never counts as
# the page's fresh live pane.
QUIET_LIVE_MAX_S = 120.0
_QUIET = re.compile(r"\bquiet\b|last trade", re.IGNORECASE)
LIVE_EXEMPT_TABS = frozenset({"gold", "mcxgold", "commodity"})
LIVE_STATE_REFRESH_S = 60.0            # the market-state GETs are repeated at most once a minute (paced, GET only)
LIVE_PROBE_SYMBOL = "NIFTY 50"         # 10 ticks/s on the Breeze socket (L-CAPACITY): the feed's heartbeat
_MARKET_SOURCE = re.compile(r"\b(BREEZE|ICICI|NSE)\b")
_NON_MARKET_SOURCE = re.compile(r"\b(CONTROLLER|SERVICE|PROBES?|SESSION CLOCK|MCX|COMEX|YAHOO|GOLD)\b")
LIVE_CHIPS_JS = r"""() => {
  const out = []
  const nodes = document.querySelectorAll('[data-sd-chip],[data-feed],[data-sd-price]')
  for (const el of nodes) {
    const state = el.getAttribute('data-sd-chip') ?? el.getAttribute('data-feed') ?? el.getAttribute('data-sd-price') ?? ''
    out.push({
      kind: el.hasAttribute('data-sd-chip') ? 'chip' : el.hasAttribute('data-feed') ? 'feed' : 'price',
      state: String(state),
      label: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
      title: (el.getAttribute('title') || '').slice(0, 400),
      asof: el.getAttribute('data-sd-asof'),
      age_s: el.getAttribute('data-sd-age-s'),
      source: el.getAttribute('data-sd-feed-source'),
    })
  }
  return { now_ms: Date.now(), chips: out }
}"""


_IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_now() -> datetime:
    """Wall-clock time in IST (timezone-aware), so weekday and hour are read in IST whatever the machine's zone."""
    return datetime.now(timezone(_IST_OFFSET))


def clock_market_state(now_ist: datetime) -> str:
    """NSE's regular session by the clock alone (no holiday calendar): 'pre-open' 09:00-09:15, 'open' from 09:15 to
    before 15:30 on a weekday (data-service live_quotes.market_state's boundaries), else 'closed'. Only a fallback: the
    live service's own market state wins when it answers."""
    if now_ist.weekday() >= 5:
        return "closed"
    hm = now_ist.hour * 60 + now_ist.minute
    if 9 * 60 <= hm < 9 * 60 + 15:
        return "pre-open"
    if 9 * 60 + 15 <= hm < 15 * 60 + 30:
        return "open"
    return "closed"


def _parse_iso(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone(_IST_OFFSET))      # a naive stamp is IST (the app's clock)


_LABEL_AGE = re.compile(r"·\s*(?:last trade\s+)?(\d+(?:\.\d+)?)\s*(s|m|h)\b", re.IGNORECASE)
_TITLE_AGE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(s|m|h) old\b", re.IGNORECASE)
_AGE_UNIT_S = {"s": 1.0, "m": 60.0, "h": 3600.0}


def label_age_s(label: Any) -> float | None:
    """The age a chip PRINTS ('LIVE · BREEZE · 2s', 'DELAYED · NSE · 6m' — ui/components/terminal/source.ts fmtAgeS);
    None when the label carries none (a clock 'DELAYED · NSE · 10:58' is not an age)."""
    m = _LABEL_AGE.search(str(label or ""))
    return float(m.group(1)) * _AGE_UNIT_S[m.group(2).lower()] if m else None


def title_age_s(title: Any) -> float | None:
    """The age a chip's hover text states ('… · last tick 10:42:13 IST · 1s old', the header's live chip)."""
    m = _TITLE_AGE.search(str(title or ""))
    return float(m.group(1)) * _AGE_UNIT_S[m.group(2).lower()] if m else None


def chip_age_s(chip: dict[str, Any], now_ms: float) -> float | None:
    """Seconds since the chip's value was confirmed by its feed: `data-sd-age-s` when numeric, else the age the label
    prints, else the age its hover text states ('1s old'), else now − `data-sd-asof`. None = the chip does not say how
    old it is (a LIVE chip without an age breaks "every live number shows its age")."""
    raw = chip.get("age_s")
    if raw not in (None, ""):
        try:
            v = float(raw)
            if v == v and v >= 0:                       # not NaN
                return v
        except (TypeError, ValueError):
            pass
    printed = label_age_s(chip.get("label"))
    if printed is None:
        printed = title_age_s(chip.get("title"))
    if printed is not None:
        return printed
    t = _parse_iso(chip.get("asof"))
    if t is None:
        return None
    return max(0.0, now_ms / 1000.0 - t.timestamp())


def is_live_market_chip(chip: dict[str, Any]) -> bool:
    """A chip that claims a LIVE market price: state 'live' and its label names a market feed (BREEZE / ICICI / NSE) or
    none at all ('● LIVE'). LIVE · CONTROLLER, LIVE · SERVICE PROBES, LIVE · MCX SESSION CLOCK are not market prices."""
    if str(chip.get("state") or "").strip().lower() != "live":
        return False
    text = f"{chip.get('source') or ''} {chip.get('label') or ''}".upper()
    if _NON_MARKET_SOURCE.search(text) and not _MARKET_SOURCE.search(text):
        return False
    return True


def live_failures(tab: str | None, probe: dict[str, Any] | None, ctx: dict[str, Any] | None, *,
                  max_age_s: float = LIVE_MAX_AGE_S) -> list[str]:
    """The live-freshness lines for one tab (empty = pass or not applicable). ``probe`` is LIVE_CHIPS_JS's result,
    ``ctx`` the market context from ``live_context`` ({market, authoritative, feed})."""
    if not tab or tab in LIVE_EXEMPT_TABS or not probe or not ctx:
        return []
    chips = [c for c in (probe.get("chips") or []) if isinstance(c, dict)]
    now_ms = float(probe.get("now_ms") or time.time() * 1000)
    live = [c for c in chips if is_live_market_chip(c)]
    market = ctx.get("market")
    out: list[str] = []
    if market == "open":
        fresh = 0
        for c in live:
            age = chip_age_s(c, now_ms)
            quiet = bool(_QUIET.search(f"{c.get('label') or ''} {c.get('title') or ''}"))
            bound = QUIET_LIVE_MAX_S if quiet else max_age_s
            if age is None:
                out.append(f"live: '{c.get('label')}' reads LIVE with no age (data-sd-asof / data-sd-age-s missing)")
            elif age > bound:
                kind = "a quiet LIVE" if quiet else "LIVE"
                out.append(f"live: '{c.get('label')}' reads {kind} but is {age:.0f} s old (max {bound:.0f} s while NSE is open)")
            elif not quiet:
                fresh += 1
        if ctx.get("feed") == "LIVE" and fresh == 0:
            out.append(f"live: the Breeze feed is LIVE but no pane on {tab} shows a live price ≤ {max_age_s:.0f} s old")
    elif market == "closed" and ctx.get("authoritative"):
        for c in live:
            out.append(f"live: '{c.get('label')}' reads LIVE after the close (expected CLOSE <session date>)")
    return out


def api_live_failures(ctx: dict[str, Any] | None, *, max_age_s: float = LIVE_MAX_AGE_S) -> list[str]:
    """Run-level check on the live service itself (GET /api/live/quotes): with the market open and the feed LIVE the
    heartbeat symbol is a Breeze tick ≤ max_age_s old; after the close it is labelled closed, never live."""
    if not ctx or not ctx.get("authoritative"):
        return []
    q = ctx.get("probe_quote") or {}
    out: list[str] = []
    if ctx.get("market") == "open" and ctx.get("feed") == "LIVE":
        age = q.get("age_s")
        if q.get("state") != "live" or q.get("source") != "breeze_ws":
            out.append(f"live api: feed LIVE but {LIVE_PROBE_SYMBOL} is {q.get('state')}/{q.get('source')}, not live/breeze_ws")
        elif not isinstance(age, int | float) or age > max_age_s:
            out.append(f"live api: {LIVE_PROBE_SYMBOL} age_s {age} > {max_age_s:.0f} with the feed LIVE")
    elif ctx.get("market") == "closed" and q:
        if q.get("state") == "live":
            out.append(f"live api: {LIVE_PROBE_SYMBOL} state live after the close (expected closed)")
    return out


def _get_json(url: str, timeout_s: float = 5.0) -> tuple[int, Any]:
    """One GET (the audit never writes). (status, body) — status 0 on a network error, body None if not JSON."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:   # noqa: S310 - the audited origin only
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def live_context(base: str, *, fetch: Any = _get_json, now_ist: datetime | None = None) -> dict[str, Any]:
    """Market state for the live assertions. Two paced GETs to the audited origin: /api/live/quotes?symbols=NIFTY 50
    (market.state + the heartbeat quote) and /api/live/status (the feed state). When the live service does not answer
    (not deployed: 404) the clock decides open/closed and the result is not authoritative (no after-close rule, no
    feed rule)."""
    from urllib.parse import quote

    base = base.rstrip("/")
    ctx: dict[str, Any] = {"market": clock_market_state(now_ist or _ist_now()), "authoritative": False, "feed": None,
                           "probe_quote": None, "session_date": None, "checked_at": time.time(), "notes": []}
    st, body = fetch(f"{base}/api/live/quotes?symbols={quote(LIVE_PROBE_SYMBOL)}")
    if st == 200 and isinstance(body, dict) and isinstance(body.get("market"), dict):
        m = body["market"]
        if m.get("state") in ("open", "pre-open", "closed"):
            ctx.update(market=m["state"], authoritative=True, session_date=m.get("session_date"))
        ctx["probe_quote"] = ((body.get("quotes") or {}).get(LIVE_PROBE_SYMBOL)) or None
    else:
        ctx["notes"].append(f"/api/live/quotes answered {st or 'no connection'}: market state from the clock")
    st2, status = fetch(f"{base}/api/live/status")
    if st2 == 200 and isinstance(status, dict):
        ctx["feed"] = status.get("state")
    else:
        ctx["notes"].append(f"/api/live/status answered {st2 or 'no connection'}: feed rule skipped")
    return ctx


class LiveGate:
    """The audit run's live assertion: the market context (refreshed at most every LIVE_STATE_REFRESH_S) and the
    per-tab failure lines. ``fetch`` and ``clock`` are injectable for the unit tests."""

    def __init__(self, base: str, *, max_age_s: float = LIVE_MAX_AGE_S, fetch: Any = _get_json,
                 clock: Any = time.time, now_ist: Any = None) -> None:
        self.base, self.max_age_s, self._fetch, self._clock, self._now_ist = base, max_age_s, fetch, clock, now_ist
        self.ctx: dict[str, Any] | None = None
        self.contexts: list[dict[str, Any]] = []

    def context(self) -> dict[str, Any]:
        if self.ctx is None or self._clock() - float(self.ctx.get("checked_at") or 0) > LIVE_STATE_REFRESH_S:
            self.ctx = live_context(self.base, fetch=self._fetch, now_ist=self._now_ist() if self._now_ist else None)
            self.ctx["checked_at"] = self._clock()
            self.contexts.append(self.ctx)
        return self.ctx

    def tab(self, tab: str | None, probe: dict[str, Any] | None) -> dict[str, Any]:
        """{market, feed, authoritative, chips, failures} for one visited tab (stored in the tab's result)."""
        ctx = self.context()
        fails = live_failures(tab, probe, ctx, max_age_s=self.max_age_s)
        chips = [c for c in ((probe or {}).get("chips") or []) if isinstance(c, dict)]
        return {"market": ctx.get("market"), "feed": ctx.get("feed"), "authoritative": ctx.get("authoritative"),
                "exempt": bool(tab in LIVE_EXEMPT_TABS), "live_chips": sum(is_live_market_chip(c) for c in chips),
                "chips": chips[:40], "failures": fails}

    def run_failures(self) -> list[str]:
        out: list[str] = []
        for c in self.contexts:
            out.extend(f for f in api_live_failures(c, max_age_s=self.max_age_s) if f not in out)
        return out


class LiveTabProbe(TabProbe):
    """TabProbe that reads the page's live chips (LIVE_CHIPS_JS) at the end of each visit, just before it leaves the tab
    (visit() always leaves through leave()), keyed by the visit's epoch."""

    def __init__(self, page: Any, base: str, *, capture_live: bool = True) -> None:
        super().__init__(page, base)
        self.capture_live = capture_live
        self.live_chips: dict[int, Any] = {}

    def leave(self, flush_ms: int = 250) -> None:
        epoch = self.active
        if self.capture_live and epoch is not None:
            self.live_chips[epoch] = self._eval(LIVE_CHIPS_JS)
        super().leave(flush_ms)


def tab_failures(visit: dict[str, Any], events: dict[str, Any], *, strict: bool) -> list[str]:
    """The audit's failure lines for one tab: the shared policy (probe.failure_lines), the T9 repetition rule and the
    Terminal v2 placement rule."""
    lines = failure_lines(visit, events, strict=strict)
    hits = repetition_hits(visit.get("fingerprint"))
    if len(hits) > REPETITION_MAX:
        lines.append(f"repetition: 'fair open' named by {len(hits)} panels/headings (T9 allows {REPETITION_MAX}): {hits}")
    lines.extend(placement_failures(visit.get("tab"), visit.get("fingerprint")))
    return lines


def audit_engine(pw: Any, engine: str, tabs: list[str], args: argparse.Namespace, out_dir: Path,
                 names: dict[str, str], codes: dict[str, str], live_gate: LiveGate | None = None) -> dict[str, Any]:
    """Audit ``tabs`` in one engine; returns {tab: result}. ``live_gate``: the live-freshness assertion (None = off)."""
    browser = launch_browser(pw, engine, chromium_channel=args.chromium_channel or None)
    version = browser.version
    ctx = new_qa_context(browser, prefs_mode=args.prefs_mode,
                         viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
    page = ctx.new_page()
    probe = LiveTabProbe(page, args.base, capture_live=live_gate is not None)
    shots = None if args.screenshots == "none" else out_dir
    visits: list[dict[str, Any]] = []
    try:
        for tab in tabs:
            v = probe.visit(tab, code=codes.get(tab), nav_timeout_s=args.nav_timeout, ready_timeout_s=args.ready_timeout,
                            idle_timeout_s=args.idle_timeout if args.idle_timeout is not None else args.wait + 15,
                            dwell_s=args.wait, drain_timeout_s=args.drain_timeout, fingerprint=True, screenshot_dir=shots,
                            full_page=args.screenshots == "full")
            visits.append(v)
            if live_gate is not None:
                v["live"] = live_gate.tab(tab, probe.live_chips.get(v["epoch"]))
            ev = probe.summarize(v["epoch"])
            fails = tab_failures(v, ev, strict=args.strict) + list((v.get("live") or {}).get("failures") or [])
            t = v["timing"]
            print(f"[{engine}] {names.get(tab, tab):22} ok={v['error'] is None} {'PASS' if not fails else 'FAIL'} "
                  f"ready={t['ready_ms']}ms total={t['total_ms']}ms console={len(ev['console_errors'])} "
                  f"pageerr={len(ev['page_errors'])} failed={len(ev['failed_requests'])} "
                  f"allowed={len(ev['allowed_aborts'])}{' ' + fails[0][:140] if fails else ''}", flush=True)
    finally:
        probe.leave()
        browser.close()
    results: dict[str, Any] = {}
    for v in visits:   # final summaries: late (post-navigation) events are attributed to their tab by now
        ev = probe.summarize(v["epoch"])
        fails = tab_failures(v, ev, strict=args.strict) + list((v.get("live") or {}).get("failures") or [])
        tab = v["tab"]
        api_failed = [f"{f['status']} {f['method']} {f['url']}" if f["status"] else f"FAILED {f['method']} {f['url']} {f['failure']}"
                      for f in ev["failed_requests"] if "/api/" in f["url"]]
        results[tab] = {
            # original fields (kept for compatibility)
            "name": names.get(tab, tab), "ok": v["error"] is None, "screenshot": v.get("screenshot"),
            "load_s": round((v["timing"]["total_ms"] or 0) / 1000, 1),
            "console": (ev["console_errors"] + ev["console_warnings"])[:30], "failed_api": api_failed[:30],
            "error_text": bool(v.get("app_error")), **({"error": v["error"]} if v["error"] else {}),
            # new fields
            "engine": engine, "browser_version": version, "code": codes.get(tab), "url": v["url"],
            "pass": not fails, "failures": fails, "timing": v["timing"], "nav_timing": v.get("nav_timing"),
            "console_errors": ev["console_errors"], "console_warnings": ev["console_warnings"],
            "console_detail": ev["console_detail"],
            "failures_non_seam": non_seam_failures(fails, ev["failed_requests"], ev["console_detail"]),
            "page_errors": ev["page_errors"], "failed_requests": ev["failed_requests"],
            "allowed_aborts": ev["allowed_aborts"], "third_party_failures": ev["third_party_failures"],
            "websockets": ev["websockets"], "api_endpoints": len(ev["api"]), "non_get_api": ev["non_get_api"],
            "fingerprint": v.get("fingerprint"), "pending_at_leave": v.get("pending_at_leave"),
            "repetition_hits": repetition_hits(v.get("fingerprint")),
            "live": v.get("live"),
        }
    return results


def _pct(vals: list[int], q: float) -> int | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))]


def failed_endpoints(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Failed requests aggregated across tabs: templated endpoint + reason → the tabs it failed on."""
    agg: dict[str, dict[str, Any]] = {}
    for tab, r in results.items():
        for f in r["failed_requests"]:
            key = f"{endpoint_key(f['method'], f['url'])} → {f['reason']}"
            slot = agg.setdefault(key, {"endpoint": key, "platform_seam": bool(f.get("seam")), "tab_ids": []})
            if tab not in slot["tab_ids"]:
                slot["tab_ids"].append(tab)
    rows = sorted(agg.values(), key=lambda x: (-len(x["tab_ids"]), x["endpoint"]))
    return [{**x, "tabs": len(x["tab_ids"])} for x in rows]


def summarize(results: dict[str, Any]) -> dict[str, Any]:
    ready = [r["timing"]["ready_ms"] for r in results.values()]
    return {"tabs": len(results), "passed": sum(r["pass"] for r in results.values()),
            "failed": [t for t, r in results.items() if not r["pass"]],
            "console_errors": sum(len(r["console_errors"]) for r in results.values()),
            "page_errors": sum(len(r["page_errors"]) for r in results.values()),
            "failed_requests": sum(len(r["failed_requests"]) for r in results.values()),
            "allowed_aborts": sum(len(r["allowed_aborts"]) for r in results.values()),
            "third_party_failures": sum(len(r["third_party_failures"]) for r in results.values()),
            "ready_ms_p50": _pct(ready, .5), "ready_ms_p95": _pct(ready, .95), "ready_ms_max": _pct(ready, 1),
            # diagnostics only (pass/fail is unchanged): which failures are platform-seam probes
            "failed_non_seam": [t for t, r in results.items() if r.get("failures_non_seam")],
            "failed_endpoints": failed_endpoints(results)}


def render_markdown(report: dict[str, Any]) -> str:
    m = report["meta"]
    lines = [f"# UI audit — {m['base']}", "",
             f"- started {m['started_at']} · finished {m['finished_at']} · strict={m['strict']} · wait={m['wait_s']}s",
             f"- label: {m.get('label') or '—'}", ""]
    for engine, block in report["engines"].items():
        s = block["summary"]
        lines += [f"## {engine} ({block['browser_version']}): {s['passed']}/{s['tabs']} PASS", "",
                  (f"console errors {s['console_errors']} · page errors {s['page_errors']} · failed requests "
                  f"{s['failed_requests']} · allowlisted stream aborts {s['allowed_aborts']} · third-party "
                  f"{s['third_party_failures']} · ready p50 {s['ready_ms_p50']} ms / p95 {s['ready_ms_p95']} ms / "
                  f"max {s['ready_ms_max']} ms"), "",
                  "| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for tab, r in block["tabs"].items():
            t, nt = r["timing"], r.get("nav_timing") or {}
            first = (r["failures"][0] if r["failures"] else "").replace("|", "\\|")[:160]
            lines.append(f"| {tab} | {r['code'] or ''} | {'PASS' if r['pass'] else '**FAIL**'} | {t['ready_ms']} | "
                         f"{t['idle_ms'] if t['idle_ms'] is not None else '—'} | {t['total_ms']} | {nt.get('fcp_ms')} | "
                         f"{len(r['console_errors'])} | {len(r['page_errors'])} | {len(r['failed_requests'])} | {first} |")
        lines.append("")
        fe = s.get("failed_endpoints") or []
        if fe:
            lines += [f"### {engine}: failed requests by endpoint", "",
                      (f"Tabs failing for anything other than a platform-seam probe: "
                       f"{', '.join(s.get('failed_non_seam') or []) or 'none'}"), "",
                      "| endpoint → reason | platform seam | tabs | tab ids |", "|---|---|---:|---|"]
            for x in fe:
                ids = ", ".join(x["tab_ids"][:12]) + (" …" if len(x["tab_ids"]) > 12 else "")
                lines.append(f"| {x['endpoint'].replace('|', chr(92) + '|')} | {'yes' if x['platform_seam'] else 'no'} | "
                             f"{x['tabs']} | {ids} |")
            lines.append("")
    lv = report.get("live")
    if lv:
        ctxs = lv.get("contexts") or []
        last = ctxs[-1] if ctxs else {}
        lines += ["## Live freshness (reports/live_nse)", "",
                  (f"- market {last.get('market')} ({'live service' if last.get('authoritative') else 'clock'}) · feed "
                   f"{last.get('feed') or '—'} · max age {lv.get('max_age_s')} s · run-level failures: "
                   f"{'; '.join(lv.get('api_failures') or []) or 'none'}"), ""]
    elif report["meta"].get("live_check") is False:
        lines += ["## Live freshness (reports/live_nse)", "", "- off (--no-live-check)", ""]
    lines.append(f"**Overall: {'PASS' if report['ok'] else 'FAIL'}**")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "reports" / "ui_audit" / "after"))
    ap.add_argument("--tabs", default=",".join(TABS),
                    help="tab ids, e.g. desk,stocks — or 'all' (page.tsx TAB_IDS) or a set name: " + ", ".join(TAB_SETS))
    ap.add_argument("--base", default="http://127.0.0.1:8010",
                    help="terminal origin (default: the live terminal served by ui-api; the old Next server was "
                         "http://localhost:3000, still usable with --base)")
    ap.add_argument("--wait", type=float, default=6.0, help="dwell seconds after load (errors surface, polls run)")
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=1050)
    ap.add_argument("--browser", choices=["chromium", "webkit", "both"], default="chromium")
    ap.add_argument("--strict", action="store_true", help="also fail on console warnings, third-party failures, ErrorBoxes")
    ap.add_argument("--screenshots", choices=["full", "viewport", "none"], default="full",
                    help="full = viewport + full-page PNG (the original behaviour)")
    ap.add_argument("--idle-timeout", type=float, default=None, help="cap on the network-idle wait (default wait+15 s)")
    ap.add_argument("--ready-timeout", type=float, default=30.0, help="max wait for the page's content/title")
    ap.add_argument("--nav-timeout", type=float, default=180.0)
    ap.add_argument("--drain-timeout", type=float, default=15.0,
                    help="max wait for in-flight API calls before leaving a tab (so the harness does not abort them)")
    ap.add_argument("--chromium-channel", default="chrome", help="'chrome' = system Chrome (original); '' = bundled")
    ap.add_argument("--json", default=None, help="report JSON path (default <out>/audit_report.json)")
    ap.add_argument("--md", default=None, help="report Markdown path (default <out>/audit_report.md)")
    ap.add_argument("--label", default="", help="free text recorded in the report (e.g. 'baseline live :3000')")
    ap.add_argument("--no-live-check", dest="live_check", action="store_false",
                    help="skip the live-freshness assertion (reports/live_nse): while NSE is open a LIVE market chip must "
                         "carry its age and be <= --live-max-age s old; after the close none may read LIVE")
    ap.add_argument("--live-max-age", type=float, default=LIVE_MAX_AGE_S, help="max age of a LIVE chip, seconds (default 10)")
    ap.add_argument("--prefs-mode", choices=PREFS_MODES, default="readonly",
                    help="the UI's settings-sync mode in the audit browser (default readonly: never writes the "
                         "owner's live /api/prefs); 'sync' only against a scratch server")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        src = load_page_source()
        tab_ids, codes = src.tab_ids, {p.id: p.code for p in src.command_pages}
        names = {**{p.id: p.label for p in src.command_pages}, **TABS}
    except (OSError, PageSourceError) as exc:   # page.tsx unreadable or reshaped: the explicit-list mode still works
        if args.tabs.strip().lower() == "all":
            print(f"cannot resolve --tabs all: {exc}", file=sys.stderr)
            return 2
        tab_ids, codes, names = [], {}, dict(TABS)
    tabs = resolve_tabs(args.tabs, tab_ids)
    engines = list(ENGINES) if args.browser == "both" else [args.browser]
    report: dict[str, Any] = {"meta": {"base": args.base, "tabs": tabs, "engines": engines, "strict": args.strict,
                                       "wait_s": args.wait, "label": args.label, "live_check": args.live_check,
                                       "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
                              "engines": {}}
    t0 = time.time()
    live_gate = LiveGate(args.base, max_age_s=args.live_max_age) if args.live_check else None
    with sync_playwright() as pw:
        for engine in engines:
            eng_dir = out if len(engines) == 1 else out / engine
            eng_dir.mkdir(parents=True, exist_ok=True)
            results = audit_engine(pw, engine, tabs, args, eng_dir, names, codes, live_gate=live_gate)
            (eng_dir / "audit.json").write_text(json.dumps(results, indent=2))
            version = next((r["browser_version"] for r in results.values()), None)
            report["engines"][engine] = {"browser_version": version, "summary": summarize(results), "tabs": results}
    report["meta"]["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report["meta"]["elapsed_s"] = round(time.time() - t0, 1)
    report["ok"] = all(not b["summary"]["failed"] for b in report["engines"].values())
    if live_gate is not None:
        api_fails = live_gate.run_failures()
        report["live"] = {"max_age_s": live_gate.max_age_s, "contexts": live_gate.contexts, "api_failures": api_fails}
        report["ok"] = report["ok"] and not api_fails
    json_path = Path(args.json) if args.json else out / "audit_report.json"
    md_path = Path(args.md) if args.md else out / "audit_report.md"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(render_markdown(report))
    for engine, b in report["engines"].items():
        s = b["summary"]
        print(f"[{engine}] {s['passed']}/{s['tabs']} PASS · failed tabs: {', '.join(s['failed']) or 'none'}")
    print(f"report: {md_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
