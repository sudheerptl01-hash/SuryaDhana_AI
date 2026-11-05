#!/usr/bin/env python
"""Feature matrix v2 — merge the proven research signals + v3 labels onto the production matrix.

PRE-REGISTERED SPEC (written before the first real run; definitions are COPIED from the cited
canonical sources, never re-derived):

  Base: data/computed_features.parquet (v1, 73 cols, 2020-09-16→, plain NSE symbols). v2 keeps
  every v1 row and column (left join on ticker+date) and ADDS the columns below. v1 is untouched;
  v2 is a sibling artifact: data/computed_features_v2.parquet (+ .manifest.json).

  Data source: the sha256-verified nightly backup DuckDB (read-only; the live DB is locked by
  data-service). Panel via alpha_lab's vendored loader (drift-tested identical to shared/):
  survivorship-free, split/bonus-adjusted, 2019-06-01→ so every 252-session window is warm
  before v1's first date.

  NEW FEATURE COLUMNS (computable at the close of date t — no future data):
    carry_ann            (fut_close/raw_close − 1) × 365/days_to_near_expiry − RF(0.065);
                         days ≥ 3; |x| ≤ 0.40 else NaN; NaN when an ex-dividend falls in
                         (t, near_expiry]; F&O single stocks only.
                         [canon: alpha_lab/strategies/quick_tests.py:162 — the TESTED-ROBUST
                          excess-carry signal, computed daily instead of weekly]
    mom_nse              Desk momentum score: mean of z(ret6/σ) and z(ret12/σ) per date
    ret_126d, ret_252d   6m / 12m simple returns (adjusted close)
    sigma_252d           annualised 252d vol (min 200 obs)
                         [canon: shared/momentum.py signals(); vendored copy drift-tested]
    dist_52w_high_pct    close / rolling 252-max(close) − 1  (≤ 0; min 200 obs; the continuous
                         form of MOM-03 — the binary flag added nothing, the distance ranks)
    rsi_2                Wilder RSI, n=2 (evidence rsi2_leader = rsi_2 crossing low while near
                         the 52w high; both ingredients shipped, the flag stays derivable)
    flag_below_200dma    close < SMA200                       [canon: alpha_lab flags.py]
    flag_near_52w_low    close ≤ 1.10 × rolling 252-min        [ditto, pct=0.10]
    flag_split_20d       split/bonus ex-date within the last 20 sessions [ditto]
    flag_bad_results_60d strong-down results reaction (≤ −5% vs liquid-universe mean on the
                         reaction session) within the last 60 sessions   [ditto]
    (vol60 is NOT added: realized_vol_20d + sigma_252d already span the family, and the S1
     veto uses a within-universe decile cut that does not belong in a per-row matrix.)

  LABEL COLUMNS (FUTURE data by construction — train targets only, NEVER features):
    y_fwd_open_20d       open[t+1+20]/open[t+1] − 1            [canon: shared/xs_labels.py]
    y_excess_20d         y_fwd minus the same-date equal-weight universe mean
    y_rank_20d           percentile rank of the excess within the labelled universe
    y_clean_20d          True when no daily |log move| > log(1.5) inside the window
    Universe for excess/rank: rows present in v1 that date ∧ raw_close ≥ ₹20 ∧ series == EQ.

AMENDMENT 1 (15 Oct 2026, ~06:30 IST — made BEFORE any model was trained on v2; the original
spec above is left as written). Trigger: the owner-shared "Label Logic Review" (grounds 4 and 5)
plus a re-read of the canonical study, which showed two deviations in the first v2 build:
  (a) the study masks the forward return with clean_windows(close, h+1) BEFORE computing excess
      (scripts/ml_label_study.py:314-317); v2 computed excess on the UNMASKED return with an
      h-window, so data-break windows (unadjusted splits, relistings) polluted that date's
      benchmark mean and their own ranks. Fixed: y_fwd/y_excess/y_rank use the clean-masked
      return; y_clean_20d now uses the canonical h+1 = 21 window.
  (b) the broad label universe had no liquidity floor and did not check the entry bar was
      fillable. Added the TRAINING-sample mask y_elig (+ y_elig_reason, first failing rule):
      series EQ · raw close ≥ ₹20 · 20-session median turnover ≥ ₹1 cr (the MKT universe rule) ·
      an entry bar exists at t+1 · the entry day is not locked (high == low: no two-sided market).
      Excess/rank are now computed within y_elig. Labels are never re-valued by the mask — rows
      outside it simply have no universe-relative label (NaN), as "undefined" should read.
  (c) added the study's EXACT universe as its own label set — y_desk_universe (top 300 by 126d
      median turnover among EQ, close ≥ ₹20, ≥ 250 sessions, no ETFs: shared.momentum.eligible)
      with y_excess_20d_desk / y_rank_20d_desk — the label the ML-labels study actually validated.
  Training protocol (written to the manifest): overlapping 20-session labels on daily rows are
  highly autocorrelated — purge ≥ 20 sessions + embargo before every validation fold (the ML
  Engine's TrainRequest defaults label_horizon=5/embargo=5 are for the legacy label; set 20), or
  sample one row per ticker per 20 sessions; never shuffle; score with rank IC / top-quantile
  precision, not accuracy.

Run:  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/build_features_v2.py
      [--backup data/backups/duckdb/market-YYYYMMDD.duckdb] [--out data/computed_features_v2.parquet]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "alpha_lab"))
import lib  # noqa: F401,E402  (aliases `shared` → the drift-tested vendored copies)
from lib.momentum import MIN_HISTORY, MIN_PRICE, UNIVERSE_SIZE, is_etf  # noqa: E402
from lib.momentum import signals as mom_signals  # noqa: E402
from lib.nse_panel import load_panel  # noqa: E402
from strategies import flags as fl  # noqa: E402

# shared/xs_labels.py imported by path: unambiguous next to the vendored alias
_spec = importlib.util.spec_from_file_location("xs_labels", ROOT / "shared" / "xs_labels.py")
xs_labels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xs_labels)

RF = 0.065           # quick_tests.py:41
BASIS_CAP = 0.40     # quick_tests.py:42
PANEL_START = "2019-06-01"
H = 20
MIN_LABEL_PRICE = 20.0          # ₹, raw close
MIN_MEDIAN_TURNOVER_CR = 1.0    # 20-session median, the MKT universe rule (market_monitor.universe)
ELIG_REASONS = {0: "ok", 1: "not_eq", 2: "below_20", 3: "illiquid", 4: "no_entry", 5: "entry_locked"}


def desk_universe(panel: dict, sig: dict) -> pd.DataFrame:
    """shared.momentum.eligible vectorised over every session (same as ml_label_study.desk_universe)."""
    cols = panel["close"].columns
    etf = pd.Series([is_etf(s) for s in cols], index=cols)
    ok = (panel["series"].eq("EQ") & panel["close"].ge(MIN_PRICE) & sig["hist"].ge(MIN_HISTORY) & ~etf)
    liq = sig["liq"].where(ok)
    return liq.rank(axis=1, ascending=False, method="first").le(UNIVERSE_SIZE)


def label_frames(panel: dict, member: pd.DataFrame, desk_uni: pd.DataFrame | None = None,
                 h: int = H) -> dict[str, pd.DataFrame]:
    """v3 labels per AMENDMENT 1: clean-masked next-open returns, excess/rank within the
    training-eligible universe (+ the Desk universe when given), and the eligibility reason code."""
    close, open_, raw = panel["close"], panel["open"], panel["raw_close"]
    clean = xs_labels.clean_windows(close, h + 1)                       # canonical h+1 window
    fwd = xs_labels.forward_open_returns(open_, h).where(clean)
    eq = panel["series"].eq("EQ")
    px = raw.ge(MIN_LABEL_PRICE)
    liquid = panel["turnover_cr"].rolling(20, min_periods=10).median().ge(MIN_MEDIAN_TURNOVER_CR)
    has_entry = open_.shift(-1).notna()
    locked = has_entry & panel["high"].shift(-1).eq(panel["low"].shift(-1))
    elig = member & eq & px & liquid & has_entry & ~locked
    code = pd.DataFrame(
        np.select([~eq.to_numpy(), ~px.to_numpy(), ~liquid.to_numpy(), ~has_entry.to_numpy(), locked.to_numpy()],
                  [1, 2, 3, 4, 5], 0),
        index=close.index, columns=close.columns)
    excess = xs_labels.excess_returns(fwd, elig)
    out = {"y_fwd_open_20d": fwd, "y_excess_20d": excess, "y_rank_20d": xs_labels.rank_label(excess),
           "y_clean_20d": clean, "y_elig": elig, "y_elig_code": code}
    if desk_uni is not None:
        ex_d = xs_labels.excess_returns(fwd, desk_uni)
        out.update({"y_desk_universe": desk_uni, "y_excess_20d_desk": ex_d,
                    "y_rank_20d_desk": xs_labels.rank_label(ex_d)})
    return out


def wilder_rsi(close: pd.DataFrame, n: int = 2) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = up / dn
    return (100 - 100 / (1 + rs)).where(close.notna())


def carry_frame(fo: pd.DataFrame, raw_close: pd.DataFrame, div: pd.DataFrame | None) -> pd.DataFrame:
    """Daily excess-carry wide frame per the pre-registered spec (quick_tests.py analogue)."""
    f = fo[fo["fut_close"].notna() & fo["near_expiry"].notna()].copy()
    f["date"] = pd.to_datetime(f["date"])
    f["near_expiry"] = pd.to_datetime(f["near_expiry"])
    f["days"] = (f["near_expiry"] - f["date"]).dt.days
    f = f[f["days"] >= 3]
    fut = f.pivot_table(index="date", columns="symbol", values="fut_close", aggfunc="last")
    days = f.pivot_table(index="date", columns="symbol", values="days", aggfunc="last")
    nexp = f.pivot_table(index="date", columns="symbol", values="near_expiry", aggfunc="last")
    spot = raw_close.reindex(index=fut.index, columns=fut.columns)
    basis = (fut / spot - 1).mul(365.0 / days) - RF
    basis = basis.where(basis.abs() <= BASIS_CAP)
    if div is not None and len(div):
        dd = {s: np.sort(g["date"].astype("datetime64[ns]").to_numpy()) for s, g in div.groupby("symbol")}
        dates = fut.index.to_numpy()
        for c in basis.columns:
            ex = dd.get(c)
            if ex is None or not len(ex):
                continue
            nxt = np.searchsorted(ex, dates, side="right")
            has = nxt < len(ex)
            next_div = np.where(has, ex[np.minimum(nxt, len(ex) - 1)], np.datetime64("2100-01-01"))
            inside = has & (next_div <= nexp[c].to_numpy())
            basis.loc[inside, c] = np.nan
    return basis


def build(backup: Path, v1_path: Path, out: Path) -> dict:
    t0 = time.time()
    con = duckdb.connect(str(backup), read_only=True)
    try:
        panel = load_panel(con, start=PANEL_START)
        q = lambda s: con.execute(s).df()  # noqa: E731
        fo = q("SELECT date, symbol, near_expiry, fut_close FROM nse_fo_daily")
        releases = q("SELECT symbol, period_end, released_at FROM nse_results "
                     "WHERE released_at IS NOT NULL AND released_at >= TIMESTAMP '2019-01-01'")
        try:
            # dividends schema: (ticker, date, amount) — plain NSE symbols
            div = q("SELECT date, ticker AS symbol FROM dividends")
        except Exception:
            div = None  # carry then ships UNstripped — manifest flags it; treat as a defect
    finally:
        con.close()
    releases["released_at"] = pd.to_datetime(releases["released_at"])

    close, open_, raw = panel["close"], panel["open"], panel["raw_close"]
    sig = mom_signals(panel)
    veto = fl.s1_veto_frames(panel, releases)
    wide: dict[str, pd.DataFrame] = {
        "carry_ann": carry_frame(fo, raw, div),
        "mom_nse": sig["mom_nse"], "ret_126d": sig["ret6"], "ret_252d": sig["ret12"],
        "sigma_252d": sig["sigma"],
        "dist_52w_high_pct": close / close.rolling(252, min_periods=200).max() - 1,
        "rsi_2": wilder_rsi(close, 2),
        "flag_below_200dma": veto["below_200dma"],
        "flag_near_52w_low": veto["near_52w_low"],
        "flag_split_20d": veto["split_20d"],
        "flag_bad_results_60d": veto["bad_results_60d"],
    }
    # labels (xs_labels v3, AMENDMENT 1) — universe fixed AFTER v1 membership is known
    v1 = pd.read_parquet(v1_path)
    v1["date"] = pd.to_datetime(v1["date"])
    base_rows = len(v1)

    member = v1.assign(one=True).pivot_table(index="date", columns="ticker", values="one", aggfunc="any")
    member = member.reindex(index=close.index, columns=close.columns).fillna(False).astype(bool)
    wide.update(label_frames(panel, member, desk_universe(panel, sig), H))

    long = {name: df.stack().rename(name) for name, df in wide.items()}
    add = pd.concat(long.values(), axis=1).reset_index()
    add.columns = ["date", "ticker", *long.keys()]
    for c in ("flag_below_200dma", "flag_near_52w_low", "flag_split_20d", "flag_bad_results_60d",
              "y_clean_20d", "y_elig", "y_desk_universe"):
        add[c] = add[c].astype("boolean")

    v2 = v1.merge(add, on=["date", "ticker"], how="left", validate="one_to_one")
    assert len(v2) == base_rows, f"row drift: {base_rows} -> {len(v2)}"
    v2["y_elig_reason"] = v2.pop("y_elig_code").map(ELIG_REASONS).astype("category")
    v2["feature_version"] = "v2"
    v2.to_parquet(out, index=False)

    new_cols = [c for c in long if c != "y_elig_code"] + ["y_elig_reason"]
    cov = {c: round(100 * float(v2[c].notna().mean()), 2) for c in new_cols}
    labelled = v2["y_fwd_open_20d"].notna()
    ac = (v2.loc[v2["y_excess_20d"].notna(), ["ticker", "date", "y_excess_20d"]]
          .sort_values(["ticker", "date"]).groupby("ticker")["y_excess_20d"]
          .apply(lambda s: s.autocorr(1) if len(s) > 60 else np.nan).dropna())
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source_backup": str(backup), "base": str(v1_path), "rows": len(v2),
        "cols": len(v2.columns), "new_columns": new_cols, "coverage_pct": cov,
        "spec_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16],
        "amendments": ["1 (15 Oct 2026, before any training): clean-masked labels (h+1 window), "
                       "y_elig training mask + reason, Desk-universe label set — see docstring"],
        "label_warning": "y_* columns use FUTURE prices — train targets only, never features",
        "eligibility": {
            "rows_by_reason": {str(k): int(v) for k, v in v2["y_elig_reason"].value_counts().items()},
            "eligible_pct_of_all_rows": round(100 * float(v2["y_elig"].fillna(False).mean()), 2),
            "unclean_label_windows": int((labelled.eq(False) & v2["y_clean_20d"].eq(False)).sum()),
            "desk_universe_rows": int(v2["y_desk_universe"].fillna(False).sum()),
        },
        "label_autocorr_lag1_median": round(float(ac.median()), 3) if len(ac) else None,
        "training_protocol": (
            "train rows: y_elig & y_rank_20d.notna() (or y_desk_universe & y_rank_20d_desk.notna() to "
            "match the validated study). Labels overlap 20 sessions: purge >= 20 sessions + embargo before "
            "each validation fold (ML Engine TrainRequest: set label_horizon=20, not the legacy 5), or "
            "keep one row per ticker per 20 sessions. Never shuffle. Score by rank IC / top-quantile "
            "precision, never accuracy."),
        "dividend_strip": div is not None,
        "seconds": round(time.time() - t0, 1),
    }
    Path(str(out) + ".manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    backups = sorted((ROOT / "data" / "backups" / "duckdb").glob("market-*.duckdb"))
    ap.add_argument("--backup", default=str(backups[-1]) if backups else None,
                    help="read-only DuckDB snapshot (default: newest verified backup)")
    ap.add_argument("--v1", default=str(ROOT / "data" / "computed_features.parquet"))
    ap.add_argument("--out", default=str(ROOT / "data" / "computed_features_v2.parquet"))
    args = ap.parse_args()
    if not args.backup:
        sys.exit("no backup DuckDB found — run scripts/db_backup.py first")
    m = build(Path(args.backup), Path(args.v1), Path(args.out))
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
