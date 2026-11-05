"""DERV tab (worldclass program W2) + the Terminal v2 IV history API (PLAN 1.1, B3).

Legacy half (W2): proxies the F&O analytics computed by data-service — /db/fo/* (term structure, basis history,
rollover, PCR history, VIX panel), /db/option-history/{symbol} (near-expiry ATM IV / PCR / max-pain, NIFTY +
BANKNIFTY) and the max-pain scalars of /db/option-chain/{symbol}.

Terminal v2 half (PLAN 1.1 "API contract (B3)"): the point-in-time IV store written by data-service's `fo_iv`
package (B1; tables `iv_summary_daily`, `iv_expiry_daily`, `iv_surface_daily`, `iv_event_log`, `iv_intraday`,
`vix_daily`) read through data-service `/db/iv/*` and ONE stale-while-revalidate cache (`SWRCache("derivatives.iv")`,
refresh 60 s, bound 600 s). No publisher is ever on the request path: the only upstream this module names is
data-service, reached through the process-wide client (`shared.http_client.get_json`).

Routes (all GET, all read-only, mounted at /api/derivatives):
  /iv/{symbol}?days=&series=      the daily series the pages chart (+ VIX overlay, events, badges)
  /iv/{symbol}/surface?date=&compare=  per-expiry rows + the smile in log-moneyness (+ the ghost surface)
  /iv/{symbol}/cone               min/25/50/75/max of constant-maturity IV by tenor over 1/3/5 years + today
  /iv/{symbol}/events?n=          the results IV-crush ledger
  /iv/{symbol}/intraday?date=     the 15-minute pilot path (ATM IV, straddle, PCR; source chip)
  /vol-screen?sort=&results_within=  the 224-underlying VOL screener

Honesty rules (PLAN §0): every derived number carries a badge (`arithmetic` for IV / rank / percentile / RV,
`context` for spreads, skew, term, the ledger); rank and percentile are BOTH served, each with its definition; no
composite score; nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price. Daily
data shows its date (`as_of`), never a clock. Errors follow errors.py: fail(status, code, message, hint).
"""
from __future__ import annotations

import math
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from cache import SWRCache, TTLCache, cache_headers, merge_served
from errors import code_for_status, fail
from fastapi import APIRouter, Query, Response

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_SYMBOL = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")

IV_REFRESH_AFTER_S = 60.0
IV_MAX_AGE_S = 600.0
STORE_DOWN_TTL_S = 15.0
STORE = SWRCache("derivatives.iv", max_items=512, refresh_after=IV_REFRESH_AFTER_S, max_age=IV_MAX_AGE_S)
_ttl = TTLCache("derivatives", max_items=64, default_ttl=STORE_DOWN_TTL_S)

BADGE_ARITH, BADGE_CONTEXT, BADGE_HEURISTIC = "arithmetic", "context", "heuristic"
DESCRIBES = "describes, does not predict"
RANK_WINDOW = 252
SERIES = ("iv30_cm", "iv60_cm", "iv90_cm", "monthly", "near")
SCREEN_SORTS = ("iv_pctile", "iv_rank", "iv_minus_rv", "term_slope", "skew")
CONE_YEARS = (1, 3, 5)
CONE_TENORS = ("iv30_cm", "iv60_cm", "iv90_cm")
SESSIONS_PER_YEAR = 250

DEFINITIONS = {
    "iv_rank_252": "IV rank: where today's iv30_cm sits between its 252-session minimum (0) and maximum (100).",
    "iv_pctile_252": "IV percentile: the share of the past 252 sessions whose iv30_cm was below today's.",
    "iv30_cm": "30-day constant-maturity ATM IV: VIX-style variance interpolation between the two bracketing expiries.",
    "skew_25d_30": "25-delta skew: 25Δ put IV minus 25Δ call IV on the 30-day surface (vol points).",
    "term_slope_30_90": "Term slope: iv90_cm minus iv30_cm (vol points).",
    "iv_minus_rv20": "IV minus RV20: iv30_cm minus the 20-session Yang-Zhang realised vol (vol points; the volatility risk premium).",
    "fovolt_ann": "NSE's own EWMA daily volatility (FOVOLT), annualised.",
}

SUMMARY_FIELDS = ("date", "spot", "iv30_cm", "iv60_cm", "iv90_cm", "monthly_atm_iv", "monthly_expiry", "near_atm_iv",
                  "near_expiry", "near_dte", "skew_25d_30", "term_slope_30_90", "iv_rank_252", "iv_pctile_252", "rv20_cc",
                  "rv20_parkinson", "rv20_yz", "fovolt_ann", "iv_minus_rv20", "expected_move_1d_pct", "quality_flags")
EXPIRY_FIELDS = ("expiry", "dte", "forward", "forward_source", "atm_iv", "iv_25d_put", "iv_25d_call", "skew_25d",
                 "iv_10d_put", "iv_10d_call", "n_iv_strikes", "call_oi", "put_oi", "pcr", "expected_move_pct",
                 "quality_flags")
EVENT_FIELDS = ("symbol", "released_at", "expiry", "iv_pre_5d", "iv_pre_1d", "iv_post_1d", "crush_pct",
                "implied_move_pct", "realised_move_pct")
SCREEN_FIELDS = ("symbol", "date", "spot", "iv30_cm", "iv_rank_252", "iv_pctile_252", "rv20_yz", "iv_minus_rv20",
                 "term_slope_30_90", "skew_25d_30", "next_results", "ban", "mwpl_pct")


# ── helpers shared with the legacy routes ────────────────────────────────────────────────────────────────────
def _check_symbol(symbol: str) -> str:
    if not _SYMBOL.fullmatch(symbol):
        fail(422, "invalid", f"Bad symbol {symbol!r}", "NSE underlyings look like NIFTY, RELIANCE, M&M")
    return symbol.upper()


async def _get(path: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict:
    """A data-service read through the process-wide client (one AsyncClient per process, PLAN 1.5)."""
    try:
        body = await get_json(f"{DATA_SVC}{path}", route="read", params=params, timeout=timeout)
    except UpstreamError as exc:
        if exc.status_code == 503:
            fail(503, "upstream_down", f"data-service unreachable: {exc.detail}", "is data-service on :8001 up?")
        fail(exc.status_code, code_for_status(exc.status_code), exc.detail)
    return body if isinstance(body, dict) else {"data": body}


@router.get("/symbols")
async def fo_symbols() -> dict:
    """F&O underlyings on the latest session (indices first) — the DERV symbol picker."""
    return await _get("/db/fo/symbols")


@router.get("/term-structure")
async def term_structure(symbol: str = Query("NIFTY")) -> dict:
    """Per-expiry futures legs with annualized basis vs spot (latest F&O bhavcopy)."""
    return await _get("/db/fo/term-structure", {"symbol": _check_symbol(symbol)})


@router.get("/basis-history")
async def basis_history(symbol: str = Query("NIFTY"), days: int = Query(1250, ge=20, le=2000)) -> dict:
    """Near-month annualized basis history (nse_fo_daily, 2019-10 →)."""
    return await _get("/db/fo/basis-history", {"symbol": _check_symbol(symbol), "days": days})


@router.get("/rollover")
async def rollover(symbol: str = Query("NIFTY"), cycles: int = Query(8, ge=2, le=24)) -> dict:
    """Expiry-week OI migration near→next, final rollover % per expiry, 3-expiry average, carry.
    First call may return updating:true while data-service builds its futures panel (~1 min)."""
    return await _get("/db/fo/rollover", {"symbol": _check_symbol(symbol), "cycles": cycles}, timeout=45.0)


@router.get("/pcr-history")
async def pcr_history(symbol: str = Query("NIFTY"), days: int = Query(1250, ge=20, le=2000)) -> dict:
    """Aggregate put/call OI ratio history (all strikes and expiries, nse_fo_daily)."""
    return await _get("/db/fo/pcr-history", {"symbol": _check_symbol(symbol), "days": days})


@router.get("/vix")
async def vix(days: int = Query(500, ge=60, le=3000)) -> dict:
    """INDIA VIX level, 1y/5y percentile, and VIX vs NIFTY 20-day realized volatility."""
    return await _get("/db/fo/vix", {"days": days})


@router.get("/option-history/{symbol}")
async def option_history(symbol: str, days: int = Query(260, ge=20, le=2000)) -> dict:
    """Daily near-expiry ATM IV, PCR and max pain (NIFTY / BANKNIFTY — data-service's archive). Kept serving until
    the UI switches to /iv/{symbol}; then an alias for one release (PLAN 1.1)."""
    return await _get(f"/db/option-history/{_check_symbol(symbol)}", {"days": days}, timeout=45.0)


_MAX_PAIN_KEYS = ("symbol", "date", "expiry", "expiries", "days_to_expiry", "spot", "future",
                  "atm", "atm_iv", "pcr_oi", "max_pain", "expected_move_pct", "resistance", "support")


@router.get("/max-pain/{symbol}")
async def max_pain(symbol: str, expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Current max pain / chain PCR / OI walls for any F&O underlying — the EOD chain's scalars
    only (the full per-strike chain lives in OMON; this stays a ~300-byte payload)."""
    params: dict[str, Any] = {"expiry": expiry} if expiry else {}
    body = await _get(f"/db/option-chain/{_check_symbol(symbol)}", params)
    return {k: body.get(k) for k in _MAX_PAIN_KEYS}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Terminal v2 — the IV store (PLAN 1.1): store, then show
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class StoreUnavailable(RuntimeError):
    """data-service could not answer (down, tables not deployed = 404, bad body): the block degrades, never the page."""


async def _db_fetch(path: str, params: dict[str, Any]) -> Any:
    try:
        return await get_json(f"{DATA_SVC}{path}", route="read", params=params)
    except UpstreamError as exc:
        if exc.status_code == 404:
            raise StoreUnavailable("data-service has no IV tables yet (404): B1's fo_iv package is not deployed") from exc
        raise StoreUnavailable(f"data-service {exc.status_code}: {exc.detail[:120]}") from exc


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Rows from any of data-service's reply shapes ({rows:[…]}, {data:[…]}, {columns, data}, a bare list)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], list) and isinstance(payload.get("columns"), list):
        cols = payload["columns"]
        return [dict(zip(cols, row, strict=False)) for row in data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


class Reads:
    """What one request read from the store: the Served entries (X-Cache headers) and the per-path errors."""

    def __init__(self) -> None:
        self.served: list[Any] = []
        self.errors: dict[str, str] = {}

    async def get(self, path: str, **params: Any) -> Any | None:
        clean = {k: v for k, v in params.items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
        down = _ttl.get(f"down:{path}")
        if down is not None:
            self.errors[path] = str(down)
            return None
        try:
            served = await STORE.get(key, lambda: _db_fetch(path, clean))
        except StoreUnavailable as exc:
            _ttl.set(f"down:{path}", str(exc), ttl=STORE_DOWN_TTL_S)
            self.errors[path] = str(exc)
            return None
        except Exception as exc:  # noqa: BLE001 — a bad body is a store problem, not a page problem
            self.errors[path] = f"{type(exc).__name__}"
            return None
        self.served.append(served)
        return served.value

    def headers(self, response: Response | None) -> None:
        cache_headers(response, merge_served(self.served))

    def meta(self) -> dict[str, Any]:
        return {"ok": not self.errors, "store_errors": dict(self.errors)}


# ── pure helpers (unit-tested) ───────────────────────────────────────────────────────────────────────────────
def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _d(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    return s[:10] if len(s) >= 10 else None


def _pick(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in fields:
        v = row.get(k)
        if k in ("date", "expiry", "monthly_expiry", "near_expiry", "next_results"):
            out[k] = _d(v)
        elif k in ("quality_flags", "forward_source", "symbol", "released_at", "price_source", "opt_type", "source"):
            out[k] = None if v is None else str(v)
        elif k == "ban":
            out[k] = bool(v) if v is not None else None
        elif isinstance(v, bool):
            out[k] = v
        else:
            out[k] = _f(v) if not isinstance(v, str) or v.replace(".", "", 1).replace("-", "", 1).isdigit() else v
    return out


def iv_rank(values: list[float], window: int = RANK_WINDOW) -> float | None:
    """IV rank over the trailing ``window`` observations (today included): (today − min) / (max − min) × 100."""
    vals = [v for v in values if v is not None][-window:]
    if len(vals) < 2:
        return None
    lo, hi, today = min(vals), max(vals), vals[-1]
    if hi <= lo:
        return None
    return round((today - lo) / (hi - lo) * 100, 1)


def iv_percentile(values: list[float], window: int = RANK_WINDOW) -> float | None:
    """IV percentile over the trailing ``window`` observations: share of PRIOR observations below today × 100."""
    vals = [v for v in values if v is not None][-window:]
    if len(vals) < 2:
        return None
    today, prior = vals[-1], vals[:-1]
    return round(sum(1 for v in prior if v < today) / len(prior) * 100, 1)


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return math.nan
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def iv_cone(rows: list[dict[str, Any]], years: Iterable[int] = CONE_YEARS, tenors: Iterable[str] = CONE_TENORS,
            sessions_per_year: int = SESSIONS_PER_YEAR) -> dict[str, Any]:
    """{years: [{years, tenors: {iv30_cm: {min, p25, p50, p75, max, n}, …}}], today: {tenor: value}} from the
    summary rows (ascending by date). A tenor with no finite value in a window reports n = 0 and nulls."""
    out_years: list[dict[str, Any]] = []
    for y in years:
        window = rows[-y * sessions_per_year:]
        tenor_stats: dict[str, dict[str, Any]] = {}
        for t in tenors:
            vals = sorted(v for v in (_f(r.get(t)) for r in window) if v is not None)
            if not vals:
                tenor_stats[t] = {"min": None, "p25": None, "p50": None, "p75": None, "max": None, "n": 0}
                continue
            tenor_stats[t] = {"min": round(vals[0], 2), "p25": round(_percentile(vals, 0.25), 2),
                              "p50": round(_percentile(vals, 0.5), 2), "p75": round(_percentile(vals, 0.75), 2),
                              "max": round(vals[-1], 2), "n": len(vals)}
        out_years.append({"years": y, "sessions": len(window), "tenors": tenor_stats})
    today = rows[-1] if rows else {}
    return {"years": out_years, "today": {t: _f(today.get(t)) for t in tenors},
            "as_of": _d(today.get("date")) if rows else None}


def summary_rows(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    picked = [_pick(r, SUMMARY_FIELDS) for r in rows if _d(r.get("date"))]
    picked.sort(key=lambda r: r["date"] or "")
    return picked[-days:]


def event_markers(summary: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Chart markers: each results release (kind `results`) and each monthly expiry roll (kind `expiry`), once per date.
    Budget / RBI / US-data markers wait for the owner's clarification (PLAN Appendix C) — never guessed here."""
    marks: dict[tuple[str, str], None] = {}
    for e in events:
        d = _d(e.get("released_at"))
        if d:
            marks[(d, "results")] = None
    prev = None
    for r in summary:
        exp = r.get("monthly_expiry")
        if exp and prev and exp != prev and r["date"]:
            marks[(r["date"], "expiry")] = None
        prev = exp or prev
    return [{"date": d, "kind": k} for d, k in sorted(marks)]


def surface_payload(expiry_rows: list[dict[str, Any]], surface_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-expiry rows (ATM, 25Δ/10Δ, skew, counts, flags) + the smile in log-moneyness for each expiry.
    Untraded strikes (no iv) are counted, never plotted."""
    smiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    untraded: dict[str, int] = defaultdict(int)
    for r in surface_rows:
        exp = _d(r.get("expiry"))
        if not exp:
            continue
        iv, lm = _f(r.get("iv")), _f(r.get("log_moneyness"))
        if iv is None or lm is None:
            untraded[exp] += 1
            continue
        smiles[exp].append({"log_moneyness": round(lm, 5), "strike": _f(r.get("strike")), "opt_type": str(r.get("opt_type") or ""),
                            "iv": round(iv, 3), "delta": _f(r.get("delta")), "oi": _f(r.get("oi"))})
    expiries = []
    for r in sorted(expiry_rows, key=lambda x: _d(x.get("expiry")) or ""):
        exp = _d(r.get("expiry"))
        if not exp:
            continue
        row = _pick(r, EXPIRY_FIELDS)
        row["smile"] = sorted(smiles.get(exp, []), key=lambda p: p["log_moneyness"])
        row["untraded_strikes"] = untraded.get(exp, 0)
        row["near"] = (row.get("dte") or 0) > 2
        expiries.append(row)
    return {"expiries": expiries, "n_expiries": len(expiries)}


def _nearest_strike_pair(rows: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None]:
    """ATM by parity: the strike where |CE mid − PE mid| is smallest (both sides present)."""
    by_strike: dict[float, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        k, t = _f(r.get("strike")), str(r.get("opt_type") or "").upper()
        if k is not None and t in ("CE", "PE") and _f(r.get("mid")) is not None:
            by_strike[k][t] = r
    best: tuple[float, float, dict[str, Any], dict[str, Any]] | None = None
    for k, sides in by_strike.items():
        if "CE" in sides and "PE" in sides:
            gap = abs((_f(sides["CE"]["mid"]) or 0) - (_f(sides["PE"]["mid"]) or 0))
            if best is None or gap < best[0]:
                best = (gap, k, sides["CE"], sides["PE"])
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def intraday_path(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The 15-minute path from `iv_intraday` rows: per snapshot (ts) and NEAR expiry, ATM IV (parity strike, mean of
    both sides), NSE's IV at the same strike when stored, the straddle price and the chain PCR. One source chip per path."""
    by_ts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources: set[str] = set()
    for r in rows:
        ts = str(r.get("ts") or "")
        if ts:
            by_ts[ts].append(r)
            if r.get("source"):
                sources.add(str(r["source"]))
    points: list[dict[str, Any]] = []
    for ts in sorted(by_ts):
        snap = by_ts[ts]
        expiries = sorted({e for e in (_d(r.get("expiry")) for r in snap) if e})
        if not expiries:
            continue
        near = expiries[0]
        near_rows = [r for r in snap if _d(r.get("expiry")) == near]
        k, ce, pe = _nearest_strike_pair(near_rows)
        call_oi = sum(_f(r.get("oi")) or 0 for r in near_rows if str(r.get("opt_type")).upper() == "CE")
        put_oi = sum(_f(r.get("oi")) or 0 for r in near_rows if str(r.get("opt_type")).upper() == "PE")
        atm = nse_atm = straddle = None
        if ce is not None and pe is not None:
            ivs = [v for v in (_f(ce.get("iv")), _f(pe.get("iv"))) if v is not None]
            atm = round(sum(ivs) / len(ivs), 3) if ivs else None
            nse = [v for v in (_f(ce.get("nse_iv")), _f(pe.get("nse_iv"))) if v is not None]
            nse_atm = round(sum(nse) / len(nse), 3) if nse else None
            straddle = round((_f(ce.get("mid")) or 0) + (_f(pe.get("mid")) or 0), 2)
        points.append({"ts": ts, "expiry": near, "atm_strike": k, "atm_iv": atm, "nse_atm_iv": nse_atm,
                       "straddle": straddle, "pcr": round(put_oi / call_oi, 3) if call_oi else None,
                       "n_strikes": len(near_rows)})
    source = "BREEZE" if "breeze" in {s.lower() for s in sources} else ("NSE" if sources else "OFFLINE")
    return {"points": points, "source": source, "sources": sorted(sources), "snapshots": len(points)}


def screen_rows(rows: list[dict[str, Any]], sort: str, results_within: int | None, today: date | None = None) -> list[dict[str, Any]]:
    key = {"iv_pctile": "iv_pctile_252", "iv_rank": "iv_rank_252", "iv_minus_rv": "iv_minus_rv20",
           "term_slope": "term_slope_30_90", "skew": "skew_25d_30"}[sort]
    out = []
    for r in rows:
        row = _pick(r, SCREEN_FIELDS)
        if not row.get("symbol"):
            continue
        if results_within is not None:
            nr = row.get("next_results")
            if not nr:
                continue
            try:
                days = (date.fromisoformat(nr) - (today or date.today())).days  # noqa: DTZ011 — IST session date
            except ValueError:
                continue
            if days < 0 or days > results_within:
                continue
            row["results_in_days"] = days
        out.append(row)
    out.sort(key=lambda r: (r.get(key) is None, -(r.get(key) or 0)))
    return out


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────────────
def _as_of(rows: list[dict[str, Any]]) -> str | None:
    return rows[-1]["date"] if rows else None


@router.get("/iv/{symbol}")
async def iv_history(symbol: str, response: Response, days: int = Query(750, ge=20, le=3000),
                     series: str = Query("iv30_cm", pattern="^(iv30_cm|iv60_cm|iv90_cm|monthly|near)$")) -> dict:
    """The daily IV series for one underlying (PLAN 1.1): constant-maturity 30/60/90, the monthly and near fixed-expiry
    ATM IV, rank AND percentile (each defined), skew, term slope, three realised-vol estimators + FOVOLT, the VIX overlay
    (one source: vix_daily), results / expiry markers. `series` names the line the chart draws first."""
    sym = _check_symbol(symbol)
    reads = Reads()
    summary = _rows(await reads.get("/db/iv/summary", symbol=sym, days=days))
    vix_rows = _rows(await reads.get("/db/iv/vix", days=days)) if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") else []
    events = _rows(await reads.get("/db/iv/events", symbol=sym, n=40))
    rows = summary_rows(summary, days)
    meta = summary[0] if summary else {}
    iv_vals = [_f(r.get("iv30_cm")) for r in rows]
    reads.headers(response)
    return {
        "symbol": sym, "as_of": _as_of(rows), "since": rows[0]["date"] if rows else None, "sessions": len(rows),
        "series": series,
        "model_version": str(meta.get("model_version") or (rows[-1].get("model_version") if rows else None) or "") or None,
        "r_source": str(meta.get("r_source") or "rate_curve (dated constant 6.5 %; O-T5 pending)"),
        "rows": rows,
        "vix": [{"date": _d(v.get("date")), "close": _f(v.get("close"))} for v in vix_rows if _d(v.get("date"))],
        "events": event_markers(rows, events),
        "rank": {"iv_rank_252": iv_rank([v for v in iv_vals if v is not None]),
                 "iv_pctile_252": iv_percentile([v for v in iv_vals if v is not None]),
                 "stored": {"iv_rank_252": rows[-1].get("iv_rank_252") if rows else None,
                            "iv_pctile_252": rows[-1].get("iv_pctile_252") if rows else None},
                 "window_sessions": RANK_WINDOW, "on": "iv30_cm"},
        "definitions": DEFINITIONS,
        "badges": {"iv": BADGE_ARITH, "rank": BADGE_ARITH, "pctile": BADGE_ARITH, "rv": BADGE_ARITH,
                   "spread": BADGE_CONTEXT, "skew": BADGE_CONTEXT, "term": BADGE_CONTEXT, "vix": BADGE_ARITH},
        "note": f"history since {rows[0]['date'] if rows else '—'} from the stored NSE F&O bhavcopies; {DESCRIBES}",
        "precedent": "Bloomberg HIVG / IVOL %ile and rank; Sensibull IV chart; tastytrade IVR",
        **reads.meta(),
    }


@router.get("/iv/{symbol}/surface")
async def iv_surface(symbol: str, response: Response, date_: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
                     compare: str | None = Query(None, pattern="^(1w|1m|3m)$")) -> dict:
    """Per-expiry rows (ATM, 25Δ/10Δ, skew, counts, flags) + the smile in log-moneyness for each expiry on `date`
    (default: the latest stored session); `compare=1m` adds the ghost surface one month earlier."""
    sym = _check_symbol(symbol)
    reads = Reads()
    expiry_rows = _rows(await reads.get("/db/iv/expiry", symbol=sym, date=date_))
    surface_rows = _rows(await reads.get("/db/iv/surface", symbol=sym, date=date_))
    as_of = _d(expiry_rows[0].get("date")) if expiry_rows else date_
    payload = surface_payload(expiry_rows, surface_rows)
    ghost: dict[str, Any] | None = None
    if compare and as_of:
        back = {"1w": 7, "1m": 30, "3m": 91}[compare]
        ghost_date = (date.fromisoformat(as_of) - timedelta(days=back)).isoformat()
        g_exp = _rows(await reads.get("/db/iv/expiry", symbol=sym, date=ghost_date))
        g_surf = _rows(await reads.get("/db/iv/surface", symbol=sym, date=ghost_date))
        ghost = {"requested": ghost_date, "as_of": _d(g_exp[0].get("date")) if g_exp else None, **surface_payload(g_exp, g_surf)}
    reads.headers(response)
    return {"symbol": sym, "as_of": as_of, **payload, "compare": ghost,
            "badges": {"atm_iv": BADGE_ARITH, "skew": BADGE_CONTEXT, "smile": BADGE_ARITH},
            "note": f"T = calendar days / 365 at the 15:30 close; expiry-day and T ≤ 2 d rows kept, excluded from near; {DESCRIBES}",
            "precedent": "Bloomberg OVDV / SKEW; ORATS skew", **reads.meta()}


@router.get("/iv/{symbol}/cone")
async def iv_cone_route(symbol: str, response: Response) -> dict:
    """min / 25 / 50 / 75 / max of constant-maturity IV by tenor over 1 / 3 / 5 years + today's term structure."""
    sym = _check_symbol(symbol)
    reads = Reads()
    summary = summary_rows(_rows(await reads.get("/db/iv/summary", symbol=sym, days=5 * SESSIONS_PER_YEAR + 10)), 5 * SESSIONS_PER_YEAR + 10)
    expiry_rows = _rows(await reads.get("/db/iv/expiry", symbol=sym))
    term = [{"expiry": _d(r.get("expiry")), "dte": _f(r.get("dte")), "atm_iv": _f(r.get("atm_iv"))}
            for r in sorted(expiry_rows, key=lambda x: _d(x.get("expiry")) or "") if _d(r.get("expiry"))]
    reads.headers(response)
    return {"symbol": sym, **iv_cone(summary), "term_today": term, "badge": BADGE_CONTEXT,
            "note": f"percentiles of stored constant-maturity ATM IV; {DESCRIBES}", "precedent": "Opstra IV cone; Bloomberg GV cone",
            **reads.meta()}


@router.get("/iv/{symbol}/events")
async def iv_events(symbol: str, response: Response, n: int = Query(8, ge=1, le=40)) -> dict:
    """The results IV-crush ledger: the last n releases — IV before / after, crush %, implied vs realised move."""
    sym = _check_symbol(symbol)
    reads = Reads()
    rows = [_pick(r, EVENT_FIELDS) for r in _rows(await reads.get("/db/iv/events", symbol=sym, n=n))]
    rows.sort(key=lambda r: r.get("released_at") or "", reverse=True)
    reads.headers(response)
    return {"symbol": sym, "rows": rows[:n], "n": len(rows[:n]), "badge": BADGE_CONTEXT,
            "note": f"a measured ledger of past releases; {DESCRIBES}", "precedent": "ORATS / Market Chameleon earnings",
            **reads.meta()}


@router.get("/iv/{symbol}/intraday")
async def iv_intraday(symbol: str, response: Response, date_: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Today's (or `date`'s) 15-minute path from the Breeze chain pilot: ATM IV, NSE's IV beside ours, straddle, PCR.
    `source` is the chip: BREEZE / NSE / OFFLINE (no snapshot stored)."""
    sym = _check_symbol(symbol)
    reads = Reads()
    rows = _rows(await reads.get("/db/iv/intraday", symbol=sym, date=date_))
    path = intraday_path(rows)
    reads.headers(response)
    return {"symbol": sym, "date": date_ or (path["points"][0]["ts"][:10] if path["points"] else None), **path,
            "badge": BADGE_CONTEXT, "note": f"15-minute pilot through the Breeze budget ledger (O-T6); {DESCRIBES}",
            "precedent": "Quantsapp IV live; Bloomberg OMON intraday", **reads.meta()}


@router.get("/vol-screen")
async def vol_screen(response: Response, sort: str = Query("iv_pctile", pattern="^(iv_pctile|iv_rank|iv_minus_rv|term_slope|skew)$"),
                     results_within: int | None = Query(None, ge=0, le=60)) -> dict:
    """The VOL screener: every underlying's latest iv30_cm, rank, percentile, RV20 (YZ), IV − RV, term slope, skew,
    next results date, ban flag and % of MWPL; sortable; `results_within=N` keeps names reporting inside N days."""
    reads = Reads()
    payload = await reads.get("/db/iv/screen")
    rows = screen_rows(_rows(payload), sort, results_within)
    as_of = (payload or {}).get("date") if isinstance(payload, dict) else None
    reads.headers(response)
    return {"as_of": _d(as_of) or (rows[0].get("date") if rows else None), "sort": sort, "results_within": results_within,
            "rows": rows, "n": len(rows), "definitions": DEFINITIONS,
            "badges": {"iv30_cm": BADGE_ARITH, "iv_rank_252": BADGE_ARITH, "iv_pctile_252": BADGE_ARITH, "rv20_yz": BADGE_ARITH,
                       "iv_minus_rv20": BADGE_CONTEXT, "term_slope_30_90": BADGE_CONTEXT, "skew_25d_30": BADGE_CONTEXT,
                       "mwpl_pct": BADGE_CONTEXT},
            "note": f"a screen, not a signal; {DESCRIBES}", "precedent": "Bloomberg GV / WVOL; Quantsapp IV percentile",
            **reads.meta()}
