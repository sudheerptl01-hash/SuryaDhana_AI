"""Shared machinery of the pre-registered Terminal v2 studies (`reports/terminal_v2/studies/*/PLAN.md`).

The gold program's study kit (`scripts/gold_studies/common.py`) is reused, not copied: Newey-West t, expanding terciles,
the long/flat evaluator, the snapshot opener and the FINDINGS row renderers come from there. What is new here:

* **the signed verdict rule** of the Terminal v2 plans (`signed_verdict`): a graded statistic carries a REGISTERED SIGN
  (the claim's direction); PASS needs t >= 2 in that direction in the full sample AND both halves AND (for a tradable
  claim) its after-cost traded leg; a t >= 2 against the sign is a FAIL; a statistic may have a lower ceiling
  (`PASS as description`, `CONTEXT-ONLY`); negative controls VOID a statistic they shadow, structural controls CAP it;
* `ols_hac` — multivariate OLS with a Bartlett Newey-West covariance (no statsmodels in the shared environment);
* point-in-time forward windows: every forward quantity starts at the close of T+1 (the F&O file of T lands 20:10 IST,
  the drivers job runs 19:25), `forward_rv` / `forward_ret` / `trailing_rv`;
* the placebo transforms of the plans (`placebo_lag`, `circular_shift`, `permute`);
* costs: cash legs through the frozen `shared/trading_costs.py` (`cash_round_trip_pct`), option legs through the dated
  `FnoCosts` schedule (trading_costs.py prices cash equity only), never below the 0.15 % project floor per order;
* `open_inputs` — a DuckDB opened READ-ONLY: a scratch inputs store directly, the live `data/market.duckdb` only through
  the gold snapshot copier (refused inside the IST busy windows);
* honest exits (3 not ingested, 4 insufficient / a data-quality gate failed, 5 live file busy) and the output writer
  that stamps PROVISIONAL on every file when the inputs are a scratch recomputation.

No network access; nothing here writes under `data/`.
"""
from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))                    # `gold_studies` is a sibling package; appended, never shadowing

from gold_studies import common as GC
from gold_studies.common import Row, aggregate_row, fmt, md_table, study_row

__all__ = ["Row", "aggregate_row", "fmt", "md_table", "study_row"]   # re-exported from the gold kit for the studies

DATA_SERVICE = ROOT / "services" / "data-service"
STUDIES_DIR = ROOT / "reports" / "terminal_v2" / "studies"
FO_ROOT = ROOT / "data" / "nse_archive" / "fo"
INDEX_CLOSE_CSV = ROOT / "data" / "nse_archive" / "derived" / "index_valuation_history.csv"
PARTICIPANT_ROOT = ROOT / "data" / "nse_archive" / "participant_oi"
FINANCIALS_ROOT = ROOT / "data" / "nse_archive" / "financials"
R_IV_COMPARE = ROOT / "reports" / "terminal_v2" / "R-IV" / "iv_compare_NIFTY.csv"
NIFTY50_LIST = ROOT / "reports" / "terminal_v2" / "R-DRIVERS" / "evidence" / "ind_nifty50list.csv"
SCRATCH_DIR = Path.home() / ".suryadhana_pm_scratch" / "v2" / "B8-STUDIES"
DEFAULT_INPUTS = SCRATCH_DIR / "inputs.duckdb"
LIVE_DB = GC.LIVE_DB

INDEX_NAME: dict[str, str] = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}
MODEL_VERSION = "b76-pcp-v1"
SEED = 20261105
T_PASS = GC.T_PASS                  # 2.0
HORIZON = 20                        # sessions
ENTRY_SHIFT = 1                     # act at the close of T+1
PLACEBO_LAG = 250
WARMUP = 252                        # expanding terciles / percentile windows
CASH_TRANCHE_INR = 100_000
FLOOR_PCT = GC.COST_RT              # 0.15 % — the project floor

PASS, CONTEXT_ONLY, FAIL, VOID, PENDING = GC.PASS, GC.CONTEXT_ONLY, GC.FAIL, GC.VOID, GC.PENDING
PASS_DESC = "PASS as description"
EXIT_NOT_INGESTED, EXIT_INSUFFICIENT, EXIT_LIVE_BUSY = GC.EXIT_NOT_INGESTED, GC.EXIT_INSUFFICIENT, GC.EXIT_LIVE_BUSY
DataNotIngested, InsufficientHistory, LiveFileBusy = GC.DataNotIngested, GC.InsufficientHistory, GC.LiveFileBusy
newey_west_t, plain_t, expanding_tercile = GC.newey_west_t, GC.plain_t, GC.expanding_tercile
evaluate_long_flat, oos_halves_t = GC.evaluate_long_flat, GC.oos_halves_t
not_ingested, insufficient, live_busy = GC.not_ingested, GC.insufficient, GC.live_busy

PROVISIONAL_BANNER = ("**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store "
                      "(PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. "
                      "No study result reaches a badge without the PM.")


def ensure_data_service_path() -> None:
    """Make the production packages (`fo_iv`, `index_drivers`, `data_health`, `storage`) and `shared` importable."""
    for p in (str(ROOT), str(DATA_SERVICE)):
        if p not in sys.path:
            sys.path.insert(0, p)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _isnan(v: Any) -> bool:
    return v is None or (isinstance(v, (float, np.floating)) and math.isnan(float(v)))


def ols_hac(y: pd.Series, x: pd.DataFrame | pd.Series, lags: int) -> dict[str, Any]:
    """OLS of y on [1, x…] with a Bartlett Newey-West covariance (HAC). Rows with any non-finite value are dropped.
    Returns {n, coef{name}, t{name}, r2}; empty coef/t below k + 10 observations."""
    xf = x.to_frame() if isinstance(x, pd.Series) else x
    d = pd.concat([pd.Series(y, dtype=float).rename("__y"), xf.astype(float)], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    names = ["const", *[str(c) for c in xf.columns]]
    n, k = len(d), len(names)
    if n < k + 10:
        return {"n": n, "coef": {}, "t": {}, "r2": float("nan")}
    yy = d["__y"].to_numpy(dtype=float)
    xm = np.column_stack([np.ones(n), d[xf.columns].to_numpy(dtype=float)])
    with np.errstate(all="ignore"):
        xtx_inv = np.linalg.pinv(xm.T @ xm)
        beta = xtx_inv @ (xm.T @ yy)
        e = yy - xm @ beta
        u = xm * e[:, None]
        s = u.T @ u
        for lag in range(1, min(int(lags), n - 1) + 1):
            w = 1.0 - lag / (lags + 1.0)
            g = u[lag:].T @ u[:-lag]
            s += w * (g + g.T)
        v = xtx_inv @ s @ xtx_inv
        se = np.sqrt(np.clip(np.diag(v), 0.0, None))
        tt = np.where(se > 0, beta / np.where(se > 0, se, 1.0), np.nan)
        ss_tot = float(((yy - yy.mean()) ** 2).sum())
        r2 = 1.0 - float((e ** 2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    return {"n": n, "coef": {nm: float(b) for nm, b in zip(names, beta, strict=True)},
            "t": {nm: float(t) for nm, t in zip(names, tt, strict=True)}, "r2": r2}


def half_masks(index: pd.Index, split: str | pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """Boolean arrays for the two halves (the first half ends ON the split date)."""
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    h1 = np.asarray(idx <= pd.Timestamp(split))
    return h1, ~h1


def slope_by_halves(y: pd.Series, x: pd.DataFrame | pd.Series, name: str, lags: int, split: str | pd.Timestamp) -> dict[str, Any]:
    """The slope of `name` with its HAC t in the full sample and each half (controls in `x` re-estimated per half)."""
    xf = x.to_frame() if isinstance(x, pd.Series) else x
    out: dict[str, Any] = {}
    full = ols_hac(y, xf, lags)
    h1, h2 = half_masks(xf.index, split)
    r1 = ols_hac(y[h1], xf[h1], lags)
    r2 = ols_hac(y[h2], xf[h2], lags)
    for tag, r in (("full", full), ("h1", r1), ("h2", r2)):
        out[f"b_{tag}"] = r["coef"].get(name, float("nan"))
        out[f"t_{tag}"] = r["t"].get(name, float("nan"))
        out[f"n_{tag}"] = r["n"]
    out["r2_full"] = full["r2"]
    return out


def mean_by_halves(x: pd.Series, lags: int, split: str | pd.Timestamp, *, plain: bool = False) -> dict[str, Any]:
    """Mean and its t (Newey-West with `lags`, or the plain t for non-overlapping events) in the full sample and halves."""
    s = pd.Series(x, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    h1, h2 = half_masks(s.index, split)
    out: dict[str, Any] = {}
    for tag, part in (("full", s), ("h1", s[h1]), ("h2", s[h2])):
        out[f"mean_{tag}"] = float(part.mean()) if len(part) else float("nan")
        out[f"t_{tag}"] = (plain_t(part) if plain else newey_west_t(part, lags)) if len(part) >= 4 else float("nan")
        out[f"n_{tag}"] = len(part)
    return out


def meets(t_full: float, t_h1: float, t_h2: float, sign: int, t_pass: float = T_PASS) -> bool:
    """The PASS condition of a statistic: t >= 2 in the registered direction in the full sample and both halves (sign 0 =
    two-sided: |t| >= 2 everywhere with one common sign). NaN never passes."""
    vals = [t_full, t_h1, t_h2]
    if any(_isnan(v) for v in vals):
        return False
    if sign == 0:
        return all(abs(v) >= t_pass for v in vals) and len({np.sign(v) for v in vals}) == 1
    return all(sign * v >= t_pass for v in vals)


def full_only(t_full: float, sign: int, t_pass: float = T_PASS) -> bool:
    if _isnan(t_full):
        return False
    return abs(t_full) >= t_pass if sign == 0 else sign * t_full >= t_pass


def signed_verdict(t_full: float, t_h1: float, t_h2: float, sign: int, *, traded_ok: bool | None = None,
                   ceiling: str = PASS) -> str:
    """The Terminal v2 verdict of one graded statistic (PLANs, 'Verdict rule').

    PASS needs `meets(...)` AND `traded_ok is True` (a tradable claim must pay after costs); a statistic that meets the
    condition without a paying leg is CONTEXT-ONLY; `ceiling` caps what a statistic can reach (`PASS_DESC` for a
    description, CONTEXT_ONLY for an information statistic or a two-sided one). t >= 2 in the full sample only →
    CONTEXT-ONLY; everything else (including t >= 2 AGAINST the registered sign) → FAIL."""
    if sign == 0 and ceiling == PASS:
        ceiling = CONTEXT_ONLY                         # nothing registered → nothing can PASS
    if meets(t_full, t_h1, t_h2, sign):
        if ceiling == PASS:
            return PASS if traded_ok is True else CONTEXT_ONLY
        return ceiling
    if full_only(t_full, sign):
        return CONTEXT_ONLY
    return FAIL


def against_sign_note(t_full: float, t_h1: float, t_h2: float, sign: int) -> list[str]:
    """A statistic that is strong in the OPPOSITE direction stays a FAIL (the opposite claim was never registered); the
    report says so, because it is still a description worth knowing."""
    if sign == 0:
        return []
    if meets(t_full, t_h1, t_h2, -sign):
        return [("strong AGAINST the registered sign in the full sample and both halves (a description, never a signal: "
                 "the opposite claim was not pre-registered)")]
    if full_only(t_full, -sign):
        return ["|t| ≥ 2 against the registered sign in the full sample only"]
    return []


def traded_leg_ok(stats: dict[str, Any], sign: int = 1) -> bool:
    """A traded leg's after-cost condition: its t (signed) >= 2 in the full span and both halves."""
    return meets(stats.get("t_full", float("nan")), stats.get("t_h1", float("nan")), stats.get("t_h2", float("nan")), sign)


def apply_controls(verdict: str, *, voided_by: list[str], capped_by: list[str]) -> tuple[str, list[str]]:
    """A negative control meeting the statistic's condition VOIDs it; a structural control CAPS a PASS (either kind)
    at CONTEXT-ONLY. Returns (verdict, notes)."""
    notes: list[str] = []
    if voided_by:
        notes.append("void: " + ", ".join(voided_by))
        return VOID, notes
    if capped_by and verdict in (PASS, PASS_DESC):
        notes.append("capped: " + ", ".join(capped_by))
        return CONTEXT_ONLY, notes
    return verdict, notes


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Point-in-time windows and placebo transforms
# ─────────────────────────────────────────────────────────────────────────────────────────────────

ANNUALISE = math.sqrt(252.0)


def log_returns(close: pd.Series) -> pd.Series:
    c = pd.Series(close, dtype=float)
    with np.errstate(all="ignore"):
        return np.log(c / c.shift(1)).replace([np.inf, -np.inf], np.nan)


def trailing_rv(close: pd.Series, n: int = HORIZON) -> pd.Series:
    """√252 × 100 × stdev of the n log returns ENDING at each date (production `realised.close_to_close`, full window)."""
    return log_returns(close).rolling(n, min_periods=n).std(ddof=1) * ANNUALISE * 100.0


def forward_rv(close: pd.Series, h: int = HORIZON, shift: int = ENTRY_SHIFT) -> pd.Series:
    """RV of the h log returns from close(T+shift) to close(T+shift+h), indexed at T (nothing of T's own close or
    before enters)."""
    return trailing_rv(close, h).shift(-(shift + h))


def forward_ret(close: pd.Series, h: int = HORIZON, shift: int = ENTRY_SHIFT) -> pd.Series:
    """100 × (close(T+shift+h) / close(T+shift) − 1), indexed at T."""
    c = pd.Series(close, dtype=float)
    return (c.shift(-(shift + h)) / c.shift(-shift) - 1.0) * 100.0


def placebo_lag(s: pd.Series, k: int = PLACEBO_LAG) -> pd.Series:
    return pd.Series(s, dtype=float).shift(k)


def circular_shift(s: pd.Series, k: int | None = None) -> pd.Series:
    """Rotate the values by k positions (default: half the length) — keeps the autocorrelation, breaks the alignment."""
    v = pd.Series(s, dtype=float).to_numpy()
    k = len(v) // 2 if k is None else k
    return pd.Series(np.roll(v, k), index=s.index)


def permute(s: pd.Series, seed: int = SEED) -> pd.Series:
    """The non-NaN values permuted across their own positions (fixed seed)."""
    x = pd.Series(s, dtype=float).copy()
    ok = x.notna().to_numpy()
    vals = x.to_numpy()[ok]
    rng = np.random.default_rng(seed)
    out = x.to_numpy().copy()
    out[ok] = rng.permutation(vals)
    return pd.Series(out, index=s.index)


def top_tercile(s: pd.Series, min_hist: int = WARMUP) -> pd.Series:
    """1.0 when s is in its expanding top tercile (cut-off from strictly earlier values, ≥ min_hist of them), 0.0 when
    not, NaN during the warm-up."""
    b = expanding_tercile(pd.Series(s, dtype=float), min_hist)
    out = pd.Series(np.where(b == "top", 1.0, 0.0), index=s.index, dtype=float)
    out[b.isna()] = np.nan
    return out


def bottom_tercile(s: pd.Series, min_hist: int = WARMUP) -> pd.Series:
    b = expanding_tercile(pd.Series(s, dtype=float), min_hist)
    out = pd.Series(np.where(b == "bottom", 1.0, 0.0), index=s.index, dtype=float)
    out[b.isna()] = np.nan
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Costs
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def cash_round_trip_pct(notional: float = CASH_TRANCHE_INR) -> float:
    """The frozen cash-equity model (`shared/trading_costs.py`, COST_PROFILE default): delivery round trip in % of the
    tranche, never below the project floor."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shared.trading_costs import default_model

    return max(FLOOR_PCT, float(default_model().round_trip_pct(notional, "delivery")))


@dataclass(frozen=True)
class FnoCosts:
    """Dated NSE F&O option-order schedule (Nov 2026, the builder's reading — verify against a contract note), all in % of
    the order's premium except `stt_exercise_pct` (of the intrinsic value of an exercised leg). `shared/trading_costs.py`
    prices cash equity only and is frozen, so the studies carry this schedule; a lower true schedule only makes a PASS
    easier, so a FAIL stands and a PASS is re-run on the owner's numbers."""

    as_of: str = "2026-11 (B8 reading; verify against a contract note)"
    stt_sell_pct: float = 0.15
    stt_exercise_pct: float = 0.15
    exchange_pct: float = 0.03503
    sebi_pct: float = 0.0001
    stamp_buy_pct: float = 0.003
    gst_pct: float = 18.0
    brokerage_pct: float = 0.10          # ₹20 per order on a ≈ ₹20,000 lot premium
    half_spread_pct: float = 0.50
    floor_pct: float = FLOOR_PCT

    def order_pct(self, side: str) -> float:
        base = self.exchange_pct + self.sebi_pct + self.brokerage_pct
        statutory = self.stt_sell_pct if side == "sell" else self.stamp_buy_pct
        gst = (self.brokerage_pct + self.exchange_pct + self.sebi_pct) * self.gst_pct / 100.0
        return max(self.floor_pct, base + statutory + gst + self.half_spread_pct)

    def order_cost(self, premium: float, side: str) -> float:
        return abs(float(premium)) * self.order_pct(side) / 100.0

    def exercise_cost(self, intrinsic: float) -> float:
        return max(0.0, float(intrinsic)) * self.stt_exercise_pct / 100.0


FNO = FnoCosts()


def straddle_to_expiry_pnl_pct(call: float, put: float, strike: float, forward: float, settle: float,
                               costs: FnoCosts = FNO) -> float:
    """Short ATM straddle sold at (call, put) and held to expiry, settled on the index close: P&L in % of the forward
    after the two sell orders and the exercise STT on the leg that finishes in the money."""
    intrinsic = abs(float(settle) - float(strike))
    gross = float(call) + float(put) - intrinsic
    cost = costs.order_cost(call, "sell") + costs.order_cost(put, "sell") + costs.exercise_cost(intrinsic)
    return (gross - cost) / float(forward) * 100.0


def straddle_one_session_pnl_pct(call0: float, put0: float, call1: float, put1: float, forward: float,
                                 costs: FnoCosts = FNO) -> float:
    """Short straddle sold at (call0, put0), bought back at (call1, put1): P&L in % of the forward after four orders."""
    gross = (float(call0) + float(put0)) - (float(call1) + float(put1))
    cost = (costs.order_cost(call0, "sell") + costs.order_cost(put0, "sell")
            + costs.order_cost(call1, "buy") + costs.order_cost(put1, "buy"))
    return (gross - cost) / float(forward) * 100.0


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Inputs (read-only) and outputs
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def is_live_db(path: Path) -> bool:
    try:
        return Path(path).expanduser().resolve() == LIVE_DB.resolve()
    except OSError:
        return False


@contextmanager
def open_inputs(db_path: Path | str, *, allow_market_hours: bool = False, now: Any = None) -> Iterator[Any]:
    """A read-only DuckDB connection to the inputs. The live `data/market.duckdb` is never opened in place: it goes
    through the gold snapshot copier (refused inside the IST busy windows → `LiveFileBusy`). Anything else (a scratch
    inputs store, an evening snapshot, a test fixture) is opened read-only directly — nothing is ever written."""
    import duckdb

    p = Path(db_path).expanduser()
    if not p.exists():
        raise DataNotIngested(f"no DuckDB file at {p}")
    if is_live_db(p):
        with GC.open_snapshot(p, allow_market_hours=allow_market_hours, now=now, live=True) as con:
            yield con
        return
    con = duckdb.connect(str(p), read_only=True)
    try:
        yield con
    finally:
        con.close()


def table_exists(con: Any, table: str) -> bool:
    return GC.table_exists(con, table)


def require(con: Any, table: str, what: str = "") -> None:
    if not table_exists(con, table):
        raise DataNotIngested(f"table {table}" + (f" ({what})" if what else ""))


def _clean(obj: Any) -> Any:
    """JSON-safe: NaN / ±inf → None, numpy scalars → Python, dates → ISO."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if not math.isfinite(f) else round(f, 6)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), indent=1, ensure_ascii=False, sort_keys=False), encoding="utf-8")


def default_results_dir(study_dir: Path) -> Path:
    """Per-session frames carry NSE prices (index closes, option closes, futures high / low): NSE's archive terms are
    personal use, no redistribution, and the repository is public — so they go to the scratch area, never under reports/."""
    return SCRATCH_DIR / "results" / study_dir.name


def write_outputs(study_dir: Path, *, summary: dict[str, Any], report_md: str, findings_md: str, findings_row_md: str,
                  results: dict[str, pd.DataFrame], provisional: bool, results_dir: Path | None = None) -> None:
    """summary.json, REPORT.md, FINDINGS.md, FINDINGS_ROW.md under `study_dir` and the per-session `results` CSVs under
    `results_dir` (default: the scratch area, see `default_results_dir`); every Markdown file opens with the PROVISIONAL
    banner when `provisional`."""
    study_dir.mkdir(parents=True, exist_ok=True)
    banner = (PROVISIONAL_BANNER + "\n\n") if provisional else ""
    res = results_dir if results_dir is not None else default_results_dir(study_dir)
    summary = {**summary, "provisional": bool(provisional), "results_dir": display_path(res)}
    write_json(study_dir / "summary.json", summary)
    for name, text in (("REPORT.md", report_md), ("FINDINGS.md", findings_md), ("FINDINGS_ROW.md", findings_row_md)):
        body = text if not banner else _insert_banner(text, banner)
        (study_dir / name).write_text(body, encoding="utf-8")
    res.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        df.to_csv(res / f"{name}.csv", index=True)


def _insert_banner(text: str, banner: str) -> str:
    """The banner right under the first heading (or at the top)."""
    lines = text.split("\n", 1)
    if lines and lines[0].startswith("# "):
        rest = lines[1] if len(lines) > 1 else ""
        return f"{lines[0]}\n\n{banner}{rest.lstrip(chr(10))}"
    return banner + text


def status_line(study: str, status: str, needs: str = "", how: str = "", detail: str = "") -> str:
    return GC.Status(study, status, needs, how, detail).to_json()


def tstr(t: float) -> str:
    return "—" if _isnan(t) else fmt(float(t), 2)


def verdict_row(signal: str, stats: dict[str, Any], verdict: str, *, kind: str = "b", extra: str = "") -> Row:
    """A FINDINGS Row from a slope / mean result dict (`b_*`/`mean_*`, `t_*`)."""
    key = "b" if kind == "b" else "mean"
    res = f"{key} {fmt(stats.get(f'{key}_full'), 3)} (t {tstr(stats.get('t_full', float('nan')))}, n {stats.get('n_full', 0)})"
    if extra:
        res += "; " + extra

    def half(tag: str) -> str:
        if not stats.get(f"n_{tag}"):
            return "— (no observation)"
        return f"{key} {fmt(stats.get(f'{key}_{tag}'), 3)} (t {tstr(stats.get(f't_{tag}', float('nan')))})"

    return Row(signal, res, half("h1"), half("h2"), verdict)


def display_path(p: Path | str) -> str:
    """A path as written into the committed reports: the home directory as `~`, the repository root dropped."""
    s = str(Path(p).expanduser())
    for root, rep in ((str(ROOT) + "/", ""), (str(Path.home()), "~")):
        if s.startswith(root):
            s = rep + s[len(root):]
    return s


def run_meta(study: str, db_path: Path | str, provisional: bool) -> dict[str, Any]:
    return {"study": study, "run_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(timespec="seconds"), "db": display_path(db_path),
            "provisional": provisional, "model_version": MODEL_VERSION, "seed": SEED, "fno_costs": asdict(FNO)}
