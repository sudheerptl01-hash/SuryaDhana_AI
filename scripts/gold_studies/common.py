"""Shared helpers for the pre-registered gold studies (scripts/gold_studies/*).

Everything a study needs that is not its hypothesis lives here, so the four scripts differ only in their data,
signals and pass bars (which are pinned in their `PLAN.md` before any result is looked at):

* point-in-time alignment — `forward_returns` starts every forward window at the close of the session AFTER the
  signal became public (no look-ahead), `expanding_percentile` / `expanding_tercile` rank a value only against
  strictly earlier values (walk-forward); `release_rule` gives the publication instant of a report on a known schedule
  (mirroring data-service `gold/pit.py`), `entry_after_release` the first session whose settlement comes after it, and
  `pit_lagged` the value of an earlier report **as it stood at the decision instant** (the latest vintage with
  `release_at <= asof` — the QUALIFY rule of `read_gold_series(asof=…)` applied per decision, so a revision is never
  seen before its own `release_at`);
* statistics without statsmodels — Bartlett Newey-West t-statistics for overlapping forward windows
  (`newey_west_t`, `nw_slope_t`, `rank_ic`), tercile spreads, cell-vs-all tests, a walk-forward long/flat rule
  after round-trip costs (`walk_forward_long_flat`);
* the verdict rule of PLAN f.1: `verdict` for a statistic (PASS needs |t| >= 2 in the full sample and the same sign
  with |t| >= 2 in both halves; |t| >= 2 in the full sample only is CONTEXT-ONLY; everything else FAILs) and
  `verdict_traded` for a rule that is traded (SIGNED: the out-of-sample excess after costs must have t >= 2 in the OOS
  span and in both OOS halves in the direction traded — a rule that loses consistently is a FAIL, never a PASS);
* loaders for the saved research data (Yahoo CSVs in two layouts, FRED fredgraph CSVs, the SPDR GLD archive XLSX,
  the World Bank CMO monthly file, the WGC fsapi chart JSON, the G-CME product-OI CSV) and read-only access to the
  data-service gold tables on a snapshot copy (`open_snapshot`, a context manager that removes the copy on exit and
  refuses to copy the live `data/market.duckdb` inside the IST busy windows unless told otherwise);
* the honest exits: `not_ingested()` prints a JSON status and exits with code 3 when a dataset the study needs is
  not stored yet, `insufficient()` exits with code 4 when it is stored but too short, `live_busy()` exits with code 5
  when the live file may not be copied right now — a study never fabricates;
* the FINDINGS row renderers: `study_row` (the study's own page, the 3-column `reports/fii_positioning` shape) and
  `aggregate_row` (the 4-column shape of the programme's `reports/gold_program/FINDINGS.md`, verdict in its own cell);
  the contract is written down in `scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md`.

Every statistic drops non-finite inputs first (`_finite`): a 0-tonne base (WGC regions before their first fund) or a
zero-OI session yields ±inf in a % change, and inf must never reach a dot product. No network access anywhere in this
package: studies run on stored data only.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
GOLD_PROGRAM = ROOT / "reports" / "gold_program"
G_STUDY_DATA = GOLD_PROGRAM / "G-STUDY" / "data"
G_MACRO_DATA = GOLD_PROGRAM / "G-MACRO" / "data"
G_PHYSICAL_SAMPLES = GOLD_PROGRAM / "G-PHYSICAL" / "samples"
G_CME_SAMPLES = GOLD_PROGRAM / "G-CME" / "samples"
G_COT_DATA = GOLD_PROGRAM / "G-COT" / "data"
LIVE_DATA_DIR = ROOT / "data"                      # the data-service's directory: anything under it is the live store
LIVE_DB = LIVE_DATA_DIR / "market.duckdb"

COST_RT = 0.15                 # % per round trip: the project floor (CLAUDE.md "never < 0.15 %")
T_PASS = 2.0                   # |t| required in the full sample AND in each half (PLAN f.1)
EXIT_NOT_INGESTED = 3          # the dataset the study needs is not stored yet
EXIT_INSUFFICIENT = 4          # stored, but shorter than the plan's minimum
EXIT_LIVE_BUSY = 5             # the live DuckDB may not be copied right now (IST busy window); re-run later or override
TROY_OZ_G = 31.1034768

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)     # IST has no DST: a fixed offset turns IST wall time into UTC-naive
# COMEX GC settles 13:30 ET = 17:30 UTC (EDT) / 18:30 UTC (EST). A release at or after the EARLIER bound on day D cannot
# be traded at D's close (conservative: never earlier than the truth, at worst one session later in winter).
SETTLE_CUTOFF_UTC = time(17, 30)
# Publication rules of the stored series this package reads, as data-service gold/pit.py stamps release_at (UTC-naive):
# (calendar days after report_date, IST wall time). The studies use the STORED release_at whenever the table carries
# one; these rules serve the fixture paths and the fallback when a row has none.
RELEASE_RULES: dict[str, tuple[int, time]] = {
    "gld": (1, time(6, 0)),            # the archive row for T is visible ≈06:00 IST on T+1
    "wgc_weekly": (3, time(11, 30)),   # Friday-dated week → Monday ≈11:30 IST
    "cme_voi": (1, time(14, 30)),      # daily_volume.xlsx for T is posted on T+1 ≈14:00–15:30 IST
}
# IST windows (Mon–Fri) in which the live data-service store is busy: ICICI login + pre-open jobs, the NSE session and
# its post-close ingest, and the EOD pipeline (CLAUDE.md freeze windows 07:45–09:20 and 18:30–21:15 plus the session
# between them). Copying 4.4 GB of data/market.duckdb competes with that I/O, so the verdict scripts refuse by default.
LIVE_BUSY_WINDOWS_IST: tuple[tuple[time, time], ...] = ((time(7, 45), time(15, 45)), (time(18, 30), time(21, 15)))
SNAPSHOT_HEADROOM = 1.10       # free disk required: this multiple of the file (+ WAL) size, plus SNAPSHOT_MIN_FREE_BYTES
SNAPSHOT_MIN_FREE_BYTES = 256 * 1024 * 1024

PASS, CONTEXT_ONLY, FAIL = "PASS", "CONTEXT-ONLY", "FAIL"
VOID = "VOID"                  # a pre-registered statistic whose own negative control "passes" (GS-P4 N4); badge = FAIL
PENDING = "PENDING"            # pre-registered, data not stored yet (exit 3 / 4)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Status exits (never fabricate)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Status:
    """Machine-readable outcome of a study run, printed as one JSON line on stdout."""

    study: str
    status: str                 # ran | data not yet ingested | insufficient history
    needs: str = ""
    how: str = ""
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class DataNotIngested(RuntimeError):
    """Raised by a loader when the dataset the study needs is not stored (yet)."""


class InsufficientHistory(RuntimeError):
    """Raised when the dataset exists but is shorter than the plan's minimum sample."""


class LiveFileBusy(RuntimeError):
    """Raised when a study would copy the live data-service DuckDB inside an IST busy window without an override."""


class SnapshotSpace(RuntimeError):
    """Raised before copying when the temp location lacks the room for a full snapshot (never a partial copy)."""


def not_ingested(study: str, needs: str, how: str, detail: str = "") -> None:
    """Print the status line and exit 3. The study must never substitute, extrapolate or fabricate."""
    print(Status(study, "data not yet ingested", needs, how, detail).to_json())
    sys.exit(EXIT_NOT_INGESTED)


def insufficient(study: str, needs: str, detail: str = "") -> None:
    """Print the status line and exit 4 (stored, but too short for the pre-registered test)."""
    print(Status(study, "insufficient history", needs, "", detail).to_json())
    sys.exit(EXIT_INSUFFICIENT)


def live_busy(study: str, detail: str = "") -> None:
    """Print the status line and exit 5: the live file is in a busy window; nothing was copied, nothing written."""
    print(Status(study, "live file busy", "a quiet IST window (outside Mon–Fri 07:45–15:45 and 18:30–21:15)",
                 "re-run later, or pass --allow-market-hours to copy the live file now", detail).to_json())
    sys.exit(EXIT_LIVE_BUSY)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Statistics (no statsmodels in the environment: Newey-West by hand, as in G-STUDY/g_study.py)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _finite(x: pd.Series | np.ndarray | list[float], index: pd.Index | None = None) -> pd.Series:
    """A float Series with ±inf turned into NaN (a 0 base in a % change must never reach a dot product)."""
    s = pd.Series(x, dtype=float) if index is None else pd.Series(np.asarray(x, dtype=float), index=index)
    return s.replace([np.inf, -np.inf], np.nan)


def pct_change_guarded(s: pd.Series, k: int, min_base: float) -> pd.Series:
    """`s / s.shift(k) - 1` in %, NaN wherever the base is missing or below `min_base` (no ±inf, no 0-base noise)."""
    x = _finite(s)
    return pct_vs_base(x, x.shift(k), min_base)


def pct_vs_base(x: pd.Series | np.ndarray, base: pd.Series | np.ndarray, min_base: float, index: pd.Index | None = None) -> pd.Series:
    """`x / base - 1` in % for two aligned series/arrays (e.g. point-in-time lagged values), NaN wherever the base is
    missing or below `min_base`."""
    idx = index if index is not None else (x.index if isinstance(x, pd.Series) else None)
    xv = _finite(np.asarray(x, dtype=float), idx) if idx is not None else _finite(x)
    bv = _finite(np.asarray(base, dtype=float), xv.index)
    out = (xv / bv - 1) * 100
    out[~(bv >= min_base)] = np.nan
    return _finite(out)


def _dot(a: np.ndarray, b: np.ndarray) -> float:
    """a·b with the floating-point exception flags silenced: numpy 2.2 on Apple Accelerate raises a spurious 'divide by
    zero encountered in matmul' for finite vectors of >= 1,000 elements. Inputs pass through `_finite` first, and a
    non-finite product still comes back as NaN for the caller to reject."""
    with np.errstate(all="ignore"):
        v = float(a @ b)
    return v if math.isfinite(v) else float("nan")


def newey_west_t(x: pd.Series | np.ndarray | list[float], lags: int) -> float:
    """t-statistic of the mean with a Bartlett Newey-West variance (overlapping forward windows need lags = h-1)."""
    v = _finite(x).dropna().to_numpy()
    n = len(v)
    if n < 4:
        return float("nan")
    e = v - v.mean()
    s = _dot(e, e) / n
    for lag in range(1, min(int(lags), n - 1) + 1):
        s += 2 * (1 - lag / (lags + 1)) * _dot(e[lag:], e[:-lag]) / n
    return float(v.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def nw_slope_t(x: pd.Series, y: pd.Series, lags: int) -> tuple[float, float]:
    """OLS slope of y on x with a Newey-West t (HAC on the score x̃·e). Returns (beta, t)."""
    d = pd.concat([_finite(x), _finite(y)], axis=1).dropna()
    if len(d) < 10:
        return float("nan"), float("nan")
    xv, yv = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    xt = xv - xv.mean()
    sxx = _dot(xt, xt)
    if not sxx > 0:
        return float("nan"), float("nan")
    beta = _dot(xt, yv - yv.mean()) / sxx
    u = xt * ((yv - yv.mean()) - beta * xt)
    n = len(u)
    s = _dot(u, u) / n
    for lag in range(1, min(int(lags), n - 1) + 1):
        s += 2 * (1 - lag / (lags + 1)) * _dot(u[lag:], u[:-lag]) / n
    if not s > 0:
        return float(beta), float("nan")
    se = math.sqrt(s * n) / sxx
    return float(beta), float(beta / se) if se > 0 else float("nan")


def rank_ic(signal: pd.Series, fwd: pd.Series, lags: int) -> dict[str, float]:
    """Spearman rank IC of a signal vs a forward return, with the Newey-West t of the rank-slope."""
    d = pd.concat([_finite(signal), _finite(fwd)], axis=1).dropna()
    if len(d) < 10:
        return {"n": len(d), "spearman": float("nan"), "t": float("nan")}
    rho = float(stats.spearmanr(d.iloc[:, 0], d.iloc[:, 1])[0])
    _, t = nw_slope_t(d.iloc[:, 0].rank(), d.iloc[:, 1], lags)
    return {"n": len(d), "spearman": round(rho, 4), "t": round(t, 2)}


def expanding_percentile(s: pd.Series, min_hist: int) -> pd.Series:
    """Percentile of s[t] within s[:t] — strictly earlier values only (the walk-forward rank)."""
    v = _finite(s).to_numpy()
    out = np.full(len(v), np.nan)
    for i in range(min_hist, len(v)):
        if np.isnan(v[i]):
            continue
        past = v[:i]
        past = past[~np.isnan(past)]
        if len(past) >= min_hist:
            out[i] = (past < v[i]).mean() + 0.5 * (past == v[i]).mean()
    return pd.Series(out, index=s.index)


def expanding_tercile(s: pd.Series, min_hist: int) -> pd.Series:
    """'top' / 'bottom' / 'middle' from expanding tercile cut-offs computed on strictly earlier values."""
    x = _finite(s)
    lo = x.expanding(min_hist).quantile(1 / 3).shift(1)
    hi = x.expanding(min_hist).quantile(2 / 3).shift(1)
    out = pd.Series(np.where(x >= hi, "top", np.where(x <= lo, "bottom", "middle")), index=x.index, dtype=object)
    out[lo.isna() | hi.isna() | x.isna()] = None
    return out


def tercile_spread(fwd: pd.Series, bucket: pd.Series, lags: int) -> dict[str, Any]:
    """Top-tercile minus bottom-tercile mean forward return, with the NW t of the signed, de-meaned series."""
    d = pd.DataFrame({"fwd": _finite(fwd), "b": bucket}).dropna()
    top, bot = d.loc[d["b"] == "top", "fwd"], d.loc[d["b"] == "bottom", "fwd"]
    sign = pd.Series(np.where(d["b"] == "top", 1.0, np.where(d["b"] == "bottom", -1.0, 0.0)), index=d.index)
    active = ((d["fwd"] - d["fwd"].mean()) * sign)[sign != 0]
    return {"n": len(d), "top_n": len(top), "bottom_n": len(bot),
            "top_mean": round(float(top.mean()), 3) if len(top) else float("nan"),
            "bottom_mean": round(float(bot.mean()), 3) if len(bot) else float("nan"),
            "spread": round(float(top.mean() - bot.mean()), 3) if len(top) and len(bot) else float("nan"),
            "t_nw": round(newey_west_t(active, lags), 2)}


def cell_vs_all(fwd: pd.Series, mask: pd.Series, lags: int) -> dict[str, Any]:
    """Mean forward return inside a cell (a month, a quadrant) minus the unconditional mean, NW t."""
    f = _finite(fwd)
    mu = f.mean()
    x = f[mask.reindex(f.index).fillna(False).astype(bool)].dropna()
    if len(x) < 5:
        return {"n": len(x), "mean": float("nan"), "hit_pct": float("nan"), "excess": float("nan"), "t_nw": float("nan")}
    return {"n": len(x), "mean": round(float(x.mean()), 3), "hit_pct": round(float((x > 0).mean() * 100), 1),
            "excess": round(float(x.mean() - mu), 3), "t_nw": round(newey_west_t(x - mu, lags), 2)}


def release_rule(kind: str, report_date: pd.Timestamp | str) -> pd.Timestamp:
    """Publication instant (UTC-naive) of a report dated `report_date` for a source with a known schedule (`RELEASE_RULES`),
    the way data-service gold/pit.py stamps `release_at` — for the fixture paths and as the fallback when a stored row
    has no release_at. Never earlier than the truth: the rules carry the latest usual posting time."""
    days, wall = RELEASE_RULES[kind]
    day = pd.Timestamp(report_date).normalize() + pd.Timedelta(days=days)
    return pd.Timestamp(datetime.combine(day.date(), wall)) - IST_OFFSET


def session_settles_at(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The instant (UTC-naive) each COMEX session's settlement is known: the date + SETTLE_CUTOFF_UTC."""
    return pd.DatetimeIndex(pd.DatetimeIndex(sessions).normalize() + pd.Timedelta(hours=SETTLE_CUTOFF_UTC.hour, minutes=SETTLE_CUTOFF_UTC.minute))


def entry_after_release(sessions: pd.DatetimeIndex, release_at: pd.Series | np.ndarray | list, shift: int = 0) -> np.ndarray:
    """Position (into `sessions`) of the first session whose settlement comes strictly AFTER each release instant, plus
    `shift` further sessions; `len(sessions)` marks 'no such session yet'. A signal released at 06:00 UTC on a Monday is
    traded at Monday's close; one released at 18:00 UTC is traded on Tuesday. NaT releases map to len(sessions)."""
    settles = session_settles_at(sessions).to_numpy()
    rel = pd.to_datetime(pd.Series(release_at)).to_numpy()
    pos = np.searchsorted(settles, rel, side="right") + shift
    pos = np.where(pd.isna(rel), len(sessions), pos)
    return np.minimum(pos, len(sessions)).astype(int)


def first_vintage(vintages: pd.DataFrame) -> pd.DataFrame:
    """From a long vintages frame (`series_id, report_date, value, release_at`, every revision) the FIRST release of each
    (series_id, report_date): the value a reader saw when the report came out and the instant it did."""
    v = vintages.sort_values(["series_id", "report_date", "release_at"])
    return v.groupby(["series_id", "report_date"], as_index=False).first()[["series_id", "report_date", "value", "release_at"]]


def pit_lagged(vintages: pd.DataFrame, decision_at: pd.Series, k: int) -> pd.Series:
    """For one series: the value of the report `k` report-dates EARLIER than each decision's report_date, **as it stood at
    the decision instant** — the latest vintage of that earlier report with `release_at <= decision_at` (the QUALIFY rule
    of `read_gold_series(asof=…)` applied per decision). `decision_at` is indexed by report_date; a revision released
    after the decision is never seen; an earlier report not yet released at the decision is NaN.

    Vectorised as a backward `merge_asof` on release_at within each lagged report_date (the input is a few thousand
    rows, so clarity wins over cleverness)."""
    v = vintages[["report_date", "value", "release_at"]].copy()
    v["report_date"] = pd.to_datetime(v["report_date"])
    v["release_at"] = pd.to_datetime(v["release_at"])
    v = v.sort_values(["release_at", "report_date"]).reset_index(drop=True)
    dates = pd.DatetimeIndex(sorted(v["report_date"].unique()))
    dec = pd.DataFrame({"report_date": pd.to_datetime(decision_at.index), "decision_at": pd.to_datetime(decision_at.to_numpy())})
    pos = dates.get_indexer(dec["report_date"]) - k
    dec["lag_date"] = pd.to_datetime(np.where(pos >= 0, dates.to_numpy()[np.clip(pos, 0, None)], np.datetime64("NaT")))
    dec = dec.sort_values("decision_at").reset_index(drop=True)
    ok = dec["lag_date"].notna() & dec["decision_at"].notna()
    merged = pd.merge_asof(dec[ok].rename(columns={"decision_at": "release_at"}), v, left_on="release_at", right_on="release_at",
                           left_by="lag_date", right_by="report_date", direction="backward", suffixes=("", "_v"))
    out = pd.Series(np.nan, index=pd.to_datetime(decision_at.index), dtype=float)
    if not merged.empty:
        out.loc[pd.to_datetime(merged["report_date"])] = merged["value"].to_numpy(dtype=float)
    return out


def halves(index: pd.Index, split: str | pd.Timestamp) -> tuple[pd.Series, pd.Series]:
    """Boolean masks for the two halves of a sample (first half ends ON the split date)."""
    cut = pd.Timestamp(split)
    idx = pd.DatetimeIndex(index)
    h1 = pd.Series(idx <= cut, index=index)
    return h1, ~h1


def _nan(v: float | None) -> bool:
    return v is None or (isinstance(v, (float, np.floating)) and math.isnan(v))


def verdict(t_full: float, t_h1: float, t_h2: float, oos_t: float | None = None, t_pass: float = T_PASS) -> str:
    """PLAN f.1 for a STATISTIC (an IC, a cell mean, a month effect — sign free, the direction is learned or reported):
    PASS = |t| >= 2 full sample, same sign and |t| >= 2 in both halves (and OOS t >= 2 when a traded leg is attached
    through `oos_t`, which is signed: the rule must pay); CONTEXT-ONLY = |t| >= 2 in the full sample only; FAIL
    otherwise. NaNs never pass. For a rule that IS the thing graded use `verdict_traded`."""
    vals = [t_full, t_h1, t_h2]
    if any(_nan(v) for v in vals):
        return FAIL if (_nan(t_full) or abs(t_full) < t_pass) else CONTEXT_ONLY
    both = abs(t_h1) >= t_pass and abs(t_h2) >= t_pass and np.sign(t_h1) == np.sign(t_h2) == np.sign(t_full)
    if abs(t_full) >= t_pass and both and (oos_t is None or (not _nan(oos_t) and oos_t >= t_pass)):
        return PASS
    if abs(t_full) >= t_pass:
        return CONTEXT_ONLY
    return FAIL


def verdict_traded(t_oos: float, t_h1: float, t_h2: float, t_pass: float = T_PASS) -> str:
    """PLAN f.1 for a TRADED rule, SIGNED: the statistics are the rule's out-of-sample excess after costs (vs scaled
    buy-and-hold) in the OOS span and in each OOS half, in the direction traded. PASS = t >= 2 in all three (the rule
    pays, consistently); CONTEXT-ONLY = t >= 2 in the OOS span only; FAIL otherwise — including a rule that loses
    consistently (t <= −2 everywhere): the opposite rule was never pre-registered, so a sign flip earns nothing.
    NaNs never pass."""
    if _nan(t_oos) or t_oos < t_pass:
        return FAIL
    if _nan(t_h1) or _nan(t_h2):
        return CONTEXT_ONLY
    return PASS if (t_h1 >= t_pass and t_h2 >= t_pass) else CONTEXT_ONLY


def perf(returns: pd.Series, periods_per_year: int) -> dict[str, Any]:
    """CAGR, annualised vol, Sharpe (rf 0), max drawdown of a periodic simple-return series (fractions)."""
    r = pd.Series(returns, dtype=float).dropna()
    if len(r) < 10:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / periods_per_year
    sd = float(r.std())
    return {"cagr": round((float(eq.iloc[-1]) ** (1 / yrs) - 1) * 100, 2), "vol": round(sd * math.sqrt(periods_per_year) * 100, 2),
            "sharpe": round(float(r.mean()) / sd * math.sqrt(periods_per_year), 2) if sd > 0 else None,
            "max_dd": round(float((eq / eq.cummax() - 1).min() * 100), 1), "periods": len(r)}


def forward_returns(price: pd.Series, horizons: tuple[int, ...], entry_shift: int = 1) -> pd.DataFrame:
    """Forward returns (%) from the close `entry_shift` sessions after the signal date to `h` sessions later, plus
    `r_next`, the one-period return of a position taken at that entry close (used by the walk-forward rule).

    With entry_shift = 1 a signal dated at session T (public before session T+1 ends) is traded at the close of T+1,
    so no forward window contains a close that was known when the signal was published."""
    p = pd.Series(price, dtype=float)
    out = pd.DataFrame(index=p.index)
    base = p.shift(-entry_shift)
    for h in horizons:
        out[f"fwd{h}"] = (p.shift(-(entry_shift + h)) / base - 1) * 100
    out["r_next"] = p.shift(-(entry_shift + 1)) / base - 1
    out["entry_px"] = base
    return out


def plain_t(x: pd.Series | np.ndarray | list[float]) -> float:
    """Ordinary t of the mean (non-overlapping observations, e.g. monthly log returns)."""
    v = _finite(x).dropna().to_numpy()
    if len(v) < 3 or v.std(ddof=1) == 0:
        return float("nan")
    return float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))


def evaluate_long_flat(pos: pd.Series, r: pd.Series, *, h: int, periods_per_year: int, cost_rt: float = COST_RT,
                       is_end: int = 0, warmup: int = 0, dirs: np.ndarray | None = None) -> dict[str, Any]:
    """Score a long/flat position series (0..1, already smoothed over its h tranches) against the one-period returns
    `r`: costs `cost_rt` % per round trip charged on turnover, IS = [warmup, is_end), OOS = [is_end, n); the honest
    benchmark is buy-and-hold scaled to the rule's average exposure in that span. `_series` carries the paths."""
    pos = _finite(pos)
    r = _finite(r).reindex(pos.index)
    n = len(pos)
    turn = pos.diff().abs().fillna(pos.abs())
    strat = pos * r - turn * (cost_rt / 100) / 2
    out: dict[str, Any] = {"h": h, "periods": n, "exposure_pct": round(float(pos.mean() * 100), 1),
                           "is_end": str(getattr(pos.index[min(is_end, n - 1)], "date", lambda: pos.index[min(is_end, n - 1)])())}
    for label, sl in (("IS", slice(warmup, is_end)), ("OOS", slice(is_end, n))):
        s, b, po = strat.iloc[sl], r.iloc[sl], pos.iloc[sl]
        ps, pb = perf(s, periods_per_year), perf(b, periods_per_year)
        if not ps:
            continue
        diff = s - b * po.mean()
        out[f"{label}_strat_cagr"] = ps["cagr"]
        out[f"{label}_strat_sharpe"] = ps["sharpe"]
        out[f"{label}_strat_maxdd"] = ps["max_dd"]
        out[f"{label}_bh_cagr"] = pb["cagr"]
        out[f"{label}_bh_sharpe"] = pb["sharpe"]
        out[f"{label}_exposure_pct"] = round(float(po.mean() * 100), 1)
        out[f"{label}_excess_vs_scaled_pa_pct"] = round(float(diff.mean() * periods_per_year * 100), 2)
        out[f"{label}_t_excess"] = round(newey_west_t(diff, max(h - 1, 0)), 2)
        if dirs is not None:
            out[f"{label}_dir_long_share_pct"] = round(float((dirs[sl] > 0).mean() * 100), 0)
    out["_series"] = {"strat": strat, "bh": r, "pos": pos}
    return out


def walk_forward_long_flat(signal: pd.Series, fwd_h: pd.Series, r_next: pd.Series, h: int, *, periods_per_year: int,
                           cost_rt: float = COST_RT, min_hist: int = 250, is_fraction: float = 0.40,
                           fixed_dir: int | None = None, refit_every: int = 1, long_cut: float = 2 / 3) -> dict[str, Any]:
    """Long/flat rule: one tranche per period held h periods (h overlapping tranches), long when the signal's expanding
    percentile is in the favourable tercile. Direction is learned from COMPLETED forward windows strictly before the
    decision (re-fitted every `refit_every` periods) unless `fixed_dir` is given. Costs: `cost_rt` % per round trip,
    charged per unit of turnover. Reports in-sample (first `is_fraction`) and out-of-sample metrics; the honest
    benchmark is buy-and-hold scaled to the rule's average exposure."""
    d = pd.DataFrame({"sig": _finite(signal), "fwd": _finite(fwd_h), "r": _finite(r_next)}).dropna(subset=["sig", "r"])
    n = len(d)
    if n < min_hist + 60:
        return {}
    is_end = int(n * is_fraction)
    sigv, fwdv = d["sig"].to_numpy(), d["fwd"].to_numpy()
    pos_tranche = np.zeros(n)
    dirs = np.zeros(n)
    d_cur = fixed_dir if fixed_dir is not None else 0
    for t in range(min_hist, n):
        if fixed_dir is None and (t - min_hist) % refit_every == 0:
            # completed pairs: the forward window of pair i ended on/before the decision t (i + h < t)
            done = max(0, t - h)
            hist, pair = sigv[:done], fwdv[:done]
            ok = ~np.isnan(pair) & ~np.isnan(hist)
            if ok.sum() >= 60:
                rho = stats.spearmanr(hist[ok], pair[ok])[0]
                d_cur = 1 if rho > 0 else -1
        if d_cur == 0:
            continue
        past = sigv[:t]
        past = past[~np.isnan(past)]
        pct = (past < sigv[t]).mean()
        dirs[t] = d_cur
        pos_tranche[t] = 1.0 if (d_cur > 0 and pct >= long_cut) or (d_cur < 0 and pct <= 1 - long_cut) else 0.0
    pos = pd.Series(pos_tranche, index=d.index).rolling(h, min_periods=1).mean()
    return evaluate_long_flat(pos, d["r"], h=h, periods_per_year=periods_per_year, cost_rt=cost_rt, is_end=is_end,
                              warmup=min_hist, dirs=dirs)


def indicator_long_flat(indicator: pd.Series, r_next: pd.Series, h: int, *, periods_per_year: int, cost_rt: float = COST_RT,
                        is_fraction: float = 0.40) -> dict[str, Any]:
    """A fixed, pre-registered rule: long (one tranche held h periods) whenever the 0/1 indicator is 1 — nothing is
    learned, so IS/OOS only separate the eras; costs and the scaled benchmark as in `evaluate_long_flat`."""
    d = pd.DataFrame({"ind": _finite(indicator), "r": _finite(r_next)}).dropna()
    n = len(d)
    if n < 60:
        return {}
    pos = d["ind"].clip(0, 1).rolling(h, min_periods=1).mean()
    return evaluate_long_flat(pos, d["r"], h=h, periods_per_year=periods_per_year, cost_rt=cost_rt, is_end=int(n * is_fraction))


def oos_halves_t(wf: dict[str, Any], h: int, split: str | pd.Timestamp | None = None) -> tuple[float, float, str]:
    """NW t of a rule's OOS excess (vs scaled B&H) in each half of the OOS span, plus the split date used. With
    `split=None` the OOS span is cut at its own midpoint observation (the plans' "both OOS halves"); a sample-half
    date would leave one OOS half a few months long when the IS fraction ends after it."""
    if not wf or "_series" not in wf:
        return float("nan"), float("nan"), ""
    s, b, po = wf["_series"]["strat"], wf["_series"]["bh"], wf["_series"]["pos"]
    oos = s.index >= pd.Timestamp(wf["is_end"])
    diff = (s - b * po[oos].mean())[oos]
    if len(diff) < 8:
        return float("nan"), float("nan"), ""
    cut = pd.Timestamp(split) if split is not None else pd.Timestamp(diff.index[len(diff) // 2 - 1])
    h1, h2 = halves(diff.index, cut)
    return newey_west_t(diff[h1], max(h - 1, 0)), newey_west_t(diff[h2], max(h - 1, 0)), str(cut.date())


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Loaders — saved research data (no network)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def load_yahoo_daily(path: Path) -> pd.DataFrame:
    """Yahoo chart CSV in either saved layout (G-STUDY `ts_utc,…,date` or G-MACRO `date,open,…`); one row per date,
    non-positive closes dropped (Yahoo pads holidays with zeros on some symbols)."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise DataNotIngested(f"{path.name}: no 'date' column")
    df["date"] = pd.to_datetime(df["date"], utc=False).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("date", keep="last").set_index("date").sort_index()
    for c in ("open", "high", "low", "close", "adjclose", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["close"].notna() & (df["close"] > 0)]
    return df


def load_fred(path: Path, series: str | None = None) -> pd.Series:
    """FRED fredgraph.csv (`observation_date,<ID>` or `date,<ID>`): a float series indexed by date, NaNs dropped."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    df = pd.read_csv(path)
    dcol = "observation_date" if "observation_date" in df.columns else "date"
    vcol = series or next(c for c in df.columns if c != dcol)
    s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").values, index=pd.to_datetime(df[dcol]), name=vcol)
    return s.dropna().sort_index()


def load_gld_archive(path: Path) -> pd.DataFrame:
    """SPDR Gold Shares historical archive XLSX (E1): `tonnes`, `gld_close`, `ounces` by date; 'US Holiday' rows dropped.
    Display-only data under SPDR's disclaimer: the study reads it, nothing re-serves it."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    x = pd.ExcelFile(path)
    sheet = next((s for s in x.sheet_names if "Archive" in s), x.sheet_names[-1])
    df = x.parse(sheet, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    out = pd.DataFrame({"date": pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce"),
                        "tonnes": pd.to_numeric(df["Tonnes of Gold"], errors="coerce"),
                        "gld_close": pd.to_numeric(df["Closing Price"], errors="coerce"),
                        "ounces": pd.to_numeric(df.get("Total Ounces of Gold in the Trust"), errors="coerce")})
    out = out.dropna(subset=["date", "tonnes"]).drop_duplicates("date", keep="last").set_index("date").sort_index()
    return out


def load_worldbank_monthly(path: Path) -> pd.Series:
    """World Bank CMO monthly gold average ($/oz) as saved by G-MACRO (`date,gold,silver,platinum`)."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    df = pd.read_csv(path, parse_dates=["date"])
    s = pd.Series(pd.to_numeric(df["gold"], errors="coerce").values, index=df["date"], name="gold")
    return s.dropna().sort_index()


def load_wgc_fsapi(path: Path, cadence: str = "Weekly") -> dict[str, pd.DataFrame]:
    """WGC Goldhub chart JSON (E5): the `holdings-chart2` table shape (`columns`/`set`) and the `flows-chart2`
    series shape (`series.tonnes[]`), returned as DataFrames by region in tonnes for one cadence."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("chartData", {}).get("data", {})
    if cadence not in data:
        raise DataNotIngested(f"{path.name}: no '{cadence}' block")
    block = data[cadence]
    out: dict[str, pd.DataFrame] = {}
    if "tonnes" in block and isinstance(block["tonnes"], dict) and "set" in block["tonnes"]:
        cols = [str(c) for c in block["tonnes"]["columns"]]
        df = pd.DataFrame(block["tonnes"]["set"], columns=cols)
        df["date"] = pd.to_datetime(df[cols[0]], unit="ms").dt.normalize()
        out["holdings"] = df.drop(columns=[cols[0]]).set_index("date").apply(pd.to_numeric, errors="coerce").sort_index()
    if "series" in block and "tonnes" in block["series"]:
        frames = {}
        for s in block["series"]["tonnes"]:
            pts = pd.DataFrame(s["data"], columns=["ms", "v"])
            frames[str(s["name"])] = pd.Series(pd.to_numeric(pts["v"], errors="coerce").values,
                                               index=pd.to_datetime(pts["ms"], unit="ms").dt.normalize())
        out["flows"] = pd.DataFrame(frames).sort_index()
    if not out:
        raise DataNotIngested(f"{path.name}: neither a holdings table nor a flows series")
    return out


def load_cme_family_oi_csv(path: Path) -> pd.DataFrame:
    """G-CME's product-OI CSV (`trade_date,sym,globex,otc,total,oi`), one row per product per trade date."""
    if not path.exists():
        raise DataNotIngested(f"missing {path}")
    df = pd.read_csv(path)
    need = {"trade_date", "sym", "oi"}
    if not need.issubset(df.columns):
        raise DataNotIngested(f"{path.name}: expected columns {sorted(need)}")
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    df["oi"] = pd.to_numeric(df["oi"], errors="coerce")
    return df.dropna(subset=["oi"]).sort_values(["sym", "trade_date"])


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Loaders — data-service gold tables (read-only, on a snapshot copy; never the live file)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def is_live_busy(when: datetime | pd.Timestamp | None = None) -> bool:
    """True inside the IST busy windows on a weekday (`LIVE_BUSY_WINDOWS_IST`): the data-service is logging in, ingesting
    the session or running the EOD pipeline, and a 4.4 GB copy of its file must not compete with that I/O."""
    now = pd.Timestamp(when) if when is not None else pd.Timestamp.now(tz=IST)
    now = now.tz_convert(IST) if now.tzinfo is not None else now.tz_localize(IST)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return any(lo <= t < hi for lo, hi in LIVE_BUSY_WINDOWS_IST)


def is_live_store(db_path: Path) -> bool:
    """Whether a DuckDB path is the data-service's live store (anything under `data/`), as opposed to a fixture or a copy."""
    try:
        Path(db_path).resolve().relative_to(LIVE_DATA_DIR.resolve())
        return True
    except ValueError:
        return False


@contextmanager
def open_snapshot(db_path: Path, tmp_dir: Path | None = None, *, allow_market_hours: bool = False, live: bool | None = None,
                  now: datetime | pd.Timestamp | None = None) -> Iterator[Any]:
    """Copy a DuckDB file (and its WAL) to a temp directory, open the copy read-only and REMOVE the copy on exit, so a
    study never holds a lock on, writes to, or leaves a 4.4 GB copy of the data-service's database behind (the pattern
    of scripts/fii_positioning_study.py, as a context manager).

    Refuses (`LiveFileBusy`) to copy the LIVE store (`live`, default: the path is under `data/`) inside an IST busy window
    unless `allow_market_hours`; refuses (`SnapshotSpace`) when the temp location lacks the room for a full copy. With
    `tmp_dir` the caller owns the directory: only the snapshot files are removed."""
    import duckdb

    db_path = Path(db_path)
    if not db_path.exists():
        raise DataNotIngested(f"no DuckDB file at {db_path}")
    if (is_live_store(db_path) if live is None else live) and not allow_market_hours and is_live_busy(now):
        raise LiveFileBusy(f"{db_path} is the live store and it is an IST busy window; re-run later or pass --allow-market-hours")
    wal = Path(f"{db_path}.wal")
    need = db_path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    own_dir = tmp_dir is None
    tmp = Path(tempfile.mkdtemp(prefix="gold_study_")) if own_dir else Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    snap = tmp / "snapshot.duckdb"
    con = None
    try:
        free = shutil.disk_usage(tmp).free
        if free < need * SNAPSHOT_HEADROOM + SNAPSHOT_MIN_FREE_BYTES:
            raise SnapshotSpace(f"{tmp}: {free / 1e9:.1f} GB free, {need * SNAPSHOT_HEADROOM / 1e9:.1f} GB needed for a full snapshot")
        shutil.copy2(db_path, snap)
        if wal.exists():
            shutil.copy2(wal, f"{snap}.wal")
        con = duckdb.connect(str(snap), read_only=True)
        yield con
    finally:
        if con is not None:
            con.close()
        for f in (snap, Path(f"{snap}.wal")):
            f.unlink(missing_ok=True)
        if own_dir:
            shutil.rmtree(tmp, ignore_errors=True)


def table_exists(con, table: str) -> bool:
    row = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()
    return bool(row and row[0])


def read_gold_series(con, series_ids: list[str], asof: str | None = None) -> pd.DataFrame:
    """Point-in-time read of `gold_series`: for each (series_id, report_date) the latest row released on or before
    `asof` (default: everything), i.e. the vintage a reader would have seen — never a later revision."""
    if not table_exists(con, "gold_series"):
        raise DataNotIngested("table gold_series")
    placeholders = ", ".join("?" for _ in series_ids)
    params: list[Any] = list(series_ids)
    asof_sql = ""
    if asof:
        asof_sql = " AND release_at <= ?"
        params.append(pd.Timestamp(asof).to_pydatetime())
    sql = (f"SELECT series_id, report_date, value, release_at FROM gold_series WHERE series_id IN ({placeholders}){asof_sql} "
           "QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, report_date ORDER BY release_at DESC) = 1 "
           "ORDER BY series_id, report_date")
    df = con.execute(sql, params).df()
    if df.empty:
        raise DataNotIngested(f"gold_series rows for {series_ids}")
    df["report_date"] = pd.to_datetime(df["report_date"])
    return df


def read_gold_series_vintages(con, series_ids: list[str]) -> pd.DataFrame:
    """EVERY stored vintage of `gold_series` for the ids (no QUALIFY): the input of a point-in-time panel, where each
    decision picks the vintage it could see (`pit_lagged`) instead of one global as-of."""
    if not table_exists(con, "gold_series"):
        raise DataNotIngested("table gold_series")
    placeholders = ", ".join("?" for _ in series_ids)
    df = con.execute(f"SELECT series_id, report_date, value, release_at, release_source FROM gold_series "
                     f"WHERE series_id IN ({placeholders}) ORDER BY series_id, report_date, release_at", list(series_ids)).df()
    if df.empty:
        raise DataNotIngested(f"gold_series rows for {series_ids}")
    df["report_date"] = pd.to_datetime(df["report_date"])
    df["release_at"] = pd.to_datetime(df["release_at"])
    return df


def read_cme_product_oi(con, product_codes: tuple[str, ...] = ("GC",), exchange: str = "COMEX") -> pd.DataFrame:
    """Daily futures open interest by product from `gold_cme_daily_voi` (C1), one row per trade date per product."""
    if not table_exists(con, "gold_cme_daily_voi"):
        raise DataNotIngested("table gold_cme_daily_voi")
    placeholders = ", ".join("?" for _ in product_codes)
    df = con.execute(f"SELECT trade_date, product_code AS sym, open_interest AS oi, total_volume AS total FROM gold_cme_daily_voi "
                     f"WHERE exchange = ? AND fut_or_opt IN ('F', 'FUT', 'Futures') AND product_code IN ({placeholders}) "
                     "ORDER BY product_code, trade_date", [exchange, *product_codes]).df()
    if df.empty:
        raise DataNotIngested(f"gold_cme_daily_voi rows for {product_codes}")
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    return df


def read_daily_bars(con, symbol: str) -> pd.Series:
    """Close series from `gold_daily_bars` for one symbol (any source; latest `first_seen_at` wins per date)."""
    if not table_exists(con, "gold_daily_bars"):
        raise DataNotIngested("table gold_daily_bars")
    df = con.execute("SELECT trade_date, close FROM gold_daily_bars WHERE symbol = ? "
                     "QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY first_seen_at DESC) = 1 ORDER BY trade_date",
                     [symbol]).df()
    if df.empty:
        raise DataNotIngested(f"gold_daily_bars rows for {symbol}")
    s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values, index=pd.to_datetime(df["trade_date"]).dt.normalize())
    return s.dropna().sort_index()


def read_etf_holdings(con, fund: str = "GLD") -> pd.DataFrame:
    """`gold_etf_holdings` tonnes by report_date for one fund with the stored `release_at` (the table's primary key is
    (report_date, fund, source), so a re-fetch overwrites in place — there is one vintage per source; where two sources
    carry the same date the EARLIEST release wins, the value a reader had first). The study enters after `release_at`."""
    if not table_exists(con, "gold_etf_holdings"):
        raise DataNotIngested("table gold_etf_holdings")
    df = con.execute("SELECT report_date, tonnes, nav, release_at FROM gold_etf_holdings WHERE fund = ? AND tonnes IS NOT NULL "
                     "QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date ORDER BY release_at ASC) = 1 ORDER BY report_date",
                     [fund]).df()
    if df.empty:
        raise DataNotIngested(f"gold_etf_holdings rows for {fund}")
    df["date"] = pd.to_datetime(df["report_date"]).dt.normalize()
    out = df.set_index("date")[["tonnes", "nav"]].astype(float)
    out["release_at"] = pd.to_datetime(df["release_at"]).to_numpy()
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Rendering — tables, the FINDINGS row (fii_positioning format), JSON
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def fmt(v: Any, digits: int = 2) -> str:
    """Compact cell text: signed numbers use U+2212 for the minus, NaN/None render empty."""
    if v is None:
        return ""
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return ""
        s = f"{v:.{digits}f}"
        return s.replace("-", "−")
    if isinstance(v, (int, np.integer)):
        return str(int(v)).replace("-", "−")
    return str(v)


def md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)
    body = "\n".join("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |" for r in rows)
    return head + ("\n" + body if body else "")


@dataclass(frozen=True)
class Row:
    """One verdict row of a study, rendered in both table shapes: `signal`, the `result` text WITHOUT the verdict, the
    two halves and the `verdict` cell (PASS / CONTEXT-ONLY / FAIL / VOID / PENDING, optionally qualified, e.g.
    'FAIL (all three)')."""

    signal: str
    result: str
    half1: str
    half2: str
    verdict: str


def _cell(text: str) -> str:
    """Cell text safe inside a Markdown table: a literal `|` (as in `|t| ≥ 2`) is escaped."""
    return text.replace("\\|", "|").replace("|", "\\|")


def study_row(row: Row) -> str:
    """The STUDY PAGE shape (`<study>/FINDINGS.md`, as `reports/fii_positioning/FINDINGS.md`): 3 columns, the verdict
    embedded in the result cell: `| Signal | result → **VERDICT** | h1 / h2 |`."""
    return f"| {_cell(row.signal)} | {_cell(row.result)} → **{_cell(row.verdict)}** | {_cell(row.half1)} / {_cell(row.half2)} |"


def aggregate_row(study: str, row: Row) -> str:
    """The AGGREGATE shape of `reports/gold_program/FINDINGS.md` (B5's table, header
    `| Study · signal (known at release) | Result | Both halves | Verdict |`): 4 columns, the study id prefixed, the
    verdict in its own cell. Paste-ready."""
    return f"| {study} · {_cell(row.signal)} | {_cell(row.result)} | {_cell(row.half1)} / {_cell(row.half2)} | **{_cell(row.verdict)}** |"


def table_cells(line: str) -> list[str]:
    """The cells of one rendered row (an escaped `\\|` is text, not a separator) — what a gate counts."""
    marker = "\x00"
    inner = line.replace("\\|", marker).strip().removeprefix("|").removesuffix("|")
    return [c.strip().replace(marker, "|") for c in inner.split("|")]


def findings_row(signal: str, result: str, half1: str, half2: str) -> str:
    """A 3-column row from already-rendered cells (kept for callers that embed the verdict themselves)."""
    return f"| {signal} | {result} | {half1} / {half2} |"


def findings_pending_row(study: str, question: str, needs: str, shape: str = "aggregate") -> str:
    """The row a pre-registered study contributes to the aggregate FINDINGS.md before its data is stored (4 columns;
    `shape='study'` gives the 3-column page form)."""
    row = Row(question, f"pre-registered, not run: needs {needs}", "—", "—", PENDING)
    return aggregate_row(study, row) if shape == "aggregate" else study_row(row)


def findings_rows_md(study: str, rows: list[Row]) -> str:
    """`<study>/FINDINGS_ROW.md`: the aggregate-shape rows (one per line) to paste into reports/gold_program/FINDINGS.md."""
    return "\n".join(aggregate_row(study, r) for r in rows) + "\n"


def findings_template(study: str, title: str, date_str: str, data_line: str, verdict_line: str, rows: list[str | Row],
                      bullets: list[str], use_line: str, script: str) -> str:
    """The FINDINGS.md skeleton every gold study fills (header, data, bold verdict, 3-column table, bullets, 'Use:' line).
    `rows` may be `Row`s (rendered in the study-page shape) or already-rendered lines."""
    lines = [study_row(r) if isinstance(r, Row) else r for r in rows]
    table_rows = "\n".join(lines) if lines else "| (no signal tested) | — | — / — |"
    bl = "\n".join(f"- {b}" for b in bullets)
    return (f"# {title}: findings ({date_str})\n\n"
            f"Pre-registered (`PLAN.md`); tables in `REPORT.md`; script `{script}`. {data_line}\n\n"
            f"**Verdict: {verdict_line}**\n\n"
            "| Signal | Result (full sample) | Both halves |\n|---|---|---|\n"
            f"{table_rows}\n\n{bl}\n- **Use:** {use_line}\n")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False), encoding="utf-8")


def now_label() -> str:
    return pd.Timestamp.now().strftime("%d %b %Y")
