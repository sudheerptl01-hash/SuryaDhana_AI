"""The named ingest groups (PLAN §c.3) behind ``POST /jobs/ingest-gold``.

A job is a list of group names. Every group is one named function with its own due rule (``cadence``), its own
``max_age`` freshness table and failure isolation: an exception inside a group becomes ``{"status": "error"}`` for that
group and the next group still runs. ``backfill_from`` (PLAN §c.4) switches a group to its resumable, paced history
pull. Aliases map the controller's group names (B2) to the functions here. Nothing in a group restarts anything,
and nothing written here feeds the Decision Desk, the S1 shadow or the paper ticket.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import (
    catalog_seed,
    db,
    derive,
    ingest_cme,
    ingest_cot,
    ingest_india,
    ingest_local,
    ingest_macro,
    ingest_physical,
    ingest_yahoo,
    mcx_close,
    mcx_daily,
    schema,
)
from gold.db import utcnow
from gold.hosts import ftp_fetch
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SHANGHAI = ZoneInfo("Asia/Shanghai")
# Due rule (PLAN §c.3): every run of a dated group records in gold_ingest_state whether its table's freshness column
# ADVANCED (a new trade_date / report_date / as_of appeared). A run that found something new waits the full gap; a run
# that found nothing new (the publisher's T+1 file not there yet, a 304, an unchanged monthly value) is retried at the
# next controller slot after the short gap — so the 17:15 CME retry runs when 15:45 found yesterday's file, and a
# monthly group that already fetched this month's value is not re-fetched daily until a value changes.
DAILY_GAP_H = 6.0            # after a daily run that found new data
RETRY_GAP_H = 1.0            # after a daily run that found nothing new (the 15:45 → 17:15 CME slot is 1.5 h apart)
WEEKLY_GAP_H = 20.0          # after a weekly run that found new data; a weekly run with nothing new retries after DAILY_GAP_H
MONTHLY_GAP_H = 72.0         # a monthly group retries every 3 days from publish_day until the new month's value arrives
FRESHNESS: dict[str, str] = {**schema.FRESHNESS_COLUMN, "gold_cme_calendar": "as_of", "gold_cme_prf": "biz_date",
                             "gold_margins": "trade_date"}

ALIASES: dict[str, str] = {
    "cme_voi_final": "cme_voi", "etf": "etf_holdings", "fed_path": "atlanta_fed", "bars_1m": "intraday_bars",
    "gpr_daily": "gpr", "gpr_monthly": "gpr", "lbma_wgc": "wgc_price", "margins": "zerodha_margins",
    "fred": "fred_daily", "sge_intraday": "sge_quotes", "yahoo": "yahoo_daily", "curve": "yahoo_curve",
    "mcx_close": "mcx_close_vwap30", "vwap30": "mcx_close_vwap30",
}
# O-8 (6 Nov 2026): the owner authorised the Breeze daily history only (group breeze_daily, gold/mcx_daily.py); the two
# MCX-site collectors stay dormant
DORMANT: dict[str, str] = {
    "mcx_official": "MCX official bhavcopy needs a browser-session collector the owner has not authorised (O-8)",
    "mcx_category": "MCX category-wise OI workbook needs the same collector (O-8)",
}
MONTHLY_SET: tuple[str, ...] = ("imf_official", "wgc_sd", "sge_monthly", "lbma_vault", "amfi", "gpr", "worldbank", "fred_monthly",
                                "swiss")   # E19 (PLAN §c.3 gold_morning); the 692 MB zip streams to a temp file, once a month


@dataclass
class Ctx:
    store: Any
    http: Any
    now: datetime
    backfill_from: date | None = None
    force: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    progress: Callable[[int, int], None] | None = None
    breeze: Callable[[], Any] | None = None    # data-service's live Breeze session getter (None in tests / no session)

    @property
    def today_ist(self) -> date:
        return self.now.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST).date()


@dataclass(frozen=True)
class Group:
    name: str
    run: Callable[[Ctx], dict[str, Any]]
    cadence: str                         # always | daily | weekly | monthly
    table: str | None = None             # freshness table for the due rule
    where: str = ""                      # SQL filter on that table (no user input)
    publish_day: int = 1                 # monthly groups: due from this day of the month
    heavy: bool = False
    note: str = ""


# ── due rule ────────────────────────────────────────────────────────────────────────────────────────

def last_seen(store: Any, table: str, where: str = "") -> datetime | None:
    """MAX(first_seen_at) of the group's rows — the fallback when no run has been recorded yet (rows written by a
    backfill or before the bookkeeping existed)."""
    v = db.max_of(store, table, "first_seen_at", where)
    return None if v is None else pd.Timestamp(v).to_pydatetime()


def freshness(store: Any, g: Group) -> str | None:
    """MAX of the group's freshness column (``trade_date`` / ``report_date`` / …) as text, or None when the table is empty."""
    if g.table is None:
        return None
    col = FRESHNESS.get(g.table)
    if col is None:
        return None
    v = db.max_of(store, g.table, col, g.where)
    return None if v is None else str(v)


def _run_key(g: Group) -> str:
    return f"run:{g.name}"


def last_run(store: Any, g: Group) -> dict[str, Any] | None:
    """The recorded outcome of the group's last run: {at, status, advanced, before, after} or None."""
    raw = db.get_state(store, _run_key(g))
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and rec.get("at") else None


def record_run(store: Any, g: Group, ctx: Ctx, *, status: str, before: str | None) -> dict[str, Any]:
    """Store the run's outcome; ``advanced`` is True when the freshness column moved past ``before``."""
    after = freshness(store, g)
    advanced = after is not None and (before is None or after > before)
    rec = {"at": ctx.now.isoformat(), "status": status, "advanced": advanced, "before": before, "after": after}
    db.set_state(store, _run_key(g), json.dumps(rec), now=ctx.now)
    return rec


def is_due(g: Group, ctx: Ctx) -> tuple[bool, str]:
    if ctx.force or ctx.backfill_from is not None or g.cadence == "always" or g.table is None:
        return True, "forced" if (ctx.force or ctx.backfill_from) else "always"
    run = last_run(ctx.store, g)
    if run is None:
        last = last_seen(ctx.store, g.table, g.where)
        if last is None:
            return True, "never fetched"
        advanced = True                                   # rows exist but no run is recorded: treat as fresh
    else:
        last = datetime.fromisoformat(str(run["at"]))
        advanced = bool(run.get("advanced"))
    age_h = (ctx.now - last).total_seconds() / 3600.0
    found = "new data" if advanced else "nothing new"
    if g.cadence == "daily":
        gap = DAILY_GAP_H if advanced else RETRY_GAP_H
        return (age_h >= gap), f"last fetch {age_h:.1f} h ago ({found}; gap {gap:g} h)"
    if g.cadence == "weekly":
        gap = WEEKLY_GAP_H if advanced else DAILY_GAP_H
        return (age_h >= gap), f"last fetch {age_h:.1f} h ago ({found}; gap {gap:g} h)"
    today = ctx.today_ist
    if today.day < g.publish_day:
        return False, f"monthly: due from day {g.publish_day}"
    last_ist = last.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST).date()
    if advanced and (last_ist.year, last_ist.month) == (today.year, today.month) and last_ist.day >= g.publish_day:
        return False, f"monthly: fetched this month on {last_ist} (new data)"
    return (age_h >= MONTHLY_GAP_H), f"last fetch {age_h / 24:.1f} d ago ({found}; gap {MONTHLY_GAP_H / 24:g} d)"


# ── group functions ─────────────────────────────────────────────────────────────────────────────────

def g_treasury(ctx: Ctx) -> dict[str, Any]:
    years = range(ctx.backfill_from.year, ctx.today_ist.year + 1) if ctx.backfill_from else [ctx.today_ist.year]
    out: dict[str, Any] = {}
    for y in years:
        out[str(y)] = ingest_macro.fetch_treasury(ctx.store, ctx.http, year=y, now=ctx.now)
    return {"years": out, "inserted": _sum(out, "inserted")}


def g_yahoo_daily(ctx: Ctx) -> dict[str, Any]:
    syms = ctx.params.get("symbols")
    res = ingest_yahoo.fetch_daily(ctx.store, ctx.http, symbols=syms, backfill_from=ctx.backfill_from, now=ctx.now)
    out = {"symbols": res, "inserted": sum(int(v.get("rows") or 0) for v in res.values()),
           "stale": [s for s, v in res.items() if v.get("stale")],
           # wave 2 (C-DATA-05): a bar fetched before its session closed is re-fetched until it is final; the run says how
           # many healed and how many are still in-progress (today's own bar is normally one of them)
           "repaired_partials": sum(int(v.get("repaired_partials") or 0) for v in res.values()),
           "partials_open": sum(int(v.get("partials_open") or 0) for v in res.values())}
    # wave 1e (M-C): a CNY=X bar revised by this run re-derives the Shanghai pair now (store arithmetic, no fetch), not at
    # 21:30 — the printed legs and the premium never disagree for a day
    if "CNY=X" in res:
        try:
            out["shanghai_rederive"] = derive.derive_shanghai(ctx.store, now=ctx.now)
        except Exception as exc:  # noqa: BLE001 — a derive failure never fails the fetch group
            out["shanghai_rederive"] = {"status": "error", "error": str(exc)[:160]}
    return out


def g_yahoo_partials(ctx: Ctx) -> dict[str, Any]:
    """Heal a bar that was fetched before its session closed WITHOUT waiting for the next 03:10 overnight pull
    (C-DATA-05, round 2). Only the symbols whose LATEST stored bar is such a bar and whose session has since closed are
    re-pulled — at most ``PARTIAL_REPAIR_MAX_SYMBOLS`` paced calls through the one gold fetcher, and no call at all when
    there is nothing to heal. A session still running is never re-pulled, so this cannot store another partial bar."""
    res = ingest_yahoo.repair_partials(ctx.store, ctx.http, symbols=ctx.params.get("symbols"), now=ctx.now)
    return {**res, "inserted": sum(int(v.get("rows") or 0) for v in res.get("symbols", {}).values())}


def g_yahoo_curve(ctx: Ctx) -> dict[str, Any]:
    res = ingest_yahoo.fetch_curve(ctx.store, ctx.http, now=ctx.now)
    return {"months": res, "inserted": sum(int(v.get("rows") or 0) for v in res.values())}


def g_intraday_bars(ctx: Ctx) -> dict[str, Any]:
    first = db.scalar(ctx.store, "SELECT COUNT(*) FROM gold_bars_intraday WHERE symbol = 'GC=F'") == 0
    res = ingest_yahoo.fetch_intraday(ctx.store, ctx.http, first_run=first, now=ctx.now)
    return {"legs": res, "inserted": sum(int(v.get("rows") or 0) for v in res.values()), "first_run": first}


def g_cot(ctx: Ctx) -> dict[str, Any]:
    res = ingest_cot.fetch_and_ingest(ctx.store, ctx.http, backfill_from=ctx.backfill_from, now=ctx.now)
    bad = ingest_cot.identity_check(ctx.store)
    return {"datasets": res, "inserted": sum(int(v.get("typed") or 0) for v in res.values()),
            "not_yet": all(v.get("status") == "not_yet" for v in res.values()), "identity_violations": len(bad)}


def _voi_ref_prices(store: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym, keys in (("GC=F", ("GC", "MGC", "1OZ", "QO")), ("SI=F", ("SI", "SIL", "SIC"))):
        v = db.scalar(store, "SELECT close FROM gold_daily_bars WHERE symbol = ? ORDER BY trade_date DESC LIMIT 1", [sym])
        if v is not None:
            for k in keys:
                out[k] = float(v)
    return out


def g_cme_voi(ctx: Ctx) -> dict[str, Any]:
    if ctx.backfill_from:
        return ingest_cme.backfill_daily_volume(ctx.store, ctx.backfill_from, ctx.today_ist, progress=ctx.progress, now=ctx.now,
                                                max_files=ctx.params.get("max_files"))
    body = ftp_fetch(ingest_cme.FTP_VOI_LATEST)
    res = ingest_cme.ingest_daily_volume(ctx.store, body, now=ctx.now)
    return {"inserted": res["rows"], "trade_date": res["trade_date"]}


def g_cme_efrp(ctx: Ctx) -> dict[str, Any]:
    if ctx.backfill_from:
        return ingest_cme.backfill_efrp(ctx.store, ctx.backfill_from, ctx.today_ist, progress=ctx.progress, now=ctx.now,
                                        max_files=ctx.params.get("max_files"))
    body = ftp_fetch(ingest_cme.FTP_EFRP_LATEST)
    res = ingest_cme.ingest_efrp(ctx.store, body.decode("utf-8", "ignore"), now=ctx.now)
    return {"inserted": res["rows"], "process_date": res["process_date"], "gold_round_turns": res["gold_round_turns"]}


def g_cme_calendar(ctx: Ctx) -> dict[str, Any]:
    body = ftp_fetch(ingest_cme.FTP_CALENDAR, timeout_s=240)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=True) as fh:   # iterparse from disk, never the whole tree in RAM
        fh.write(body)
        fh.flush()
        del body
        res = ingest_cme.ingest_product_calendar(ctx.store, fh.name, now=ctx.now)
    ev = _recompile_events(ctx)                     # the COMEX_FND / COMEX_LTD rows exist the moment the calendar does (wave 1c)
    return {"inserted": res["rows"], "as_of": res["as_of"], "events": ev}


def g_cme_prf(ctx: Ctx) -> dict[str, Any]:
    body = ftp_fetch(ingest_cme.FTP_PRF)
    res = ingest_cme.ingest_prf(ctx.store, body, now=ctx.now, ref_prices=_voi_ref_prices(ctx.store))
    ev = _recompile_events(ctx)                     # the PRF is the daily fallback source of FND / LTD (compile_events)
    return {"inserted": res["rows"], "margins": res["margins"], "biz_date": res["biz_date"], "events": ev}


def _recompile_events(ctx: Ctx) -> dict[str, Any]:
    """Re-run the compiled gold calendar after a source of its rows changed; never fails the group that called it."""
    try:
        return ingest_local.ingest_events(ctx.store, now=ctx.now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gold.events.recompile_failed", error=type(exc).__name__)
        return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:160]}", "inserted": 0}


def _fred(group: str) -> Callable[[Ctx], dict[str, Any]]:
    def run(ctx: Ctx) -> dict[str, Any]:
        res = ingest_macro.fetch_fred(ctx.store, ctx.http, group, now=ctx.now)
        return {"series": res, "inserted": _sum(res, "inserted"), "revised": _sum(res, "revised"),
                "failed": [k for k, v in res.items() if v.get("status") != "ok"]}
    return run


def g_calendar_us(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_macro.FF_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    res = ingest_macro.ingest_ff_calendar(ctx.store, resp.text, now=ctx.now)
    ev = ingest_local.ingest_events(ctx.store, now=ctx.now)
    return {"inserted": res["rows"] + ev["inserted"], "us_rows": res["rows"], "compiled_rows": ev["inserted"]}


def g_events(ctx: Ctx) -> dict[str, Any]:
    return ingest_local.ingest_events(ctx.store, now=ctx.now)


def g_gpr(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for url, daily in ((ingest_macro.GPR_DAILY_URL, True), (ingest_macro.GPR_MONTHLY_URL, False)):
        try:
            resp = ctx.http.get(url)
            if resp.status_code != 200:
                out["daily" if daily else "monthly"] = {"status": f"http_{resp.status_code}"}
                continue
            df = ingest_macro.parse_gpr(resp.content, daily=daily, now=ctx.now)
            out["daily" if daily else "monthly"] = {"status": "ok", **ingest_physical.ingest_series(ctx.store, df, now=ctx.now)}
        except Exception as exc:  # noqa: BLE001 — one file never stops the other
            out["daily" if daily else "monthly"] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_worldbank(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_macro.WORLDBANK_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    return ingest_physical.ingest_series(ctx.store, ingest_macro.parse_worldbank_monthly(resp.content, now=ctx.now), now=ctx.now)


def g_atlanta_fed(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_macro.ATLANTA_URL, timeout_s=120)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    since = ctx.backfill_from or ingest_macro.default_since(ctx.store)
    res = ingest_macro.ingest_atlanta_fed(ctx.store, resp.content, since=since, now=ctx.now)
    return {"inserted": res["rows"], "as_of": res["as_of"]}


def g_etf_holdings(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        resp = ctx.http.get(ingest_physical.GLD_URL, timeout_s=60)
        since = ctx.backfill_from or (None if db.scalar(ctx.store, "SELECT COUNT(*) FROM gold_etf_holdings WHERE fund = 'GLD'") == 0
                                      else ctx.today_ist - timedelta(days=30))
        out["GLD"] = ingest_physical.ingest_gld(ctx.store, resp.content, now=ctx.now, since=since) if resp.status_code == 200 \
            else {"status": f"http_{resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        out["GLD"] = {"status": "error", "error": str(exc)[:160]}
    try:
        resp = ctx.http.get(ingest_physical.IAU_URL, timeout_s=60)
        out["IAU"] = ingest_physical.ingest_iau(ctx.store, resp.text, now=ctx.now) if resp.status_code == 200 \
            else {"status": f"http_{resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        out["IAU"] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def _wgc(url: str, parser: Callable[..., pd.DataFrame]) -> Callable[[Ctx], dict[str, Any]]:
    def run(ctx: Ctx) -> dict[str, Any]:
        resp = ctx.http.get(url)
        if resp.status_code != 200:
            return {"status": f"http_{resp.status_code}", "inserted": 0}
        return {"attribution": "World Gold Council (Goldhub), display-only (O-1)",
                **ingest_physical.ingest_series(ctx.store, parser(resp.text, now=ctx.now), now=ctx.now)}
    return run


def g_wgc_etf(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, url, parser in (("flows", ingest_physical.WGC_FLOWS_URL, ingest_physical.parse_wgc_flows),
                             ("holdings", ingest_physical.WGC_HOLDINGS_URL, ingest_physical.parse_wgc_holdings),
                             ("archive", ingest_physical.WGC_ARCHIVE_URL, ingest_physical.parse_wgc_archive)):
        try:
            out[key] = _wgc(url, parser)(ctx)
        except Exception as exc:  # noqa: BLE001
            out[key] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_imf(ctx: Ctx) -> dict[str, Any]:
    start = (ctx.backfill_from or (ctx.today_ist - timedelta(days=200))).strftime("%Y-%m")
    out: dict[str, Any] = {}
    countries = list(catalog_seed.IMF_COUNTRIES)
    ref = _voi_ref_prices(ctx.store).get("GC")          # the latest stored GC close: the ounce ↔ USD consistency reference
    for i in range(0, len(countries), 6):
        batch = countries[i:i + 6]
        url, params = ingest_physical.imf_url(batch, start)
        try:
            resp = ctx.http.get(url, params=params, headers={"Accept": "text/csv"}, timeout_s=60)
            out["+".join(batch)] = ingest_physical.ingest_series(
                ctx.store, ingest_physical.parse_imf_csv(resp.text, now=ctx.now, ref_price=ref), now=ctx.now) \
                if resp.status_code == 200 else {"status": f"http_{resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            out["+".join(batch)] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_sge_daily(ctx: Ctx) -> dict[str, Any]:
    end = ctx.now.replace(tzinfo=ZoneInfo("UTC")).astimezone(SHANGHAI).date()
    start = ctx.backfill_from or (end - timedelta(days=7))
    resp = ctx.http.get(ingest_physical.SGE_DAILY_URL, params={"start_date": start.isoformat(), "end_date": end.isoformat()})
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    return ingest_physical.ingest_sge_daily(ctx.store, resp.text, now=ctx.now)


def g_sge_benchmark(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        resp = ctx.http.get(ingest_physical.SGE_BENCH_HTML_URL)
        out["html"] = ingest_physical.ingest_series(ctx.store, ingest_physical.parse_sge_benchmark_html(resp.text, now=ctx.now), now=ctx.now) \
            if resp.status_code == 200 else {"status": f"http_{resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        out["html"] = {"status": "error", "error": str(exc)[:160]}
    first = db.scalar(ctx.store, "SELECT COUNT(*) FROM gold_series WHERE series_id = 'SGE_SHAU_PM'") == 0
    if first or ctx.backfill_from:
        try:
            resp = ctx.http.get(ingest_physical.SGE_BENCH_JSON_URL)
            out["json"] = ingest_physical.ingest_series(ctx.store, ingest_physical.parse_sge_benchmark_json(resp.text, now=ctx.now,
                                                                                                           since=ctx.backfill_from), now=ctx.now) \
                if resp.status_code == 200 else {"status": f"http_{resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            out["json"] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_sge_quotes(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_physical.SGE_QUOTES_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    df = ingest_physical.parse_sge_quotations(resp.text, now=ctx.now)
    inserted = db.upsert(ctx.store, "gold_bars_intraday", df)
    # self-heal (6 Nov 2026): runs before the trading-day fix stored the night session's padding with future stamps
    future = int(db.scalar(ctx.store, "SELECT COUNT(*) FROM gold_bars_intraday WHERE symbol = 'SGE_AU9999' AND ts > ?", [ctx.now]) or 0)
    if future:
        db.execute(ctx.store, "DELETE FROM gold_bars_intraday WHERE symbol = 'SGE_AU9999' AND ts > ?", [ctx.now])
    return {"inserted": inserted, "purged_future": future}


def g_sge_monthly(ctx: Ctx) -> dict[str, Any]:
    page = ctx.http.get(ingest_physical.SGE_MONTHLY_LIST_URL)
    if page.status_code != 200:
        return {"status": f"http_{page.status_code}", "inserted": 0}
    links = re.findall(r"href=[\"']([^\"']+\.pdf)[\"']", page.text, re.IGNORECASE)
    if not links:
        return {"status": "no_pdf_link", "inserted": 0}
    href = links[0] if links[0].startswith("http") else "https://en.sge.com.cn" + (links[0] if links[0].startswith("/") else "/" + links[0])
    pdf = ctx.http.get(href, timeout_s=60)
    if pdf.status_code != 200:
        return {"status": f"http_{pdf.status_code}", "inserted": 0}
    return ingest_physical.ingest_series(ctx.store, ingest_physical.parse_sge_monthly_pdf(pdf.content, now=ctx.now), now=ctx.now)


def g_shfe(ctx: Ctx) -> dict[str, Any]:
    day = ctx.backfill_from or ctx.now.replace(tzinfo=ZoneInfo("UTC")).astimezone(SHANGHAI).date()
    if day.weekday() >= 5 and not ctx.backfill_from:
        return {"status": "not_trading", "inserted": 0}
    resp = ctx.http.get(ingest_physical.SHFE_KX_URL.format(yyyymmdd=day.strftime("%Y%m%d")), headers={"Referer": "https://www.shfe.com.cn/"})
    if resp.status_code == 404 or "html" in (resp.headers.get("content-type") or "").lower():
        return {"status": "not_trading", "inserted": 0, "day": str(day)}      # non-trading days return a 404 HTML page
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    return ingest_physical.ingest_shfe(ctx.store, resp.text, day, now=ctx.now)


def g_lbma_turnover(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_physical.LBMA_TRADE_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    df = ingest_physical.parse_lbma_turnover(resp.text, now=ctx.now)
    if df.empty:
        return {"status": "no_headline", "inserted": 0, "note": "the 'period ending … Gold: $… bn' headline was not found"}
    periods = sorted({str(d) for d in df["report_date"]})
    return {**ingest_physical.ingest_series(ctx.store, df, now=ctx.now), "page_periods": periods, "latest_period": periods[-1]}


def g_lbma_vault(ctx: Ctx) -> dict[str, Any]:
    page = ctx.http.get(ingest_physical.LBMA_VAULT_PAGE_URL)
    if page.status_code != 200:
        return {"status": f"http_{page.status_code}", "inserted": 0}
    href = ingest_physical.lbma_vault_href(page.text)
    if not href:
        return {"status": "no_xlsx_link", "inserted": 0}
    xlsx = ctx.http.get(href, timeout_s=60)
    if xlsx.status_code != 200:
        return {"status": f"http_{xlsx.status_code}", "inserted": 0}
    return {"file": href.rsplit("/", 1)[-1], **ingest_physical.ingest_series(ctx.store, ingest_physical.parse_lbma_vault_xlsx(xlsx.content, now=ctx.now),
                                                                             now=ctx.now)}


def g_swiss(ctx: Ctx) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=True) as fh:
        size = ctx.http.stream_to_file(ingest_physical.SWISS_ZIP_URL, fh.name)
        df = ingest_physical.parse_swiss_zip(fh.name, now=ctx.now)
    return {"bytes": size, **ingest_physical.ingest_series(ctx.store, df, now=ctx.now)}


def g_wgc_price(ctx: Ctx) -> dict[str, Any]:
    out = _wgc(ingest_physical.WGC_PRICE_URL, ingest_physical.parse_wgc_price)(ctx)
    out["provisional"] = "A9: reference marks until owner decision O-1"
    return out


def g_ibja(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_india.IBJA_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    return ingest_physical.ingest_series(ctx.store, ingest_india.parse_ibja_html(resp.text, now=ctx.now), now=ctx.now)


def _last_friday(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 4) % 7)


def g_rbi_wss(ctx: Ctx) -> dict[str, Any]:
    fridays = [_last_friday(ctx.today_ist)]
    if ctx.backfill_from:
        f = _last_friday(ctx.backfill_from)
        while f < fridays[0]:
            fridays.append(f)
            f += timedelta(days=7)
    out: dict[str, Any] = {}
    for f in sorted(set(fridays)):
        try:
            resp = ctx.http.get(ingest_india.RBI_WSS_URL, params={"SelectedDate": f.strftime("%m/%d/%Y")})
            out[str(f)] = ingest_physical.ingest_series(ctx.store, ingest_india.parse_rbi_wss(resp.text, now=ctx.now), now=ctx.now) \
                if resp.status_code == 200 else {"status": f"http_{resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            out[str(f)] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_inr_ref(ctx: Ctx) -> dict[str, Any]:
    """RBI reference-rate archive: GET the ASP.NET form for its hidden fields, POST the date range (dd/mm/yyyy)."""
    page = ctx.http.get(ingest_india.RBI_REF_URL)
    if page.status_code != 200:
        return {"status": f"http_{page.status_code}", "inserted": 0}
    hidden = dict(re.findall(r'<input[^>]+name="(__[A-Z]+)"[^>]+value="([^"]*)"', page.text))
    start = ctx.backfill_from or (ctx.today_ist - timedelta(days=10))
    form = {**hidden, "txtFromDate": start.strftime("%d/%m/%Y"), "txtToDate": ctx.today_ist.strftime("%d/%m/%Y"), "chkUSD": "on",
            "btnGo": "Go"}
    resp = ctx.http.post(ingest_india.RBI_REF_URL, data=form)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    df = ingest_india.parse_rbi_reference_rate(resp.text, now=ctx.now)
    if df.empty:
        return {"status": "no_rows", "inserted": 0, "note": "form layout to confirm in week one (PLAN j.2 #4)"}
    return ingest_physical.ingest_series(ctx.store, df, now=ctx.now)


def g_mcx_master(ctx: Ctx) -> dict[str, Any]:
    try:                                                           # wave 1d: idempotent, rows before the fix only; never fails the group
        relabel: dict[str, Any] = ingest_india.relabel_band_sessions(ctx.store)
    except Exception as exc:  # noqa: BLE001 — a read-only store: the reads re-key from trade_date anyway
        relabel = {"status": "error", "error": type(exc).__name__}
    return {**ingest_india.fetch_mcx_master(ctx.store, ctx.http, now=ctx.now), "band_session_relabel": relabel}


def g_mcx_close_vwap30(ctx: Ctx) -> dict[str, Any]:
    """The MCX settlement proxy (last-30-minute VWAP of Breeze 1-minute bars) of the latest completed session, or of
    ``params.sessions`` / every session since ``backfill_from``; stored contracts are skipped (zero Breeze calls)."""
    p = ctx.params
    return mcx_close.run(ctx.store, ctx.breeze, now=ctx.now, sessions=p.get("sessions"), backfill_from=ctx.backfill_from,
                         families=p.get("families"), force=ctx.force, max_calls=p.get("max_calls"),
                         backfill_lookback=p.get("backfill_lookback"))


def g_breeze_daily(ctx: Ctx) -> dict[str, Any]:
    """MCX gold futures daily OHLC + volume + OI per LIVE expiry from Breeze (O-8, 6 Nov 2026) into gold_mcx_daily, through
    the latest completed session; a contract with no stored bar gets ``backfill_from`` or 180 days, a stored one its last
    10 sessions. ``params``: families, max_calls (default 15), max_expiries (default 3)."""
    p = ctx.params
    return mcx_daily.run(ctx.store, ctx.breeze, now=ctx.now, backfill_from=ctx.backfill_from, families=p.get("families"),
                         max_calls=p.get("max_calls"), max_expiries=p.get("max_expiries"))


def g_zerodha(ctx: Ctx) -> dict[str, Any]:
    resp = ctx.http.get(ingest_india.ZERODHA_URL)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    return ingest_india.ingest_zerodha(ctx.store, resp.text, now=ctx.now)


def _month_end(d: date) -> date:
    """The last day of ``d``'s month."""
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def amfi_months(today: date, backfill_from: date | None = None) -> list[date]:
    """Month-ends to fetch: the two latest completed months, plus (backfill) EVERY month-end from the month before
    ``backfill_from`` — one step per calendar month, no skipping."""
    first = today.replace(day=1) - timedelta(days=1)
    months = {first, first.replace(day=1) - timedelta(days=1)}
    if backfill_from:
        m = backfill_from.replace(day=1) - timedelta(days=1)
        while m < first:
            months.add(m)
            m = _month_end(m + timedelta(days=1))
    return sorted(months)


def g_amfi(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for me in amfi_months(ctx.today_ist, ctx.backfill_from):
        if db.scalar(ctx.store, "SELECT COUNT(*) FROM gold_series WHERE series_id = 'AMFI_GOLD_ETF_AUM_CR' AND report_date = ?", [me]):
            out[str(me)] = {"status": "have"}
            continue
        try:
            resp = ctx.http.get(ingest_india.amfi_url(me))
            out[str(me)] = ingest_physical.ingest_series(ctx.store, ingest_india.parse_amfi_xls(resp.content, now=ctx.now), now=ctx.now) \
                if resp.status_code == 200 else {"status": f"http_{resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            out[str(me)] = {"status": "error", "error": str(exc)[:160]}
    return {**out, "inserted": _sum(out, "inserted")}


def g_duty(ctx: Ctx) -> dict[str, Any]:
    return ingest_physical.ingest_series(ctx.store, ingest_india.duty_frame(now=ctx.now, extra=derive._env_duty()), now=ctx.now)


def g_manual(ctx: Ctx) -> dict[str, Any]:
    """Hand-typed observations for catalogued series only (F14 India imports and the like)."""
    values = ctx.params.get("values") or []
    cat = {r["series_id"]: r for r in catalog_seed.build_rows()}
    ok = [v for v in values if str(v.get("series_id")) in cat and str(cat[str(v.get("series_id"))]["verdict"]).startswith("PUBLISH")]
    rejected = [v.get("series_id") for v in values if v not in ok]
    df = ingest_india.manual_series_frame(ok, source=str(ctx.params.get("source") or "manual"), now=ctx.now)
    return {**ingest_physical.ingest_series(ctx.store, df, now=ctx.now), "rejected": rejected}


def g_derive_india(ctx: Ctx) -> dict[str, Any]:
    g_duty(ctx)
    return derive.derive_india(ctx.store, now=ctx.now)


def g_derive_global(ctx: Ctx) -> dict[str, Any]:
    return derive.derive_global(ctx.store, now=ctx.now)


def g_brief(ctx: Ctx) -> dict[str, Any]:
    return ingest_local.ingest_briefs(ctx.store, ctx.params.get("folder"), now=ctx.now)


def g_preopen_log(ctx: Ctx) -> dict[str, Any]:
    """Standing sync of data/gold_preopen/log.json → gold_preopen_log (missing days only, FINAL P0-11); the original
    full migration (overwrites, strips inputs_json) only on an explicit ``params.full``."""
    if ctx.params.get("full"):
        return ingest_local.migrate_preopen_log(ctx.store, ctx.params.get("path"), now=ctx.now)
    return ingest_local.sync_preopen_log(ctx.store, ctx.params.get("path"), now=ctx.now)


def g_health(ctx: Ctx) -> dict[str, Any]:
    return ingest_local.fetch_health(ctx.store, ctx.http, now=ctx.now)


def g_catalog(ctx: Ctx) -> dict[str, Any]:
    return {"inserted": catalog_seed.seed(ctx.store)}


def g_monthly_due(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in MONTHLY_SET:
        out[name] = run_group(name, ctx)
    return {"groups": out, "inserted": _sum(out, "inserted")}


def _all_legs_failed(res: dict[str, Any]) -> bool:
    """True when the result has leg sub-dicts and every one of them reports an http_/error status."""
    legs = [v for v in res.values() if isinstance(v, dict) and "status" in v]
    return bool(legs) and all(str(v.get("status", "")).startswith(("http_", "error")) for v in legs)


def _sum(d: dict[str, Any], key: str) -> int:
    n = 0
    for v in d.values():
        if isinstance(v, dict):
            x = v.get(key)
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                n += int(x)
            else:
                n += _sum(v, key)
    return n


# ── registry ────────────────────────────────────────────────────────────────────────────────────────

GROUPS: dict[str, Group] = {g.name: g for g in (
    Group("catalog", g_catalog, "always", note="seed the data dictionary (code, not data)"),
    Group("treasury", g_treasury, "daily", "gold_series", "source = 'treasury_csv'"),
    Group("yahoo_daily", g_yahoo_daily, "daily", "gold_daily_bars", "source = 'yahoo'", note="CODE ONLY in the build; one call per symbol 6 s apart"),
    Group("yahoo_partials", g_yahoo_partials, "always",
          note="re-pull only the symbols whose latest bar is an in-progress session that has since closed; no calls when there are none"),
    Group("yahoo_curve", g_yahoo_curve, "daily", "gold_curve", "exchange = 'COMEX' AND source = 'yahoo'"),
    Group("intraday_bars", g_intraday_bars, "always", note="every 5 min while COMEX trades; 7d/1m (+60d/5m on the first run)"),
    Group("cot", g_cot, "always", note="incremental: report_date > max stored; 0 rows = not yet released"),
    Group("cme_voi", g_cme_voi, "daily", "gold_cme_daily_voi", heavy=True, note="latest file; backfill_from → archive 1 file / 2 s"),
    Group("cme_efrp", g_cme_efrp, "daily", "gold_cme_efrp", heavy=True),
    Group("cme_calendar", g_cme_calendar, "weekly", "gold_cme_calendar", heavy=True, note="38 MB XML, iterparse from a temp file"),
    Group("cme_prf", g_cme_prf, "daily", "gold_cme_prf"),
    Group("fred_daily", _fred("daily"), "daily", "gold_series", "source = 'fred_csv' AND freq = 'D'"),
    Group("fred_weekly", _fred("weekly"), "weekly", "gold_series", "source = 'fred_csv' AND freq = 'W'"),
    Group("fred_monthly", _fred("monthly"), "monthly", "gold_series", "source = 'fred_csv' AND freq = 'M'", publish_day=5),
    Group("calendar_us", g_calendar_us, "always", note="ForexFactory this-week JSON (hourly) + the compiled gold calendar"),
    Group("events", g_events, "always"),
    Group("gpr", g_gpr, "weekly", "gold_series", "source = 'iacoviello_xls'"),
    Group("worldbank", g_worldbank, "monthly", "gold_series", "source = 'worldbank_cmo'", publish_day=5),
    Group("atlanta_fed", g_atlanta_fed, "daily", "gold_fed_path"),
    Group("etf_holdings", g_etf_holdings, "daily", "gold_etf_holdings"),
    Group("wgc_etf", g_wgc_etf, "weekly", "gold_series", "source = 'wgc_fsapi' AND series_id LIKE 'WGC_ETF%'"),
    Group("wgc_premiums", _wgc(ingest_physical.WGC_PREMIUMS_URL, ingest_physical.parse_wgc_premiums), "weekly", "gold_series",
          "series_id LIKE 'WGC_PREMIUM%'"),
    Group("wgc_sd", _wgc(ingest_physical.WGC_SD_URL, ingest_physical.parse_wgc_sd), "monthly", "gold_series", "series_id LIKE 'WGC_SD%'",
          publish_day=1),
    Group("wgc_price", g_wgc_price, "daily", "gold_series", "series_id IN ('LBMA_AM_USD', 'LBMA_PM_USD')"),
    Group("imf_official", g_imf, "monthly", "gold_series", "source = 'imf_irfcl'", publish_day=24),
    Group("sge_daily", g_sge_daily, "daily", "gold_asia_daily", "exchange = 'SGE'"),
    Group("sge_benchmark", g_sge_benchmark, "daily", "gold_series", "series_id LIKE 'SGE_SHAU%'"),
    Group("sge_quotes", g_sge_quotes, "always", note="delayed intraday line, 5-min cadence during SGE hours"),
    Group("sge_monthly", g_sge_monthly, "monthly", "gold_series", "source = 'sge_pdf'", publish_day=10),
    Group("shfe", g_shfe, "daily", "gold_asia_daily", "exchange = 'SHFE'"),
    Group("lbma_turnover", g_lbma_turnover, "weekly", "gold_series", "series_id LIKE 'LBMA_OTC%'"),
    Group("lbma_vault", g_lbma_vault, "monthly", "gold_series", "series_id LIKE 'LBMA_VAULT%'", publish_day=20),
    Group("swiss", g_swiss, "monthly", "gold_series", "series_id = 'SWISS_GOLD_EXPORT_IN_KG'", publish_day=22, heavy=True,
          note="692 MB zip streamed to a temp file; in monthly_due from the 22nd, once per month (E19)"),
    Group("ibja_am", g_ibja, "always", note="both tables are on the page; the job slot names the fix it waits for"),
    Group("ibja_pm", g_ibja, "always"),
    Group("rbi_wss", g_rbi_wss, "weekly", "gold_series", "source = 'rbi_wss'"),
    Group("inr_ref", g_inr_ref, "daily", "gold_series", "series_id = 'USDINR_FBIL'"),
    Group("mcx_master", g_mcx_master, "always", note="conditional GET; a 304 is a no-op"),
    Group("mcx_close_vwap30", g_mcx_close_vwap30, "always",
          note="after the MCX close (≈23:58) and at start-up: last-30-min VWAP of Breeze 1-min bars; stored sessions cost 0 calls"),
    Group("breeze_daily", g_breeze_daily, "always",
          note="09:35 Mon–Fri: Breeze daily OHLC / volume / OI per live MCX gold expiry → gold_mcx_daily; ≤ 15 calls, 1.2 s apart"),
    Group("zerodha_margins", g_zerodha, "daily", "gold_margins", "source = 'zerodha_nrml'"),
    Group("amfi", g_amfi, "monthly", "gold_series", "source = 'amfi_xls'", publish_day=10),
    Group("duty", g_duty, "always"),
    Group("india_imports", g_manual, "always", note="hand-typed PIB number (F14 URL unverified): params.values"),
    Group("manual", g_manual, "always"),
    Group("derive_india", g_derive_india, "always"),
    Group("derive_global", g_derive_global, "always"),
    Group("brief", g_brief, "always"),
    Group("preopen_log", g_preopen_log, "always",
          note="sync data/gold_preopen/log.json → gold_preopen_log (missing days only; params.full = the old migration); "
               "the data-health refresh also runs it so the catalog row never says gap while the log holds the row"),
    Group("health", g_health, "always", note="reads ui-api /api/gold/health"),
    Group("monthly_due", g_monthly_due, "always", note="every monthly group whose due rule says so"),
)}


def resolve(name: str) -> str:
    return ALIASES.get(name, name)


def run_group(name: str, ctx: Ctx) -> dict[str, Any]:
    """One group with failure isolation and the due rule; always returns a dict with ``status``."""
    key = resolve(name)
    if key in DORMANT:
        return {"status": "dormant", "reason": DORMANT[key]}
    g = GROUPS.get(key)
    if g is None:
        return {"status": "unknown", "error": f"no such group: {name}"}
    due, why = is_due(g, ctx)
    if not due:
        return {"status": "skipped", "reason": why}
    t0 = utcnow()
    dated = g.cadence != "always" and g.table is not None
    before = freshness(ctx.store, g) if dated else None
    try:
        res = g.run(ctx) or {}
        status = res.pop("status", "ok")
        if status == "ok" and _all_legs_failed(res):
            status = "degraded"
        if "inserted" in res and any(isinstance(v, dict) and "status" in v for v in res.values()):
            res["inserted_total"] = res.pop("inserted")        # legs carry `inserted`; the aggregate never double counts
        out = {"status": status, **res, "seconds": (utcnow() - t0).total_seconds()}
    except Exception as exc:  # noqa: BLE001 — isolation: one group failing never stops the others
        logger.warning("gold.group.failed", group=key, error=type(exc).__name__)
        out = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}", "seconds": (utcnow() - t0).total_seconds()}
    if dated:
        with contextlib.suppress(Exception):                    # bookkeeping never fails a group (read-only store)
            out["advanced"] = record_run(ctx.store, g, ctx, status=str(out["status"]), before=before)["advanced"]
    return out


_CATALOG_CHECKED: set[int] = set()


def ensure_catalog(store: Any) -> int:
    """Seed the catalog when the stored table lacks a code row (a new id shipped since the last ``catalog`` run — wave 1d,
    C-DATA-17: the three Asia ids existed in code but not in the live table). Once per store per process (a code change
    means a restart); never fails a job."""
    if id(store) in _CATALOG_CHECKED:
        return 0
    _CATALOG_CHECKED.add(id(store))
    try:
        have = {str(r) for r in db.query_df(store, "SELECT series_id FROM gold_series_catalog")["series_id"]}
        if {r["series_id"] for r in catalog_seed.build_rows()} - have:
            return catalog_seed.seed(store)
    except Exception as exc:  # noqa: BLE001 — a read-only store, a missing table
        logger.warning("gold.catalog.ensure_failed", error=type(exc).__name__)
    return 0


def run_job(store: Any, http: Any, job: str, groups: list[str], *, backfill_from: date | None = None, force: bool = False,
            params: dict[str, Any] | None = None, now: datetime | None = None,
            progress: Callable[[int, int], None] | None = None, breeze: Callable[[], Any] | None = None) -> dict[str, Any]:
    """The whole job: every group in order, then a checkpoint; the result carries per-group outcomes (``groups``), the
    freshness of the gold tables (``tables``) and ``rows_total``. Row counts sit in ``inserted`` exactly once per leaf
    (a group with legs reports ``inserted_total``), so a walker that sums every ``inserted`` key is never off."""
    ctx = Ctx(store=store, http=http, now=now or utcnow(), backfill_from=backfill_from, force=force, params=params or {}, progress=progress,
              breeze=breeze)
    out: dict[str, Any] = {}
    if "catalog" not in groups:
        ensure_catalog(store)
    for i, name in enumerate(groups):
        out[name] = run_group(name, ctx)
        if progress:
            progress(i + 1, len(groups))
    with contextlib.suppress(Exception):            # a read-only or test store
        store.checkpoint()
    return {"job": job, "groups": out, "rows_total": _sum(out, "inserted"), "tables": schema.positions_meta(store),
            "backfill_from": backfill_from.isoformat() if backfill_from else None, "ran_at": ctx.now.isoformat()}


def default_http() -> Any:
    from gold.hosts import GoldHttp

    return GoldHttp(timeout_s=float(os.getenv("GOLD_HTTP_TIMEOUT_S", "20")))
