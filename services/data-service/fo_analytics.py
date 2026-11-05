"""
F&O analytics for the DERV tab (worldclass program W2): futures term structure, basis
history, rollover tracking, PCR history and the INDIA VIX panel. GET-only, read-only.

Data-grain honesty (what each number can and cannot be):
- `nse_fo_daily` (2019-10 →) holds ONE row per underlying per day: the NEAR expiry's close
  plus OI summed across ALL expiries. So the 5-year basis history is near-month basis, and
  the PCR history is the all-expiry aggregate OI ratio (the OMON chain PCR is near-expiry —
  a different, noisier number; both are labeled in the payloads).
- Per-contract rows live only in the cached UDiFF F&O bhavcopies (2024-07-08 →, under
  data/nse_archive/fo/). Term structure (near/next/far) and the near→next OI split behind
  the rollover tracker come from a derived futures panel (derived/fo_futures_panel.csv.gz)
  built incrementally in a background thread — same pattern as option_history.json.
- `market_index_daily` stores NIFTY50 + INDIAVIX closes only → index basis HISTORY is
  NIFTY-only; BANKNIFTY still gets term structure + rollover (spot comes from the file).

Mounted by main.py with:  import fo_analytics; app.include_router(fo_analytics.router)
`main` is imported lazily inside handlers (main mounts this module, so a top-level import
would be circular). Pure math and SQL helpers take plain args so tests run without the app.
"""
from __future__ import annotations

import threading
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

import option_chain as oc
from shared.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["fo-analytics"])

SYMBOL_RE = r"^[A-Za-z0-9&\-]{1,20}$"
FUTURE_TYPES = ("IDF", "STF")              # index futures, stock futures (UDiFF)
PANEL_COLS = ["date", "symbol", "expiry", "close", "spot", "oi"]
_FUT_USECOLS = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "ClsPric", "SttlmPric",
                "UndrlygPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol"]


# ── pure math (unit-tested in services/ui-api/tests/test_derivatives.py) ────────────────

def ann_basis_pct(fut: Optional[float], spot: Optional[float], dte: Optional[int]) -> Optional[float]:
    """Annualized basis % = (fut/spot − 1) × 365/dte × 100. None when inputs are missing or
    dte < 2 (expiry-session annualization is division-by-noise)."""
    if fut is None or spot is None or not spot or dte is None or dte < 2:
        return None
    return round((fut / spot - 1.0) * 365.0 / dte * 100.0, 2)


def basis_pct(fut: Optional[float], spot: Optional[float]) -> Optional[float]:
    if fut is None or spot is None or not spot:
        return None
    return round((fut / spot - 1.0) * 100.0, 3)


def pcr(put_oi: Optional[float], call_oi: Optional[float]) -> Optional[float]:
    """Put/call OI ratio; None when call OI is zero/missing (a ratio over 0 is not 'bullish')."""
    if put_oi is None or call_oi is None or call_oi <= 0:
        return None
    return round(put_oi / call_oi, 2)


def rollover_pct(near_oi: float, next_oi: float, far_oi: float = 0.0) -> Optional[float]:
    """% of futures OI already sitting beyond the dying series: (next+far)/total × 100."""
    total = near_oi + next_oi + far_oi
    if total <= 0:
        return None
    return round((next_oi + far_oi) / total * 100.0, 1)


def percentile_of_last(values: list[float], window: int) -> Optional[float]:
    """Percentile rank (0–100) of the last value within its trailing `window` values."""
    xs = [v for v in values if v is not None][-window:]
    if len(xs) < 20:
        return None
    last = xs[-1]
    return round(100.0 * sum(1 for v in xs if v <= last) / len(xs), 1)


def realized_vol_series(closes: pd.Series, window: int = 20) -> pd.Series:
    """Rolling annualized realized volatility %, from log returns (√252)."""
    import numpy as np
    r = np.log(closes / closes.shift(1))
    return r.rolling(window).std() * (252.0 ** 0.5) * 100.0


def term_legs(fut: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-expiry futures legs for one underlying on one session, nearest first.
    `fut` columns: TradDt, XpryDt, ClsPric, SttlmPric, UndrlygPric, OpnIntrst,
    ChngInOpnIntrst, TtlTradgVol (one row per expiry)."""
    legs: list[dict[str, Any]] = []
    labels = ["near", "next", "far"]
    for rank, (_, r) in enumerate(fut.sort_values("XpryDt").iterrows()):
        trade_day = pd.Timestamp(r["TradDt"]).date()
        expiry = pd.Timestamp(r["XpryDt"]).date()
        dte = (expiry - trade_day).days
        spot = float(r["UndrlygPric"]) if pd.notna(r["UndrlygPric"]) else None
        close = float(r["ClsPric"]) if pd.notna(r["ClsPric"]) else None
        legs.append({
            "rank": rank, "label": labels[rank] if rank < 3 else f"#{rank + 1}",
            "expiry": expiry.isoformat(), "dte": dte, "close": close,
            "settle": float(r["SttlmPric"]) if pd.notna(r["SttlmPric"]) else None,
            "basis_pct": basis_pct(close, spot), "basis_ann_pct": ann_basis_pct(close, spot, dte),
            "oi": float(r["OpnIntrst"]) if pd.notna(r["OpnIntrst"]) else None,
            "oi_chg": float(r["ChngInOpnIntrst"]) if pd.notna(r["ChngInOpnIntrst"]) else None,
            "volume": float(r["TtlTradgVol"]) if pd.notna(r["TtlTradgVol"]) else None,
        })
    return legs


def rollover_view(panel: pd.DataFrame, symbol: str, cycles: int = 8) -> dict[str, Any]:
    """Rollover analytics for one underlying from the futures panel (date, expiry, close, spot, oi).

    A cycle is the run of sessions sharing a near expiry E; its last session is expiry day
    (date == E). Final rollover % at each past expiry, the current cycle's daily curve, and
    the average prior curve by days-to-expiry for the 'vs 3-expiry average' comparison."""
    sdf = panel[panel["symbol"] == symbol]
    if sdf.empty:
        return {"symbol": symbol, "current": None, "curve_now": [], "curve_avg": [],
                "history": [], "avg3": None}
    rows: list[dict[str, Any]] = []
    for d, g in sdf.groupby("date"):
        g = g.sort_values("expiry")
        ois = g["oi"].fillna(0).tolist()
        near_oi = float(ois[0])
        next_oi = float(ois[1]) if len(ois) > 1 else 0.0
        far_oi = float(sum(ois[2:])) if len(ois) > 2 else 0.0
        near_exp, spot = g["expiry"].iloc[0], g["spot"].iloc[0]
        dte = (pd.Timestamp(near_exp).date() - pd.Timestamp(d).date()).days
        row: dict[str, Any] = {
            "date": pd.Timestamp(d).date().isoformat(), "near_expiry": pd.Timestamp(near_exp).date().isoformat(),
            "dte": dte, "roll_pct": rollover_pct(near_oi, next_oi, far_oi),
            "near_oi": near_oi, "next_oi": next_oi, "far_oi": far_oi,
        }
        if len(g) > 1:                                   # cost of carry into the next series
            nxt = g.iloc[1]
            dte_next = (pd.Timestamp(nxt["expiry"]).date() - pd.Timestamp(d).date()).days
            spot_f = float(spot) if pd.notna(spot) else None
            close_n = float(nxt["close"]) if pd.notna(nxt["close"]) else None
            row["carry_next_ann_pct"] = ann_basis_pct(close_n, spot_f, dte_next)
        else:
            row["carry_next_ann_pct"] = None
        rows.append(row)
    rows.sort(key=lambda r: r["date"])
    history = [{"expiry": r["near_expiry"], "date": r["date"], "roll_pct": r["roll_pct"],
                "carry_next_ann_pct": r["carry_next_ann_pct"]}
               for r in rows if r["date"] == r["near_expiry"] and r["roll_pct"] is not None]
    history = history[-cycles:]
    current_exp = rows[-1]["near_expiry"]
    curve_now = [r for r in rows if r["near_expiry"] == current_exp]
    completed = [e["expiry"] for e in history if e["expiry"] != current_exp]
    prior = [r for r in rows if r["near_expiry"] in set(completed[-cycles:]) and r["roll_pct"] is not None]
    curve_avg: list[dict[str, Any]] = []
    if prior:
        by_dte = pd.DataFrame(prior).groupby("dte")["roll_pct"].mean().round(1)
        curve_avg = [{"dte": int(k), "roll_pct": float(v)} for k, v in by_dte.items() if int(k) <= 32]
    final3 = [h["roll_pct"] for h in history if h["expiry"] != current_exp][-3:]
    return {"symbol": symbol, "current": rows[-1], "curve_now": curve_now[-25:], "curve_avg": curve_avg,
            "history": history, "avg3": round(sum(final3) / len(final3), 1) if final3 else None}


# ── SQL helpers (take a raw DuckDB connection; handlers wrap with the store lock) ───────

def q_symbols(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT symbol, kind FROM nse_fo_daily WHERE date = (SELECT MAX(date) FROM nse_fo_daily) "
        "ORDER BY kind != 'index', symbol").fetchall()
    return [{"symbol": s, "kind": k} for s, k in rows]


def q_basis_history(conn, symbol: str, days: int) -> tuple[list[dict[str, Any]], str]:
    """Near-month basis history: nse_fo_daily fut_close vs spot. Spot = market_index_daily
    NIFTY50 for NIFTY, else the EQ-series nse_bhavcopy close. ('' , reason) when no spot."""
    if symbol == "NIFTY":
        spot_sql, spot_args, source = (
            "SELECT date, close AS spot FROM market_index_daily WHERE symbol = 'NIFTY50'", [],
            "market_index_daily:NIFTY50")
    else:
        spot_sql, spot_args, source = (
            "SELECT date, close AS spot FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ'", [symbol],
            "nse_bhavcopy:EQ")
    rows = conn.execute(
        f"""
        WITH spot AS ({spot_sql})
        SELECT f.date, s.spot, f.fut_close, (f.near_expiry - f.date) AS dte
        FROM nse_fo_daily f JOIN spot s USING (date)
        WHERE f.symbol = ? AND f.fut_close IS NOT NULL AND s.spot > 0
        ORDER BY f.date DESC LIMIT ?
        """, [*spot_args, symbol, days]).fetchall()
    out = [{"date": d.isoformat(), "spot": float(sp), "fut": float(fc), "dte": int(dte),
            "basis_pct": basis_pct(float(fc), float(sp)),
            "basis_ann_pct": ann_basis_pct(float(fc), float(sp), int(dte))}
           for d, sp, fc, dte in reversed(rows)]
    return out, source


def q_pcr_history(conn, symbol: str, days: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date, call_oi, put_oi, fut_oi FROM nse_fo_daily
        WHERE symbol = ? AND (call_oi > 0 OR put_oi > 0)
        ORDER BY date DESC LIMIT ?
        """, [symbol, days]).fetchall()
    return [{"date": d.isoformat(),
             "call_oi": float(c) if c is not None else None,
             "put_oi": float(p) if p is not None else None,
             "pcr": pcr(float(p) if p is not None else None, float(c) if c is not None else None),
             "fut_oi": float(f) if f is not None else None}
            for d, c, p, f in reversed(rows)]


def q_vix(conn, days: int) -> dict[str, Any]:
    df = conn.execute(
        """
        SELECT v.date, v.close AS vix, n.close AS nifty
        FROM market_index_daily v LEFT JOIN market_index_daily n
          ON n.date = v.date AND n.symbol = 'NIFTY50'
        WHERE v.symbol = 'INDIAVIX' ORDER BY v.date
        """).df()
    if df.empty:
        return {"rows": [], "count": 0}
    df["rv20"] = realized_vol_series(df["nifty"])
    vix = df["vix"].tolist()
    last, prev = float(vix[-1]), (float(vix[-2]) if len(vix) > 1 else None)
    rv = df["rv20"].iloc[-1]
    rv = round(float(rv), 2) if pd.notna(rv) else None
    tail = df.tail(days)
    rows = [{"date": d.isoformat(), "vix": round(float(v), 2),
             "nifty": round(float(n), 2) if pd.notna(n) else None,
             "rv20": round(float(r), 2) if pd.notna(r) else None}
            for d, v, n, r in zip(tail["date"], tail["vix"], tail["nifty"], tail["rv20"])]
    return {"as_of": df["date"].iloc[-1].isoformat(), "level": round(last, 2),
            "chg_1d": round(last - prev, 2) if prev is not None else None,
            "pctile_1y": percentile_of_last(vix, 252), "pctile_5y": percentile_of_last(vix, 1250),
            "rv20": rv, "spread": round(last - rv, 2) if rv is not None else None,
            "rows": rows, "count": len(rows)}


# ── UDiFF file access + the derived futures panel ───────────────────────────────────────

def read_fut_rows(path: str) -> pd.DataFrame:
    """FUT rows (all underlyings, per expiry) of one UDiFF F&O bhavcopy — ~650 rows, ~0.05 s."""
    with zipfile.ZipFile(path) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), usecols=_FUT_USECOLS, low_memory=False)
    df = df[df["FinInstrmTp"].isin(FUTURE_TYPES)].copy()
    df["TradDt"] = pd.to_datetime(df["TradDt"])
    df["XpryDt"] = pd.to_datetime(df["XpryDt"])
    return df


_latest_cache: dict[str, Any] = {"key": None, "df": None}
_PANEL: dict[str, Any] = {"df": None, "through": None, "running": False, "error": None}
_PANEL_LOCK = threading.Lock()


def _latest_fut(root: Path) -> tuple[date, pd.DataFrame]:
    fs = oc.files(root)
    if not fs:
        raise HTTPException(status_code=404, detail="No F&O bhavcopy cached (run the EOD pipeline)")
    day, path = fs[-1]
    if _latest_cache["key"] != str(path):
        _latest_cache.update(key=str(path), df=read_fut_rows(str(path)))
    return day, _latest_cache["df"]


def _panel_file(data_dir: Path) -> Path:
    return data_dir / "nse_archive" / "derived" / "fo_futures_panel.csv.gz"


def build_panel(root: Path, cache: Path, through: Optional[str] = None,
                base: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Append FUT rows of every cached UDiFF bhavcopy newer than `through` to the panel and
    write it atomically. Full build ≈ 560 files × 0.05 s; a day later it costs one file."""
    frames: list[pd.DataFrame] = [base] if base is not None and not base.empty else []
    for day, path in oc.files(root):
        if through and day.isoformat() <= through:
            continue
        try:
            f = read_fut_rows(str(path))
        except Exception:  # noqa: BLE001 — one corrupt file must not kill the panel
            logger.warning("fo panel: unreadable file skipped", file=str(path))
            continue
        frames.append(pd.DataFrame({
            "date": f["TradDt"].dt.date.astype(str), "symbol": f["TckrSymb"],
            "expiry": f["XpryDt"].dt.date.astype(str), "close": f["ClsPric"],
            "spot": f["UndrlygPric"], "oi": f["OpnIntrst"]}))
    if not frames:
        return base if base is not None else pd.DataFrame(columns=PANEL_COLS)
    panel = pd.concat(frames, ignore_index=True)[PANEL_COLS].sort_values(["date", "symbol", "expiry"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp.gz")
    panel.to_csv(tmp, index=False, compression="gzip")
    tmp.replace(cache)
    return panel


def _ensure_panel(root: Path, data_dir: Path) -> tuple[pd.DataFrame, bool]:
    """(panel, updating). Loads the cached panel, and kicks a background (re)build when the
    newest cached bhavcopy is not in it yet. Never blocks the request on a build."""
    cache = _panel_file(data_dir)
    with _PANEL_LOCK:
        if _PANEL["df"] is None and cache.is_file():
            try:
                df = pd.read_csv(cache)
                _PANEL.update(df=df, through=str(df["date"].max()) if not df.empty else None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fo panel: cache unreadable, rebuilding", error=str(exc))
        panel = _PANEL["df"] if _PANEL["df"] is not None else pd.DataFrame(columns=PANEL_COLS)
        through = _PANEL["through"]
    fs = oc.files(root)
    latest = fs[-1][0].isoformat() if fs else None
    stale = latest is not None and (through is None or through < latest)
    claimed = False
    if stale:
        with _PANEL_LOCK:                      # C2 E2: check-and-set raced outside the lock —
            if not _PANEL["running"]:          # two builders shared one tmp (corrupt panel,
                _PANEL["running"] = True       # self-healing but wrong). Claim atomically.
                claimed = True
    if claimed:

        def _run() -> None:
            try:
                built = build_panel(root, cache, through, panel if not panel.empty else None)
                with _PANEL_LOCK:
                    _PANEL.update(df=built, through=str(built["date"].max()) if not built.empty else None, error=None)
            except Exception as exc:  # noqa: BLE001
                _PANEL["error"] = str(exc)[:300]
                logger.warning("fo panel build failed", error=str(exc))
            finally:
                _PANEL["running"] = False

        threading.Thread(target=_run, name="fo-panel", daemon=True).start()
    return panel, stale or _PANEL["running"]


# ── endpoints (sync def → FastAPI threadpool; DuckDB work never blocks the loop) ────────

def _ctx():
    """data-service app context, imported lazily (main.py mounts this router)."""
    import main
    return main.get_store(), main._data_dir(main.get_settings())


@router.get("/db/fo/symbols")
def fo_symbols() -> dict:
    """F&O underlyings on the latest session (indices first) — the DERV symbol picker."""
    store, _ = _ctx()
    with store.reader() as con:
        rows = q_symbols(con)
    return {"rows": rows, "count": len(rows)}


@router.get("/db/fo/term-structure")
def fo_term_structure(symbol: str = Query("NIFTY", pattern=SYMBOL_RE)) -> dict:
    """Futures term structure from the latest cached F&O bhavcopy: every live expiry's close,
    OI and annualized basis vs the exchange's underlying price. Works for any F&O underlying."""
    _, data_dir = _ctx()
    day, fut = _latest_fut(data_dir / "nse_archive" / "fo")
    sym = symbol.upper()
    mine = fut[fut["TckrSymb"] == sym]
    if mine.empty:
        raise HTTPException(status_code=404, detail=f"{sym} had no futures on {day.isoformat()} (F&O underlyings only)")
    legs = term_legs(mine)
    spot = float(mine["UndrlygPric"].dropna().iloc[0]) if mine["UndrlygPric"].notna().any() else None
    return {"symbol": sym, "as_of": day.isoformat(), "spot": spot, "legs": legs,
            "fut_oi_total": float(mine["OpnIntrst"].fillna(0).sum()),
            "source": "NSE F&O bhavcopy (UDiFF), OI in shares"}


@router.get("/db/fo/basis-history")
def fo_basis_history(symbol: str = Query("NIFTY", pattern=SYMBOL_RE),
                     days: int = Query(1250, ge=20, le=2000)) -> dict:
    """Near-month basis history (annualized %) from nse_fo_daily (2019-10 →). NIFTY uses the
    NIFTY50 index close as spot; stocks use the EQ bhavcopy close. BANKNIFTY has no stored
    spot history → 404 with that exact reason (its term structure still works)."""
    store, _ = _ctx()
    sym = symbol.upper()
    with store.reader() as con:
        rows, source = q_basis_history(con, sym, days)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No basis history for {sym}: no spot series stored "
                            "(market_index_daily holds NIFTY50 only; stocks need EQ bhavcopy rows)")
    return {"symbol": sym, "spot_source": source, "rows": rows, "count": len(rows),
            "note": "near-month futures close vs spot; annualized over calendar days to expiry (dte ≥ 2)"}


@router.get("/db/fo/rollover")
def fo_rollover(symbol: str = Query("NIFTY", pattern=SYMBOL_RE),
                cycles: int = Query(8, ge=2, le=24)) -> dict:
    """Rollover tracker from the derived futures panel (UDiFF era, Jul-2024 →): current cycle's
    near→next OI migration, final rollover % at each past expiry, 3-expiry average, and the
    cost of carry into the next series. First call kicks a background build (~1 min)."""
    _, data_dir = _ctx()
    sym = symbol.upper()
    panel, updating = _ensure_panel(data_dir / "nse_archive" / "fo", data_dir)
    view = rollover_view(panel, sym, cycles) if not panel.empty else {
        "symbol": sym, "current": None, "curve_now": [], "curve_avg": [], "history": [], "avg3": None}
    built_through = _PANEL["through"]
    if view["current"] is None and not updating and built_through:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the futures panel (F&O underlyings only)")
    return {**view, "updating": updating, "built_through": built_through, "error": _PANEL["error"],
            "note": "rollover % = OI beyond the dying series ÷ total futures OI (shares); UDiFF era only (Jul-2024 →)"}


@router.get("/db/fo/pcr-history")
def fo_pcr_history(symbol: str = Query("NIFTY", pattern=SYMBOL_RE),
                   days: int = Query(1250, ge=20, le=2000)) -> dict:
    """Aggregate put/call OI ratio history from nse_fo_daily (ALL strikes and expiries, 2019-10 →).
    The OMON chain PCR is near-expiry only — a different number; both are labeled."""
    store, _ = _ctx()
    sym = symbol.upper()
    with store.reader() as con:
        rows = q_pcr_history(con, sym, days)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No option OI history for {sym}")
    return {"symbol": sym, "rows": rows, "count": len(rows),
            "note": "all-expiry aggregate OI ratio; the OMON chain shows near-expiry PCR"}


@router.get("/db/fo/vix")
def fo_vix(days: int = Query(500, ge=60, le=3000)) -> dict:
    """INDIA VIX panel: level, 1y/5y percentile, and VIX vs NIFTY 20-day realized volatility
    (annualized, √252) from market_index_daily."""
    store, _ = _ctx()
    with store.reader() as con:
        out = q_vix(con, days)
    if not out.get("rows"):
        raise HTTPException(status_code=404, detail="No INDIAVIX history in market_index_daily")
    return out
