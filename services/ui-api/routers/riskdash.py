"""RSK — portfolio risk dashboard (worldclass program W5).

GET /api/risk/dashboard   VaR/ES (hist-sim), beta & risk decomposition, sector
                          concentration vs the 40% rule, honest historical stress
                          replays, drawdown ladder vs the −20% HARD / −2% daily rules.

Book = the Decision Desk paper positions (routers/desk status — the same ledger the
DESK tab shows) merged with the broker's last-known holdings (data/last_holdings.json,
written by routers/positions; its `as_of` is surfaced — this endpoint never calls
Breeze, so a stale file is shown as stale, not refreshed). `?symbols=A,B` instead
prices an equal-weight WHAT-IF basket at the book's NAV, for pre-trade checks.

Data: per-ticker history over data-service HTTP only (never DuckDB directly):
  GET :8001/ohlcv/{t}?start=…              adjusted closes → VaR/beta panel
  GET :8001/db/security/{t}/history?days=…  bhavcopy, split-adjusted change_pct →
                                            stress windows (reaches 2020; yfinance
                                            ohlcv starts 2020-09 and misses COVID)
  GET :8001/db/index-daily?symbol=NIFTY50   beta benchmark + scenario context

All handlers are sync `def`s (FastAPI threadpool) and the N-ticker fan-out runs in a
bounded ThreadPoolExecutor — the event loop is never touched. Math: risk_math.py
(pure, tested in tests/test_risk_math.py). Trading rules are READ here, never changed.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
import pandas as pd
from fastapi import APIRouter, Query

# shared/ lives at the repo root locally and is bind-mounted at /app/shared in Docker
for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import risk_math as rm  # noqa: E402
from cache import TTLCache  # noqa: E402
from errors import degraded, fail  # noqa: E402

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
_TIMEOUT = httpx.Timeout(20.0)
_FANOUT_WORKERS = 8
_MAX_SYMBOLS = 40                      # the Desk caps at 20 names; 40 covers both books merged
_BETA_WINDOW = 250
_MIN_OBS = 60

# Honest historical replays (close-to-close): each holding's ACTUAL window return.
_SCENARIOS: list[dict[str, Any]] = [
    {"id": "covid_2020", "label": "COVID crash", "start": date(2020, 2, 20), "end": date(2020, 3, 23)},
    {"id": "election_2024", "label": "Election result shock day", "start": date(2024, 6, 3), "end": date(2024, 6, 4)},
    {"id": "rate_shock_2022", "label": "2022 rate shock (H1)", "start": date(2022, 1, 1), "end": date(2022, 6, 30)},
]
_STRESS_FROM = date(2019, 12, 1)       # bhavcopy fetch must reach the COVID base close

_cache = TTLCache("riskdash", max_items=8, default_ttl=120.0)


# ── Book assembly ──────────────────────────────────────────────────────────────────

def _industries() -> dict[str, str]:
    try:
        from shared.momentum import industries
        return industries()
    except Exception:  # noqa: BLE001 — reference list optional
        return {}


def _desk_book(notes: list[str]) -> dict[str, Any]:
    """Decision Desk paper book from the same ledger the DESK tab's status endpoint reads."""
    try:
        from routers.desk import get_desk
        return get_desk().status()
    except Exception as exc:  # noqa: BLE001 — risk page must still render the broker sleeve
        notes.append(f"Decision Desk ledger unavailable: {exc}")
        return {}


def _broker_book(notes: list[str]) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Last-known broker holdings (file written by routers/positions). Never calls Breeze."""
    try:
        from routers.positions import _last_holdings_path
        raw = json.loads(_last_holdings_path().read_text())
        return list(raw.get("positions") or []), raw.get("as_of")
    except (OSError, ValueError) as exc:
        notes.append(f"broker holdings file unreadable: {exc}")
        return [], None


def _merge_books(desk: dict[str, Any], broker_rows: list[dict[str, Any]],
                 sector_of: dict[str, str], notes: list[str]) -> list[dict[str, Any]]:
    """One line per symbol across both books: qty, entry value, current value (desk marks;
    broker lines are re-priced from fetched history later), sector, sources."""
    lines: dict[str, dict[str, Any]] = {}

    def add(sym: str, qty: float, value: Optional[float], invested: float, source: str, sector: str) -> None:
        row = lines.setdefault(sym, {"symbol": sym, "qty": 0.0, "value": 0.0, "invested": 0.0,
                                     "sector": sector, "sources": [], "needs_pricing": False})
        row["qty"] += qty
        row["invested"] += invested
        if value is None:
            row["needs_pricing"] = True
        else:
            row["value"] += value
        row["sources"].append(source)

    for p in desk.get("positions") or []:
        invested = float(p["qty"]) * float(p["avg_cost"] or 0.0)
        add(str(p["symbol"]), float(p["qty"]), p.get("value"), invested, "desk",
            str(p.get("sector") or sector_of.get(str(p["symbol"]), "Unknown")))
    for b in broker_rows:
        sym = str(b.get("symbol") or "").strip()
        qty = float(b.get("quantity") or 0.0)
        if not sym or qty <= 0:
            continue
        invested = float(b.get("invested") or qty * float(b.get("buy_price") or 0.0))
        add(sym, qty, None, invested, "broker", sector_of.get(sym, "Unknown"))

    rows = list(lines.values())
    if len(rows) > _MAX_SYMBOLS:
        rows = sorted(rows, key=lambda r: -(r["value"] or r["invested"]))[:_MAX_SYMBOLS]
        notes.append(f"book truncated to the {_MAX_SYMBOLS} largest lines for the risk fan-out")
    return rows


# ── data-service fetches (called from worker threads only) ─────────────────────────

def _fetch_ohlcv_returns(client: httpx.Client, sym: str, start: date) -> pd.Series:
    r = client.get(f"{DATA_SVC}/ohlcv/{sym}", params={"start": start.isoformat()})
    r.raise_for_status()
    rows = r.json().get("data") or []
    closes = {row["date"]: (row.get("adjusted_close") or row.get("close")) for row in rows}
    s = pd.Series(closes, dtype=float)
    s.index = pd.to_datetime(s.index)
    return rm.daily_returns(s)


def _fetch_bhavcopy_returns(client: httpx.Client, sym: str, days: int) -> pd.Series:
    """Split-adjusted daily returns from the NSE bhavcopy (reaches 2020, unlike ohlcv)."""
    r = client.get(f"{DATA_SVC}/db/security/{sym}/history", params={"days": days})
    r.raise_for_status()
    rows = r.json().get("rows") or []          # newest first; change_pct is on adjusted closes
    pairs = {row["date"]: row["change_pct"] / 100.0 for row in rows if row.get("change_pct") is not None}
    s = pd.Series(pairs, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _fetch_symbol(sym: str, panel_start: date, stress_days: int) -> dict[str, Any]:
    """Both histories for one holding; failures are reported per leg, never raised."""
    out: dict[str, Any] = {"symbol": sym, "panel": None, "stress": None,
                           "panel_err": None, "stress_err": None, "last_close_ret_date": None}
    with httpx.Client(timeout=_TIMEOUT) as client:
        try:
            out["panel"] = _fetch_ohlcv_returns(client, sym, panel_start)
        except httpx.HTTPStatusError as exc:
            out["panel_err"] = f"ohlcv {exc.response.status_code}"
        except httpx.HTTPError as exc:
            out["panel_err"] = f"data-service unreachable: {type(exc).__name__}"
        try:
            out["stress"] = _fetch_bhavcopy_returns(client, sym, stress_days)
        except httpx.HTTPStatusError as exc:
            out["stress_err"] = f"bhavcopy history {exc.response.status_code}"
        except httpx.HTTPError as exc:
            out["stress_err"] = f"data-service unreachable: {type(exc).__name__}"
    # ohlcv missing (new listing / non-yfinance name) → the bhavcopy series also serves the panel
    if out["panel"] is None and out["stress"] is not None and len(out["stress"]):
        out["panel"] = out["stress"]
        out["panel_err"] = None if out["panel"] is not None else out["panel_err"]
        out["panel_src"] = "bhavcopy"
    else:
        out["panel_src"] = "ohlcv"
    return out


def _fetch_last_close(client: httpx.Client, sym: str) -> Optional[float]:
    """Latest raw close (bhavcopy) to price broker lines that carry no mark."""
    try:
        r = client.get(f"{DATA_SVC}/db/security/{sym}/history", params={"days": 10})
        r.raise_for_status()
        rows = r.json().get("rows") or []
        return float(rows[0]["close"]) if rows else None
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None


def _fetch_nifty_returns() -> tuple[pd.Series, Optional[str]]:
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(f"{DATA_SVC}/db/index-daily", params={"symbol": "NIFTY50", "days": 6000})
            r.raise_for_status()
            rows = r.json().get("rows") or []
        s = pd.Series({row["date"]: row["close"] for row in rows}, dtype=float)
        s.index = pd.to_datetime(s.index)
        return rm.daily_returns(s), None
    except httpx.HTTPError as exc:
        return pd.Series(dtype=float), f"NIFTY series unavailable: {type(exc).__name__}"


# ── The dashboard ──────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def risk_dashboard(
    symbols: str = Query("", max_length=800, description="comma-separated WHAT-IF basket (equal weight at book NAV); empty = the live book"),
    lookback: int = Query(750, ge=100, le=1500, description="hist-sim lookback in sessions"),
    refresh: bool = Query(False, description="bypass the 120 s cache"),
) -> dict[str, Any]:
    """Full RSK payload. Sync handler: runs in FastAPI's threadpool; per-ticker history
    is fanned out on a bounded executor so the event loop is never blocked."""
    key = f"{symbols.strip().upper()}|{lookback}"
    if not refresh:
        hit = _cache.get(key)
        if hit is not None:
            return hit
    out = _build_dashboard(symbols, lookback)
    _cache.set(key, out)
    return out


def _build_dashboard(symbols: str, lookback: int) -> dict[str, Any]:
    notes: list[str] = []
    sector_of = _industries()
    desk = _desk_book(notes)
    broker_rows, broker_as_of = _broker_book(notes)

    meta = desk.get("meta") or {}
    cfg = meta.get("config") or {}
    nav_rows = desk.get("nav") or []
    desk_nav = float((desk.get("latest") or {}).get("nav") or meta.get("cash") or 0.0)
    stopped = bool(meta.get("stopped"))
    sector_cap_pct = float(cfg.get("sector_cap", 0.40)) * 100.0

    what_if = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if what_if:
        notional = desk_nav if desk_nav > 0 else 500_000.0
        per = notional / len(what_if)
        holdings = [{"symbol": s, "qty": None, "value": per, "invested": per,
                     "sector": sector_of.get(s, "Unknown"), "sources": ["what-if"], "needs_pricing": False}
                    for s in dict.fromkeys(what_if)][:_MAX_SYMBOLS]
        notes.append(f"WHAT-IF basket: {len(holdings)} names, equal weight on ₹{notional:,.0f} "
                     "(the live book is untouched; the drawdown ladder below is still the real book)")
        mode = "what_if"
    else:
        holdings = _merge_books(desk, broker_rows, sector_of, notes)
        mode = "book"

    if not holdings and not nav_rows:
        fail(503, "state", "No book to measure: the Desk ledger is empty and there are no broker holdings",
             hint="Open the DESK tab (paper book) or pass ?symbols=A,B for a what-if basket")

    # ── fan-out: per-ticker history off the event loop, bounded ────────────────────
    panel_start = date.today() - timedelta(days=int(lookback * 1.6) + 30)
    stress_days = min(3700, (date.today() - _STRESS_FROM).days)
    fetched: dict[str, dict[str, Any]] = {}
    if holdings:
        with ThreadPoolExecutor(max_workers=_FANOUT_WORKERS, thread_name_prefix="riskdash") as ex:
            for res in ex.map(lambda h: _fetch_symbol(h["symbol"], panel_start, stress_days), holdings):
                fetched[res["symbol"]] = res
    nifty_rets, nifty_err = _fetch_nifty_returns()
    if nifty_err:
        notes.append(nifty_err)

    # ── price broker lines that carry no mark (file has qty+cost only) ─────────────
    needs = [h for h in holdings if h.get("needs_pricing")]
    if needs:
        with httpx.Client(timeout=_TIMEOUT) as client:
            for h in needs:
                px = _fetch_last_close(client, h["symbol"])
                if px is not None and h.get("qty"):
                    h["value"] = (h.get("value") or 0.0) + px * h["qty"]
                    h["priced"] = "last close"
                else:
                    h["value"] = (h.get("value") or 0.0) + h["invested"]
                    h["priced"] = "at cost (no price history)"
                    notes.append(f"{h['symbol']}: broker line valued at cost — no price history")

    equity_value = sum(float(h["value"] or 0.0) for h in holdings)
    broker_equity = sum(float(h["value"] or 0.0) for h in holdings if "broker" in h.get("sources", []))
    book_nav = desk_nav + broker_equity if mode == "book" else (desk_nav if desk_nav > 0 else equity_value)
    weights = {h["symbol"]: float(h["value"] or 0.0) for h in holdings}

    # ── VaR / ES (hist-sim) ────────────────────────────────────────────────────────
    rets_by_symbol = {s: f["panel"] for s, f in fetched.items() if f["panel"] is not None}
    panel, panel_excluded = rm.build_panel(rets_by_symbol, lookback, _MIN_OBS)
    for s, f in fetched.items():
        if f["panel"] is None and s not in panel_excluded:
            panel_excluded[s] = f["panel_err"] or "no history"
    port_rets = rm.portfolio_returns(panel, weights)
    var95, es95 = rm.hist_var_es(port_rets, 0.95)
    var99, es99 = rm.hist_var_es(port_rets, 0.99)
    covered_w = sum(weights.get(s, 0.0) for s in panel.columns)
    var_coverage_pct = covered_w / equity_value * 100.0 if equity_value else 0.0

    def inr(x: Optional[float]) -> Optional[float]:
        return None if x is None else round(x * equity_value, 0)

    def pct_of_book(x: Optional[float]) -> Optional[float]:
        return None if x is None or book_nav <= 0 else round(x * equity_value / book_nav * 100.0, 2)

    var_block: dict[str, Any] = {
        "lookback_sessions": lookback,
        "sessions_used": int(len(port_rets)),
        "from": str(port_rets.index.min().date()) if len(port_rets) else None,
        "to": str(port_rets.index.max().date()) if len(port_rets) else None,
        "var95_1d_pct": None if var95 is None else round(var95 * 100, 2),
        "var99_1d_pct": None if var99 is None else round(var99 * 100, 2),
        "es95_1d_pct": None if es95 is None else round(es95 * 100, 2),
        "es99_1d_pct": None if es99 is None else round(es99 * 100, 2),
        "var95_1d_inr": inr(var95), "var99_1d_inr": inr(var99),
        "es95_1d_inr": inr(es95), "es99_1d_inr": inr(es99),
        "var95_5d_pct": None if var95 is None else round(rm.sqrt_horizon(var95, 5) * 100, 2),
        "var99_5d_pct": None if var99 is None else round(rm.sqrt_horizon(var99, 5) * 100, 2),
        "var95_5d_inr": inr(rm.sqrt_horizon(var95, 5)), "var99_5d_inr": inr(rm.sqrt_horizon(var99, 5)),
        "pct_of_book": {"var95_1d": pct_of_book(var95), "var99_1d": pct_of_book(var99),
                        "var95_5d": pct_of_book(rm.sqrt_horizon(var95, 5)),
                        "var99_5d": pct_of_book(rm.sqrt_horizon(var99, 5))},
        "coverage_value_pct": round(var_coverage_pct, 1),
        "excluded": [{"symbol": s, "reason": r} for s, r in sorted(panel_excluded.items())],
        "histogram": rm.histogram(port_rets, bins=31),
        "policy": [
            f"historical simulation on the last {len(port_rets)} sessions of portfolio returns at current weights",
            "VaR at level a = the ceil((1−a)·n)-th worst day (no interpolation); ES = mean of those days",
            "5-day numbers are 1-day × √5 — an i.i.d. APPROXIMATION, not a resimulation",
            "a symbol's missing session counts as a 0.0 return (price carried); thin histories are excluded, not guessed",
        ],
    }

    # ── beta & decomposition ───────────────────────────────────────────────────────
    portfolio_beta = rm.beta(port_rets.tail(_BETA_WINDOW), nifty_rets, _MIN_OBS) if len(nifty_rets) else None
    sigma_p, contribs = rm.risk_contributions(panel, weights)
    holdings_out = []
    for h in sorted(holdings, key=lambda x: -(x["value"] or 0.0)):
        s = h["symbol"]
        f = fetched.get(s, {})
        srets = f.get("panel")
        b = rm.beta(srets.tail(_BETA_WINDOW), nifty_rets, _MIN_OBS) if srets is not None and len(nifty_rets) else None
        holdings_out.append({
            "symbol": s,
            "sources": h.get("sources", []),
            "sector": h.get("sector", "Unknown"),
            "qty": h.get("qty"),
            "value_inr": round(float(h["value"] or 0.0), 0),
            "weight_pct": round(float(h["value"] or 0.0) / equity_value * 100.0, 1) if equity_value else None,
            "beta": None if b is None else round(b, 2),
            "risk_contrib_pct": (round(contribs[s] / sigma_p * 100.0, 1) if sigma_p > 0 and s in contribs else None),
            "in_var_panel": s in panel.columns,
            "note": h.get("priced") or ("" if s in panel.columns else panel_excluded.get(s, "")),
        })

    # ── sector concentration vs the 40% rule ───────────────────────────────────────
    sector_rows = rm.sector_concentration(
        [{"symbol": h["symbol"], "value": h["value"], "sector": h["sector"]} for h in holdings],
        cap_pct=sector_cap_pct)
    # C2 LOW: "Unknown" is unclassified, not an industry — it must not trip the 40% cap chip.
    max_count_pct = max((r["count_pct"] for r in sector_rows if r["sector"] != "Unknown"), default=None)

    # ── stress replays (honest history) ────────────────────────────────────────────
    stress_rets = {s: f["stress"] for s, f in fetched.items() if f["stress"] is not None}
    values = {h["symbol"]: float(h["value"] or 0.0) for h in holdings}
    stress_out = []
    for sc in _SCENARIOS:
        res = rm.stress_scenario(stress_rets, values, sc["start"], sc["end"])
        for e in res["excluded"]:          # a fetch failure is more specific than "no history covering…"
            err = (fetched.get(e["symbol"]) or {}).get("stress_err")
            if err:
                e["reason"] = err
        nifty_window = rm.window_return(nifty_rets, sc["start"], sc["end"]) if len(nifty_rets) else None
        stress_out.append({
            "id": sc["id"], "label": sc["label"],
            "start": sc["start"].isoformat(), "end": sc["end"].isoformat(),
            "nifty_pct": None if nifty_window is None else round(nifty_window * 100, 1),
            "portfolio_pct": None if res["portfolio_pct"] is None else round(res["portfolio_pct"], 1),
            "pnl_inr": round(res["pnl_inr"], 0),
            "covered_value_pct": round(res["covered_value_pct"], 0),
            "worst": res["worst"],
            "excluded": res["excluded"],
        })

    # ── drawdown ladder vs the HARD rules (read-only; CLAUDE.md Trading Rules) ─────
    if nav_rows:
        ladder = rm.drawdown_ladder([r["nav"] for r in nav_rows], peak=meta.get("peak"))
        ladder_src = "Desk paper ledger (EOD NAV marks)"
        today_basis = "last two EOD marks — intraday halt distance needs live marks"
    else:
        invested = sum(float(h.get("invested") or 0.0) for h in holdings)
        ladder = rm.drawdown_ladder([invested, equity_value] if invested > 0 else [])
        ladder_src = "holdings entry values (no NAV history): drawdown measured from cost"
        today_basis = "entry→now, not a daily mark"
    ladder.update({
        "source": ladder_src, "today_basis": today_basis, "stopped": stopped,
        "points": [{"date": str(r["date"])[:10], "drawdown_pct": round(float(r.get("drawdown") or 0.0) * 100, 2)}
                   for r in nav_rows[-250:]],
        "rules": [
            "Max drawdown −20% from peak → sell everything at the next open; manual re-enable (HARD)",
            "Daily loss limit −2% → halt trading for the day (HARD)",
            "Max 15% of portfolio per stock · max 40% of positions per NSE industry",
        ],
    })

    severity = {
        "var": rm.severity_var(var_block["pct_of_book"]["var95_1d"]),
        "beta": rm.severity_beta(portfolio_beta),
        "sector": rm.severity_sector(max_count_pct, sector_cap_pct),
        "dd": rm.severity_dd(ladder.get("drawdown_pct"), stopped),
        "thresholds": rm.THRESHOLDS_DOC,
    }

    broker_stale_h = None
    if broker_as_of:
        try:
            as_of = datetime.fromisoformat(broker_as_of)
            if as_of.tzinfo is not None:          # critique E8: aware − naive raised an uncaught TypeError
                as_of = as_of.astimezone().replace(tzinfo=None)
            broker_stale_h = round((datetime.now() - as_of).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    payload: dict[str, Any] = {
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "book": {
            "nav_inr": round(book_nav, 0),
            "equity_value_inr": round(equity_value, 0),
            "desk_nav_inr": round(desk_nav, 0),
            "desk_cash_inr": round(float(meta.get("cash") or 0.0), 0),
            "desk_positions": len(desk.get("positions") or []),
            "broker_positions": len(broker_rows),
            "broker_equity_inr": round(broker_equity, 0),
            "broker_as_of": broker_as_of,
            "broker_stale_hours": broker_stale_h,
            "stopped": stopped,
            "paper": True,
        },
        "holdings": holdings_out,
        "var": var_block,
        "beta": {"portfolio": None if portfolio_beta is None else round(portfolio_beta, 2),
                 "index": "NIFTY50", "window_sessions": _BETA_WINDOW,
                 "method": "cov/var of daily returns on common sessions",
                 "portfolio_sigma_1d_pct": round(sigma_p * 100, 2) if sigma_p else None},
        "sectors": {"cap_pct": sector_cap_pct,
                    "rule": "max 40% of POSITIONS per NSE industry (Desk rule — CLAUDE.md Trading Rules)",
                    "rows": [{**r, "value_inr": round(r["value_inr"], 0), "value_pct": round(r["value_pct"], 1),
                              "count_pct": round(r["count_pct"], 1)} for r in sector_rows]},
        "stress": stress_out,
        "ladder": ladder,
        "severity": severity,
        "notes": notes,
    }
    if not holdings:
        return degraded(payload, "state", "The book is all cash — nothing at market risk today",
                        hint="The drawdown ladder still tracks the ledger; pass ?symbols=A,B for a what-if basket")
    if equity_value > 0 and var95 is None:
        return degraded(payload, "degraded", "VaR could not be computed (per-ticker history unavailable)",
                        hint="data-service :8001 must be up; see var.excluded for per-symbol reasons")
    return payload
