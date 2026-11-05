#!/usr/bin/env python
"""
News-scanner track record: what happened to every stock the scanner picked (new_scnner/*.json).

For each pick (scans are written after the NSE close, so nothing could be bought on the scan day):
  entry      open of the first NSE session after the scan date
  pre_move   close before the news date → close on the scan date (how much was priced in already)
  r1 … r10   entry open → close 1, 3, 5, 10 sessions later; r_to_date → latest close
  peak/worst best high and worst low since entry
  excess     the same window minus the average NSE stock of similar liquidity (60-session median
             turnover quintile) on the same dates — "did it beat a random similar stock?"
Prices: NSE bhavcopy (official, split-adjusted); Yahoo daily for BSE-only / SME names.
Costs: shared/trading_costs round trip on ₹25,000 per position.

Two weeks of scans in one market regime cannot prove an edge; this is a running track record.

Price source: the shared 19:20 evening snapshot, opened read-only, when it is fresh (SURYA_SNAPSHOT_PATH injected
by master-controller at spawn time, else the pointer file); otherwise a private copy of the live DuckDB. Either
way the panel is loaded from the connection and the connection is closed (the 15–23 Oct 2026 nightly runs
returned the snapshot's connection itself as the "panel" and crashed every evening, P6).

    python scripts/news_scan_performance.py [--out reports/news_scanner]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "ui-api"))

from routers.news_scanner import _normalise_pick, _scan_files, load_scan_file

from shared.nse_panel import load_panel
from shared.trading_costs import default_model

SCAN_DIR = ROOT / "new_scnner"
LIVE_DB = ROOT / "data" / "market.duckdb"
SNAPSHOT_POINTER = ROOT / "data" / ".evening_snapshot.json"
SNAPSHOT_MAX_AGE_S = 24 * 3600
HORIZONS = (1, 3, 5, 10)
POSITION_RS = 25_000
THEMES = [  # first match wins; categories are free text written by the scanner
    ("Orders & tenders", r"order|tender|\bl1\b|contract|bid"),
    ("Capacity & capex", r"capex|capacity|commission|plant|expansion|backward"),
    ("Trade & regulation", r"dgtr|dump|duty|regulat|sebi|policy|approval|licen|import"),
    ("Institutional & insider", r"institution|promoter|\bpit\b|stake|overhang|block|insider|pe "),
    ("Corporate action", r"demerger|buyback|merger|acqui|value unlock|open offer|delist"),
    ("Growth & results", r"growth|business update|results|guidance|margin|q[1-4]"),
    ("Credit & rating", r"credit|rating|debt"),
    ("Macro spillover", r"macro|hormuz|global|crude|commodity|spillover"),
]


def theme(category: str | None) -> str:
    c = (category or "").lower()
    return next((name for name, pat in THEMES if re.search(pat, c)), "Other")


# ── data ────────────────────────────────────────────────────────────────────────

def load_picks() -> pd.DataFrame:
    rows = []
    for ymd, path in sorted(_scan_files(SCAN_DIR)):
        raw = load_scan_file(path)
        for p in raw["picks"]:
            n = _normalise_pick(p)
            sym = n["symbol"] or {}
            rows.append({
                "scan_date": pd.Timestamp(str(p.get("scan_date") or ymd)[:10]),
                "news_date": pd.to_datetime(str(p.get("news_date") or "")[:10], errors="coerce"),
                "symbol": sym.get("base"), "yahoo": sym.get("yahoo"), "exchange": sym.get("exchange"),
                "company": n["company_name"], "conviction": n["conviction_score"],
                "category": n["catalyst_category"], "theme": theme(n["catalyst_category"]),
                "news": (n["news_text"] or "")[:240],
            })
    df = pd.DataFrame(rows)
    df["news_date"] = df["news_date"].fillna(df["scan_date"])
    return df


def snapshot_path() -> Path | None:
    """The shared evening snapshot when it is fresh (< 24 h): SURYA_SNAPSHOT_PATH (master-controller injects it at
    spawn time, Bloomberg F2.3/A7), else the pointer file. None means: use a private copy of the live DB."""
    try:
        sp = Path(os.getenv("SURYA_SNAPSHOT_PATH") or json.loads(SNAPSHOT_POINTER.read_text())["path"])
        if sp.is_file() and time.time() - sp.stat().st_mtime < SNAPSHOT_MAX_AGE_S:
            return sp
    except (OSError, ValueError, KeyError, TypeError):
        pass                                        # no pointer / unreadable pointer: private copy
    return None


def load_prices(start: str) -> dict:
    """The adjusted NSE panel from `start` (shared.nse_panel.load_panel) plus panel["other"] (SME/InvIT series).

    Reuses the shared 19:20 evening snapshot, opened READ-ONLY, instead of a private 4.4 GB copy when it is fresh.
    The panel is always loaded from the connection and the connection closed: returning the snapshot's connection
    itself (as the Bloomberg F2.3 ops hook did) crashed every nightly run from 15 Oct (P6). A snapshot that cannot be read
    falls back to the private copy."""
    snap = snapshot_path()
    if snap is not None:
        try:
            con = duckdb.connect(str(snap), read_only=True)
            try:
                return _panel_from(con, start)
            finally:
                con.close()
        except (duckdb.Error, OSError) as exc:
            print(f"evening snapshot {snap.name} unreadable ({type(exc).__name__}: {exc}); using a private copy",
                  file=sys.stderr)
    tmp = Path(tempfile.mkdtemp(prefix="newsperf_"))
    copy = tmp / "s.duckdb"
    try:
        shutil.copy2(LIVE_DB, copy)
        if Path(f"{LIVE_DB}.wal").exists():
            shutil.copy2(f"{LIVE_DB}.wal", f"{copy}.wal")
        con = duckdb.connect(str(copy))
        try:
            return _panel_from(con, start)
        finally:
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _panel_from(con: duckdb.DuckDBPyConnection, start: str) -> dict:
    panel = load_panel(con, start=start)
    # SME (SM/ST) and InvIT (IV) listings are outside the equity panel; raw prices are fine
    # over a few weeks. One row per symbol-day, SM preferred over ST.
    other = con.execute("""
        SELECT date, symbol, open, high, low, close, turnover_lacs FROM nse_bhavcopy
        WHERE date >= ?::DATE AND series IN ('SM', 'ST', 'IV')
        QUALIFY row_number() OVER (PARTITION BY symbol, date ORDER BY series) = 1""", [start]).df()
    other["date"] = pd.to_datetime(other["date"])
    sessions = panel["close"].index
    panel["other"] = {k: other.pivot(index="date", columns="symbol", values=v).reindex(sessions)
                      for k, v in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "close"),
                                   ("turnover_cr", "turnover_lacs"))}
    panel["other"]["turnover_cr"] = panel["other"]["turnover_cr"] / 100.0
    return panel


def yahoo_daily(symbol: str, sessions: pd.DatetimeIndex) -> dict[str, pd.Series] | None:
    """Daily OHLC + turnover from Yahoo, on NSE session dates (for BSE-only / SME names)."""
    for sym in (symbol, symbol[:-3] + ".BO" if symbol.endswith(".NS") else None):
        if not sym:
            continue
        try:
            r = httpx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                          params={"range": "6mo", "interval": "1d"}, timeout=15,
                          headers={"User-Agent": "Mozilla/5.0 (SuryaDhana-NewsTrackRecord)"})
            res = (r.json().get("chart") or {}).get("result") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            res = None
        if not res:
            continue
        q = res[0]["indicators"]["quote"][0]
        idx = pd.to_datetime(res[0]["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").normalize().tz_localize(None)
        df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")}, index=idx).dropna(subset=["close"])
        df = df[~df.index.duplicated(keep="last")].reindex(sessions)
        return {**{k: df[k] for k in ("open", "high", "low", "close")},
                "turnover_cr": df["close"] * df["volume"] / 1e7, "source": sym}
    return None


_LEGAL = re.compile(r"\b(limited|ltd|the|india|company|co|corporation|corp)\b|[^a-z0-9 ]")


def _name_key(name: str) -> str:
    return " ".join(_LEGAL.sub(" ", str(name).split("(")[0].lower()).split())


def nse_names() -> dict[str, str]:
    ref = pd.read_csv(ROOT / "data" / "reference" / "nse_equity_list.csv")
    ref.columns = [c.strip() for c in ref.columns]
    return {_name_key(n): s.strip() for s, n in zip(ref["SYMBOL"], ref["NAME OF COMPANY"])}


def yahoo_search(company: str) -> str | None:
    """Best Indian listing for a company name (BSE-only and SME names)."""
    try:
        r = httpx.get("https://query2.finance.yahoo.com/v1/finance/search",
                      params={"q": str(company).split("(")[0].strip(), "quotesCount": 6, "newsCount": 0},
                      headers={"User-Agent": "Mozilla/5.0 (SuryaDhana-NewsTrackRecord)"}, timeout=15)
        quotes = r.json().get("quotes", []) if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None
    hits = [q["symbol"] for q in quotes if str(q.get("symbol", "")).endswith((".NS", ".BO"))]
    return next((s for s in hits if s.endswith(".NS")), hits[0] if hits else None)


def resolve(picks: pd.DataFrame, panel: dict) -> pd.DataFrame:
    """Map each pick to an NSE panel symbol, else a Yahoo symbol. The scanner's tickers are
    sometimes BSE scrip codes, old symbols (HEG → HEGAM) or guesses (KAJARIA → KAJARIACER)."""
    c = panel["close"]
    names = nse_names()
    out = picks.copy()
    nse, ysym, how = [], [], []
    for p in picks.itertuples(index=False):
        e = int(c.index.searchsorted(p.scan_date, side="right"))
        live = lambda s, e=e: s in c.columns and c[s].iloc[max(0, e - 5):e + 2].notna().any()
        by_name = names.get(_name_key(p.company))
        if p.symbol and live(p.symbol):
            nse.append(p.symbol); ysym.append(None); how.append("ticker")
        elif by_name and live(by_name):
            nse.append(by_name); ysym.append(None); how.append("company name → NSE")
        elif p.symbol in panel["other"]["close"].columns or (by_name or "") in panel["other"]["close"].columns:
            sym = p.symbol if p.symbol in panel["other"]["close"].columns else by_name
            nse.append(f"other:{sym}"); ysym.append(None); how.append("NSE SME / InvIT series")
        elif p.yahoo and yahoo_daily(p.yahoo, c.index):
            nse.append(None); ysym.append(p.yahoo); how.append("ticker (Yahoo)")
        else:
            found = yahoo_search(p.company)
            nse.append(None); ysym.append(found); how.append("Yahoo search" if found else "unresolved")
    out["nse_symbol"], out["yahoo_symbol"], out["resolved_by"] = nse, ysym, how
    return out


# ── measurement ─────────────────────────────────────────────────────────────────

def measure(picks: pd.DataFrame, panel: dict) -> pd.DataFrame:
    c, o, h, lo = panel["close"], panel["open"], panel["high"], panel["low"]
    sessions = c.index
    last = len(sessions) - 1
    med_to = panel["turnover_cr"].rolling(60, min_periods=20).median()
    universe = panel["series"].eq("EQ") & (c >= 10) & med_to.notna()
    quint = med_to.where(universe).rank(axis=1, pct=True).mul(5).clip(upper=4.999).floordiv(1)

    def bench(entry_i: int, exit_i: int, q: float) -> float:
        """Mean return of same-liquidity NSE stocks from the entry open to the exit close."""
        rr = c.iloc[exit_i] / o.iloc[entry_i] - 1
        members = quint.iloc[entry_i] == q
        return float(rr.where(members & rr.notna()).mean())

    def bench_close(a: int, b: int, q: float) -> float:
        rr = c.iloc[b] / c.iloc[a] - 1
        return float(rr.where((quint.iloc[a] == q) & rr.notna()).mean())

    yahoo_cache: dict[str, dict | None] = {}
    out = []
    for p in picks.itertuples(index=False):
        rec = p._asdict()
        if isinstance(p.nse_symbol, str) and p.nse_symbol.startswith("other:"):
            n = p.nse_symbol[6:]
            s = {k: panel["other"][k][n] for k in ("open", "high", "low", "close", "turnover_cr")}
            rec["price_source"] = f"NSE SME/InvIT:{n}"
        elif isinstance(p.nse_symbol, str):
            n = p.nse_symbol
            s = {"open": o[n], "high": h[n], "low": lo[n], "close": c[n], "turnover_cr": panel["turnover_cr"][n]}
            rec["price_source"] = f"NSE:{n}"
        else:
            ys = p.yahoo_symbol if isinstance(p.yahoo_symbol, str) else None
            if ys not in yahoo_cache:
                yahoo_cache[ys] = yahoo_daily(ys, sessions) if ys else None
            s = yahoo_cache[ys]
            rec["price_source"] = f"Yahoo:{s['source']}" if s else "none"
        e = int(sessions.searchsorted(p.scan_date, side="right"))           # first session after the scan
        scan_i = int(sessions.searchsorted(p.scan_date, side="right")) - 1   # last session on/before the scan
        news_i = int(sessions.searchsorted(p.news_date, side="left")) - 1    # last close before the news
        rec["entry_date"] = sessions[e].date() if e <= last else None
        if s is None or e > last or pd.isna(s["open"].iloc[e]):
            out.append({**rec, "status": "no price" if s is None else ("pending" if e > last else "no trade at entry")})
            continue
        to_hist = s["turnover_cr"].iloc[max(0, e - 60):e].median()
        ranks = med_to.iloc[e].dropna()
        q = float(min(4, int((ranks < to_hist).mean() * 5))) if np.isfinite(to_hist) and len(ranks) else 0.0
        entry = float(s["open"].iloc[e])
        rec.update(status="open", entry_price=round(entry, 2), liquidity_quintile=int(q) + 1,
                   turnover_cr_60d=round(float(to_hist), 2) if np.isfinite(to_hist) else None)
        if news_i >= 0 and pd.notna(s["close"].iloc[news_i]) and pd.notna(s["close"].iloc[scan_i]):
            rec["pre_move_pct"] = round((s["close"].iloc[scan_i] / s["close"].iloc[news_i] - 1) * 100, 2)
            rec["pre_move_excess_pct"] = round(rec["pre_move_pct"] - bench_close(news_i, scan_i, q) * 100, 2)
        for k in HORIZONS:
            x = e + k - 1
            if x <= last and pd.notna(s["close"].iloc[x]):
                rec[f"r{k}_pct"] = round((s["close"].iloc[x] / entry - 1) * 100, 2)
                rec[f"ex{k}_pct"] = round(rec[f"r{k}_pct"] - bench(e, x, q) * 100, 2)
        latest = s["close"].iloc[e:].last_valid_index()
        if latest is not None:
            x = sessions.get_loc(latest)
            rec["sessions_held"] = x - e + 1
            rec["last_price"] = round(float(s["close"].iloc[x]), 2)
            rec["r_to_date_pct"] = round((s["close"].iloc[x] / entry - 1) * 100, 2)
            rec["ex_to_date_pct"] = round(rec["r_to_date_pct"] - bench(e, x, q) * 100, 2)
            rec["peak_pct"] = round((s["high"].iloc[e:x + 1].max() / entry - 1) * 100, 2)
            rec["worst_pct"] = round((s["low"].iloc[e:x + 1].min() / entry - 1) * 100, 2)
        out.append(rec)
    return pd.DataFrame(out)


# ── summaries ───────────────────────────────────────────────────────────────────

def summarize(df: pd.DataFrame, by: str | None, cost_pct: float, horizon: str = "5") -> pd.DataFrame:
    r, ex = (f"r{horizon}_pct", f"ex{horizon}_pct") if horizon != "to_date" else ("r_to_date_pct", "ex_to_date_pct")
    if r not in df:
        return pd.DataFrame()                       # nobody has been held that long yet
    d = df.dropna(subset=[r])
    groups = d.groupby(by) if by else [("all picks", d)]
    rows = []
    for key, g in groups:
        rows.append({"group": key, "picks": len(g), "days": g["scan_date"].nunique(),
                     "avg_return_pct": round(g[r].mean(), 2), "median_return_pct": round(g[r].median(), 2),
                     "avg_excess_pct": round(g[ex].mean(), 2), "beat_similar_stocks_pct": round((g[ex] > 0).mean() * 100, 1),
                     "after_costs_pct": round(g[r].mean() - cost_pct, 2),
                     "profitable_after_costs_pct": round((g[r] > cost_pct).mean() * 100, 1)})
    return pd.DataFrame(rows)


def day_clustered_t(df: pd.DataFrame, col: str) -> tuple[float, int]:
    daily = df.dropna(subset=[col]).groupby("scan_date")[col].mean()
    if len(daily) < 3:
        return float("nan"), len(daily)
    return float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))), len(daily)


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in r) + " |")
    return "\n".join(lines)


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe rows: dates as YYYY-MM-DD, categories as text, NaN as null."""
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            d[c] = d[c].dt.strftime("%Y-%m-%d")
        elif isinstance(d[c].dtype, pd.CategoricalDtype) or d[c].dtype == object:
            d[c] = d[c].map(lambda v: None if pd.isna(v) else (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)))
    return json.loads(d.to_json(orient="records"))


def track_record_json(res: pd.DataFrame, by_h: pd.DataFrame, sections: dict, cost: float, latest, t5: float,
                      n5: int) -> dict:
    """Machine-readable twin of REPORT.md for the News Terminal's TRACK RECORD view (ui-api serves it)."""
    pick_cols = ["scan_date", "symbol", "yahoo", "nse_symbol", "company", "conviction", "theme", "status",
                 "entry_date", "entry_price", "last_price", "sessions_held", "r_to_date_pct", "ex_to_date_pct",
                 "peak_pct", "worst_pct", "r5_pct", "ex5_pct"]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005 - local time, like REPORT.md
        "prices_through": str(latest),
        "cost_pct": round(float(cost), 3), "position_rs": POSITION_RS, "picks": len(res),
        "scans": int(res["scan_date"].nunique()), "first_scan": str(res["scan_date"].min().date()),
        "last_scan": str(res["scan_date"].max().date()),
        "t5": {"t": None if not np.isfinite(t5) else round(t5, 2), "scan_days": n5},
        "horizons": _records(by_h.drop(columns="group")[["horizon"] + [c for c in by_h.columns if c not in ("group", "horizon")]]),
        "sections": {title: _records(tab) for title, tab in sections.items()},
        "rows": _records(res[[c for c in pick_cols if c in res.columns]]),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/news_scanner")
    args = ap.parse_args(argv)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    picks = load_picks()
    panel = load_prices(start=str((picks["news_date"].min() - pd.Timedelta(days=150)).date()))
    res = measure(resolve(picks, panel), panel)
    cost = default_model().round_trip_pct(POSITION_RS)
    res["news_age_days"] = (res["scan_date"] - res["news_date"]).dt.days
    res["news_age"] = pd.cut(res["news_age_days"], [-1, 0, 3, 10, 999], labels=["same day", "1–3 days", "4–10 days", "> 10 days"])
    res["conviction_band"] = pd.cut(res["conviction"], [0, 3, 4, 5, 10], labels=["2–3", "4", "5", "6–8"])
    res["pre_move"] = pd.cut(res["pre_move_pct"], [-999, -3, 3, 10, 999],
                             labels=["fell > 3%", "flat (±3%)", "rose 3–10%", "rose > 10%"])
    res["times_picked"] = res.groupby("symbol")["scan_date"].transform("nunique")
    res.sort_values(["scan_date", "conviction"], ascending=[False, False]).to_csv(out / "picks.csv", index=False)

    latest = panel["close"].index.max().date()
    by_h = pd.concat([s.assign(horizon=f"{k} sessions") for k in HORIZONS
                      if not (s := summarize(res, None, cost, str(k))).empty]
                     + [summarize(res, None, cost, "to_date").assign(horizon="to date")])
    t5, n5 = day_clustered_t(res, "ex5_pct")
    sections = {
        "By conviction score (5 sessions)": summarize(res, "conviction_band", cost),
        "By how old the news was at scan time (5 sessions)": summarize(res, "news_age", cost),
        "By the move between the news and the scan (5 sessions)": summarize(res, "pre_move", cost),
        "By catalyst theme (5 sessions)": summarize(res, "theme", cost),
        "By scan date (to date)": summarize(res, "scan_date", cost, "to_date"),
    }
    held = res.dropna(subset=["r_to_date_pct"]).sort_values("ex_to_date_pct", ascending=False)
    cols = ["scan_date", "symbol", "company", "conviction", "theme", "entry_date", "entry_price", "last_price",
            "r_to_date_pct", "ex_to_date_pct", "peak_pct", "worst_pct", "pre_move_pct"]
    L = ["# News scanner track record", "",
         (f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/news_scan_performance.py`. {len(res)} picks from "  # noqa: DTZ005
          f"{res['scan_date'].nunique()} scans ({res['scan_date'].min().date()} → {res['scan_date'].max().date()}); prices "
          f"through {latest}. Entry = next session's open after the scan. Excess = minus the average NSE stock of similar "
          f"liquidity over the same window. Round-trip cost {cost:.2f}% at ₹{POSITION_RS:,}."), "",
         f"Status: {res['status'].value_counts().to_dict()}.", "",
         "## How the picks did", "", md(by_h[["horizon"] + [c for c in by_h.columns if c != "horizon"]].drop(columns="group")), "",
         f"Day-clustered t of the 5-session excess: {t5:.2f} over {n5} scan days (needs ≥ 2 and many more days to mean anything).", ""]
    for title, tab in sections.items():
        L += [f"## {title}", "", md(tab), ""]
    L += ["## Every pick, best to worst against similar stocks (to date)", "", md(held[cols]), ""]
    rest = res[res["r_to_date_pct"].isna()][["scan_date", "symbol", "company", "status", "entry_date"]]
    if len(rest):
        L += ["## Not measurable yet", "", md(rest), ""]
    (out / "REPORT.md").write_text("\n".join(L) + "\n")
    (out / "track_record.json").write_text(json.dumps(track_record_json(
        res, by_h, sections, cost, latest, t5, n5), indent=1, allow_nan=False))
    print("\n".join(L[:20]))


if __name__ == "__main__":
    main()
