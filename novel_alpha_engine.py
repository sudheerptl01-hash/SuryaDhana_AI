"""
novel_alpha_engine.py
=====================================================================================
SuryaDhana AI — Phase 3 Vectorized Novel Alpha Engine (Agent 3)

Production-grade, fully-vectorized scanning engine that turns the *validated* alpha
contract (`validated_alpha.md`, Section 3b) into an importable, scalable backend
component for the institutional trading terminal.

Surviving strategy (the ONLY one approved in Phase 2b):
    S3-Simplified — Gap Polarity Engine
        2 free hyper-parameters: gap_threshold (0.05), phi (0.50)
        Two long legs:
            Leg B (gap-up continuation, C_T >= O_T) — robust, +56.5 bps standalone
            Leg A (gap-down reversal)              — fails standalone, default OFF
        Entry: T+1 open. Exit: 5-day time-stop (sole exit). No -2%-from-entry stop.

Design contract for downstream agents:
    * `DuckDBDataSource`     — read-only loader; pushes filtering/windowing into SQL.
    * `Strategy` (ABC)       — `generate_signals(data) -> pd.Series[bool]` boolean mask
                               indexed by (ticker, date); plus class-level `PARAM_SPEC`
                               (name -> {default,min,max,step,type}) so Agent 4 can
                               auto-render UI knobs without guessing.
    * `STRATEGY_REGISTRY`    — dynamic enumeration of available strategies.

ABSOLUTE CONSTRAINTS honored:
    * Data ONLY from data/market.duckdb (read-only). No live data, no yfinance/Breeze.
    * Full ~1500-ticker NSE universe (index/macro symbols excluded by predicate).
    * MODE defaults to 'PAPER'. Zero live execution. Research/scanning only.
    * No look-ahead: every signal at decision-time T uses only data at/<= T.
      Entry is T+1 open; forward returns are diagnostics only, never fed to a signal.
    * Zero Python loops over the time series — groupby-transform / shift / vectorized
      boolean algebra exclusively. No iterrows, no per-date / per-ticker signal loops.

Author: Agent 3 — Lead Quantitative Software Engineer
Python : /Users/sudheer/Desktop/jupyter_env/bin/python
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

try:  # duckdb is the sole sanctioned data backend
    import duckdb
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "duckdb is required. Install via "
        "/Users/sudheer/Desktop/jupyter_env/bin/pip install duckdb"
    ) from exc


# --------------------------------------------------------------------------------------
# Module constants & logging
# --------------------------------------------------------------------------------------

#: Air-gap policy — this module never places orders. Execution hooks default to PAPER.
MODE: str = "PAPER"

#: Canonical, immutable path to the central time-series database (read-only).
DB_PATH: Path = Path(
    "/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/market.duckdb"
)

#: Validated universe-eligibility gates (Section 3b / Section 4 of validated_alpha.md).
MIN_BARS: int = 252  # >= 1 trading year of non-zero-volume history
MIN_PRICE_INR: float = 20.0  # penny-stock floor on the latest bar

#: Non-tradeable index/macro symbol exclusion. The current snapshot contains none of
#: these, but the predicate is a permanent safety net so the engine never scans an
#: index series as if it were a stock.
INDEX_EXCLUDE_PATTERN: str = "^%"  # SQL LIKE pattern for caret-prefixed index symbols
INDEX_EXCLUDE_SYMBOLS: tuple[str, ...] = ("NIFTY500", "NIFTY50", "NIFTY")

logger = logging.getLogger("suryadhana.alpha_engine")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------------------
# Data source
# --------------------------------------------------------------------------------------

class DuckDBDataSource:
    """Read-only loader that returns tidy, vectorization-ready OHLCV frames.

    The loader pushes universe-eligibility filtering and column/row pruning into SQL
    so only what is needed is materialized into pandas. It opens the database strictly
    ``read_only=True`` (air-gap / no-mutation guarantee) and reuses a single connection.

    The returned frame is sorted by ``(ticker, date)`` — the canonical layout for the
    groupby-transform / shift vectorization used by every Strategy. The per-ticker
    ordering by date is what makes ``shift(1)`` mean "previous trading bar" without any
    loop.
    """

    OHLCV_COLUMNS: ClassVar[tuple[str, ...]] = (
        "ticker",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
    )

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"market.duckdb not found at {self.db_path}. Phase 2 data load must "
                "run before Phase 3 scanning."
            )
        # Single read-only connection, reused across queries.
        self._con: duckdb.DuckDBPyConnection = duckdb.connect(
            str(self.db_path), read_only=True
        )
        logger.info("DuckDBDataSource opened read-only: %s", self.db_path)

    # -- universe -----------------------------------------------------------------

    def _eligible_predicate(self) -> str:
        """SQL predicate excluding non-tradeable index/macro symbols.

        Returns a fragment intended for a ``WHERE`` clause on the ``ohlcv`` table.
        """
        symbol_list = ", ".join(f"'{s}'" for s in INDEX_EXCLUDE_SYMBOLS)
        return (
            f"ticker NOT LIKE '{INDEX_EXCLUDE_PATTERN}' "
            f"AND ticker NOT IN ({symbol_list})"
        )

    def eligible_universe(self) -> list[str]:
        """Return the full tradeable NSE universe under the validated gates.

        Gates (per validated_alpha.md Section 3b / 4):
            * non-index / non-macro symbol
            * >= MIN_BARS non-zero-volume bars (sufficient history)
            * latest non-zero-volume close >= MIN_PRICE_INR (penny-stock floor)

        Computed entirely in SQL — no row leaves the database for this count.
        """
        sql = f"""
            WITH nz AS (
                SELECT
                    ticker,
                    COUNT(*) AS bars,
                    ARG_MAX(close, date) AS last_close
                FROM ohlcv
                WHERE volume > 0 AND ({self._eligible_predicate()})
                GROUP BY ticker
            )
            SELECT ticker
            FROM nz
            WHERE bars >= {MIN_BARS} AND last_close >= {MIN_PRICE_INR}
            ORDER BY ticker
        """
        tickers = self._con.execute(sql).df()["ticker"].tolist()
        logger.info(
            "Eligible universe: %d tickers (>=%d bars, price>=%.0f INR, non-index)",
            len(tickers),
            MIN_BARS,
            MIN_PRICE_INR,
        )
        return tickers

    def total_universe_size(self) -> int:
        """Count of ALL tradeable tickers in ohlcv (pre-eligibility), for observability."""
        sql = f"SELECT COUNT(DISTINCT ticker) FROM ohlcv WHERE {self._eligible_predicate()}"
        return int(self._con.execute(sql).fetchone()[0])

    # -- frames -------------------------------------------------------------------

    def load_ohlcv(
        self,
        tickers: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        eligible_only: bool = True,
    ) -> pd.DataFrame:
        """Load a tidy OHLCV frame for the requested ticker set / date window.

        Parameters
        ----------
        tickers
            Explicit ticker subset. ``None`` -> the full eligible universe (when
            ``eligible_only``) or the full tradeable universe.
        start, end
            Inclusive ISO date bounds (``YYYY-MM-DD``). Pushed into SQL.
        eligible_only
            Apply the validated history/price/index eligibility gates in SQL.

        Returns
        -------
        pandas.DataFrame
            Columns = OHLCV_COLUMNS, sorted by (ticker, date), zero-volume bars dropped
            (non-tradeable), ``date`` as datetime64. This is the canonical input frame
            for every Strategy.

        Notes
        -----
        Filtering is pushed down to DuckDB to avoid materializing the whole table.
        Zero-volume rows are removed at the SQL layer because they are non-tradeable
        and (per validation) excluded from the eligibility bar-count.
        """
        where: list[str] = ["volume > 0", self._eligible_predicate()]
        params: list[Any] = []

        if eligible_only:
            # Restrict to the eligible universe computed in SQL (sub-select keeps the
            # whole filter server-side; nothing intermediate is shipped to pandas).
            where.append(
                f"""ticker IN (
                    WITH nz AS (
                        SELECT ticker, COUNT(*) AS bars, ARG_MAX(close, date) AS last_close
                        FROM ohlcv
                        WHERE volume > 0 AND ({self._eligible_predicate()})
                        GROUP BY ticker
                    )
                    SELECT ticker FROM nz
                    WHERE bars >= {MIN_BARS} AND last_close >= {MIN_PRICE_INR}
                )"""
            )

        if tickers is not None:
            placeholders = ", ".join("?" for _ in tickers)
            where.append(f"ticker IN ({placeholders})")
            params.extend(tickers)
        if start is not None:
            where.append("date >= ?")
            params.append(start)
        if end is not None:
            where.append("date <= ?")
            params.append(end)

        cols = ", ".join(self.OHLCV_COLUMNS)
        sql = (
            f"SELECT {cols} FROM ohlcv "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY ticker, date"
        )

        t0 = time.perf_counter()
        df = self._con.execute(sql, params).df()
        dt = time.perf_counter() - t0

        df["date"] = pd.to_datetime(df["date"])
        logger.info(
            "Loaded %s rows x %d tickers (%s -> %s) in %.3fs",
            f"{len(df):,}",
            df["ticker"].nunique(),
            df["date"].min().date() if len(df) else "—",
            df["date"].max().date() if len(df) else "—",
            dt,
        )
        return df

    def close(self) -> None:
        """Close the underlying read-only connection."""
        try:
            self._con.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

    def __enter__(self) -> "DuckDBDataSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------------------
# Strategy contract
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:
    """Typed UI/validation spec for one tunable hyper-parameter.

    Mirrors the Phase 4 UI-knob table in validated_alpha.md. ``min``/``max``/``step``
    let Agent 4 render a slider without inspecting code; ``ptype`` drives the widget.
    """

    default: float | int | bool
    min: float | int | None = None
    max: float | int | None = None
    step: float | int | None = None
    ptype: type = float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "type": self.ptype.__name__,
            "label": self.label,
        }


@dataclass
class ScanResult:
    """Outcome of one strategy scan over the universe."""

    strategy: str
    params: dict[str, Any]
    signals: pd.Series  # boolean mask indexed by (ticker, date)
    universe_size: int
    n_rows_scanned: int
    n_signals: int
    sql_latency_s: float
    signal_latency_s: float
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def signal_rate(self) -> float:
        return self.n_signals / self.n_rows_scanned if self.n_rows_scanned else 0.0


class Strategy(ABC):
    """Abstract base class defining the engine-wide strategy contract.

    Subclasses MUST:
        * declare a class-level ``PARAM_SPEC`` mapping ``name -> ParamSpec`` (the single
          source of truth for defaults/ranges; consumed by Agent 4's UI and by
          ``__init__`` validation), and a unique ``STRATEGY_ID`` / ``NAME``;
        * accept every PARAM_SPEC key as a typed constructor kwarg (with the spec's
          default), plus any boolean leg/feature flags;
        * implement ``generate_signals(data) -> pd.Series[bool]`` returning a boolean
          mask aligned to ``data``'s rows, indexed by (ticker, date). ``True`` means
          "decision-time-T signal fired; trade at T+1 open."

    The base class provides parameter coercion/clamping from ``PARAM_SPEC`` and a
    ``scan`` convenience that pulls data and times the SQL + signal phases.
    """

    STRATEGY_ID: ClassVar[str]
    NAME: ClassVar[str]
    PARAM_SPEC: ClassVar[dict[str, ParamSpec]]
    #: Optional non-numeric flags (e.g. leg toggles) advertised to the UI separately.
    FLAG_SPEC: ClassVar[dict[str, ParamSpec]] = {}

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = {}
        spec = {**self.PARAM_SPEC, **self.FLAG_SPEC}
        for name, ps in spec.items():
            raw = params.get(name, ps.default)
            self.params[name] = self._coerce(name, raw, ps)
        # Reject unknown params loudly — keeps the UI contract honest.
        unknown = set(params) - set(spec)
        if unknown:
            raise ValueError(
                f"{type(self).__name__}: unknown params {sorted(unknown)}; "
                f"valid={sorted(spec)}"
            )

    @staticmethod
    def _coerce(name: str, raw: Any, ps: ParamSpec) -> Any:
        """Coerce to the declared type and clamp numeric params into [min, max]."""
        if ps.ptype is bool:
            return bool(raw)
        val = ps.ptype(raw)
        if ps.min is not None and val < ps.min:
            logger.warning("%s=%s below min %s; clamping", name, val, ps.min)
            val = ps.ptype(ps.min)
        if ps.max is not None and val > ps.max:
            logger.warning("%s=%s above max %s; clamping", name, val, ps.max)
            val = ps.ptype(ps.max)
        return val

    @classmethod
    def param_spec_dict(cls) -> dict[str, dict[str, Any]]:
        """Serialize PARAM_SPEC (+ FLAG_SPEC) for the UI / API layer."""
        return {
            name: ps.as_dict()
            for name, ps in {**cls.PARAM_SPEC, **cls.FLAG_SPEC}.items()
        }

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return a boolean mask aligned to ``data`` rows, indexed by (ticker, date).

        ``data`` is the tidy OHLCV frame from :class:`DuckDBDataSource`. The mask must
        contain no NaN (insufficient-history rows -> ``False``, never an error), and
        must use only information available at or before each row's bar T.
        """

    # -- convenience ---------------------------------------------------------------

    def scan(
        self,
        source: DuckDBDataSource,
        tickers: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> ScanResult:
        """Load the slice, generate signals, and time both phases."""
        t0 = time.perf_counter()
        data = source.load_ohlcv(tickers=tickers, start=start, end=end)
        sql_latency = time.perf_counter() - t0

        t1 = time.perf_counter()
        mask = self.generate_signals(data)
        signal_latency = time.perf_counter() - t1

        mask = mask.fillna(False).astype(bool)
        result = ScanResult(
            strategy=self.STRATEGY_ID,
            params=dict(self.params),
            signals=mask,
            universe_size=int(data["ticker"].nunique()),
            n_rows_scanned=int(len(data)),
            n_signals=int(mask.sum()),
            sql_latency_s=sql_latency,
            signal_latency_s=signal_latency,
        )
        logger.info(
            "[%s] scanned %d tickers / %s rows | signals=%s (%.4f%%) | "
            "sql=%.3fs signal=%.3fs",
            self.STRATEGY_ID,
            result.universe_size,
            f"{result.n_rows_scanned:,}",
            f"{result.n_signals:,}",
            100 * result.signal_rate,
            sql_latency,
            signal_latency,
        )
        return result


# --------------------------------------------------------------------------------------
# Concrete strategy: S3-Simplified — Gap Polarity Engine
# --------------------------------------------------------------------------------------

class GapPolarityStrategy(Strategy):
    """S3-Simplified — Gap Polarity Engine (validated_alpha.md Section 3b).

    Long-only, two-leg gap strategy. Signal computed at close of bar T; trade at the
    open of T+1; sole exit is the 5-day time-stop.

    Leg A — Gap-Down Reversal (default OFF, fails standalone):
        gap_T = O_T / C_{T-1} - 1
        fire if  gap_T <= -gap_threshold                              (P1 magnitude gate)
            AND  C_T   >= O_T + phi * (H_T - O_T)                     (P2 recovery conf.)

    Leg B — Gap-Up Continuation (default ON, robust +56.5 bps standalone):
        fire if  gap_T >= +gap_threshold                             (P1 magnitude gate)
            AND  C_T   >= O_T                                        (FIXED: close held gap)

    signal = (leg_a if enable_leg_a) | (leg_b if enable_leg_b)

    Vectorization
    -------------
    ``gap_T`` needs the *previous bar's* close per ticker. We obtain it with a single
    ``groupby('ticker')['close'].shift(1)`` — strictly past data, no look-ahead, and no
    loop. All leg logic is vectorized boolean algebra on full-length numpy arrays.

    Look-ahead audit
    ----------------
    Every input to the signal (O_T, H_T, C_T, C_{T-1}) is known at the close of bar T.
    ``shift(1)`` pulls the *prior* close (T-1), never a future bar. Forward returns and
    the T+1 adjusted entry price are computed only as *diagnostics* in
    :meth:`forward_diagnostics` and are NEVER consumed by ``generate_signals``.
    """

    STRATEGY_ID: ClassVar[str] = "S3_GAP_POLARITY"
    NAME: ClassVar[str] = "Gap Polarity Engine (S3-Simplified)"

    # The two free hyper-parameters — defaults/ranges copied verbatim from the
    # Phase 4 UI-knob table in validated_alpha.md Section 3b.
    PARAM_SPEC: ClassVar[dict[str, ParamSpec]] = {
        "gap_threshold": ParamSpec(
            default=0.05, min=0.03, max=0.10, step=0.01, ptype=float,
            label="Gap magnitude threshold (fraction)",
        ),
        "phi": ParamSpec(
            default=0.50, min=0.00, max=1.00, step=0.05, ptype=float,
            label="Intraday recovery fraction (gap-down leg)",
        ),
    }

    # Leg toggles — zero DoF (not tuned), exposed so the robust leg (B) can run alone.
    # Default: Leg B ON (robust), Leg A OFF (fails standalone per Section 3b).
    FLAG_SPEC: ClassVar[dict[str, ParamSpec]] = {
        "enable_leg_a": ParamSpec(
            default=False, ptype=bool, label="Enable Leg A (gap-down reversal)",
        ),
        "enable_leg_b": ParamSpec(
            default=True, ptype=bool, label="Enable Leg B (gap-up continuation)",
        ),
    }

    # Fixed project rules (zero DoF) — documented constants, not tunable.
    TIME_STOP_DAYS: ClassVar[int] = 5  # exit at close of T+5
    FRICTION_ROUND_TRIP: ClassVar[float] = 0.0015  # 30 bps

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        if not (self.params["enable_leg_a"] or self.params["enable_leg_b"]):
            raise ValueError(
                "GapPolarityStrategy: at least one leg must be enabled "
                "(enable_leg_a / enable_leg_b)."
            )

    # -- signal -------------------------------------------------------------------

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Vectorized two-leg gap-polarity entry mask, indexed by (ticker, date).

        No time-series loops: the only cross-bar dependency (prior close) is resolved
        with one groupby-shift. NaN/Inf are handled by masking, never by dropping rows.
        """
        gap_threshold = float(self.params["gap_threshold"])
        phi = float(self.params["phi"])

        # Stable (ticker, date) order is required for shift(1) to mean "previous bar".
        df = data.sort_values(["ticker", "date"], kind="mergesort")

        o = df["open"].to_numpy(dtype=np.float64)
        h = df["high"].to_numpy(dtype=np.float64)
        c = df["close"].to_numpy(dtype=np.float64)

        # Previous close per ticker — the SOLE cross-bar lookup. shift(1) => strictly
        # past (T-1); first bar of each ticker becomes NaN (insufficient history).
        prev_close = (
            df.groupby("ticker", sort=False)["close"].shift(1).to_numpy(dtype=np.float64)
        )

        # gap_T = O_T / C_{T-1} - 1. Guard divide-by-zero / non-finite -> NaN (no signal).
        with np.errstate(divide="ignore", invalid="ignore"):
            gap = np.where(prev_close > 0.0, o / prev_close - 1.0, np.nan)
        gap = np.where(np.isfinite(gap), gap, np.nan)

        # P2 recovery confirmation (Leg A): C_T >= O_T + phi*(H_T - O_T).
        intraday_recovered = c >= (o + phi * (h - o))
        # FIXED gap-held confirmation (Leg B): C_T >= O_T.
        gap_held = c >= o

        # Any NaN among the gap inputs disqualifies the row (treated as "no signal").
        valid = np.isfinite(gap) & np.isfinite(o) & np.isfinite(h) & np.isfinite(c)

        leg_a = (gap <= -gap_threshold) & intraday_recovered & valid
        leg_b = (gap >= gap_threshold) & gap_held & valid

        signal = np.zeros(len(df), dtype=bool)
        if self.params["enable_leg_a"]:
            signal |= leg_a
        if self.params["enable_leg_b"]:
            signal |= leg_b

        mask = pd.Series(
            signal,
            index=pd.MultiIndex.from_arrays(
                [df["ticker"].to_numpy(), df["date"].to_numpy()],
                names=["ticker", "date"],
            ),
            name=self.STRATEGY_ID,
        )
        return mask

    # -- diagnostics (NOT used by the signal — forward-looking, evaluation only) ---

    def forward_diagnostics(self, data: pd.DataFrame) -> pd.DataFrame:
        """Attach T+1 adjusted-entry and 5-day-time-stop forward returns for QA only.

        These columns are *strictly forward-looking* and must never be fed back into a
        signal — they exist so the UI/backtest layer can display realized edge. Entry
        and exit follow the validated contract exactly:

            entry_adj = open[T+1]  * (adjusted_close[T+1] / close[T+1])
            exit_adj  = adjusted_close[T+5]
            fwd5      = exit_adj / entry_adj - 1
            net5      = fwd5 - FRICTION_ROUND_TRIP

        Per-ticker shifts (-1 / -5) are vectorized via groupby; no loops.
        """
        df = data.sort_values(["ticker", "date"], kind="mergesort").copy()
        g = df.groupby("ticker", sort=False)

        # Per-day adjustment factor (corporate actions baked into adjusted_close).
        with np.errstate(divide="ignore", invalid="ignore"):
            adj_factor = np.where(
                df["close"].to_numpy() > 0,
                df["adjusted_close"].to_numpy() / df["close"].to_numpy(),
                np.nan,
            )
        df["adj_factor"] = adj_factor

        # T+1 adjusted open (actual execution price).
        df["entry_adj"] = (
            g["open"].shift(-1).to_numpy() * g["adj_factor"].shift(-1).to_numpy()
        )
        # T+5 adjusted close (time-stop exit).
        df["exit_adj"] = g["adjusted_close"].shift(-self.TIME_STOP_DAYS).to_numpy()

        with np.errstate(divide="ignore", invalid="ignore"):
            fwd5 = df["exit_adj"].to_numpy() / df["entry_adj"].to_numpy() - 1.0
        fwd5 = np.where(np.isfinite(fwd5), fwd5, np.nan)
        df["fwd5"] = fwd5
        df["net5"] = fwd5 - self.FRICTION_ROUND_TRIP
        return df[["ticker", "date", "entry_adj", "exit_adj", "fwd5", "net5"]]


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

#: Dynamic enumeration of available strategies, keyed by STRATEGY_ID.
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    GapPolarityStrategy.STRATEGY_ID: GapPolarityStrategy,
}


def get_strategy(strategy_id: str, **params: Any) -> Strategy:
    """Instantiate a registered strategy by id with the given hyper-parameters."""
    if strategy_id not in STRATEGY_REGISTRY:
        raise KeyError(
            f"Unknown strategy '{strategy_id}'. "
            f"Registered: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[strategy_id](**params)


def list_strategies() -> dict[str, dict[str, Any]]:
    """Enumerate strategies + their UI param specs for Agent 4 (no instantiation)."""
    return {
        sid: {
            "name": cls.NAME,
            "params": cls.param_spec_dict(),
        }
        for sid, cls in STRATEGY_REGISTRY.items()
    }


# --------------------------------------------------------------------------------------
# Smoke test
# --------------------------------------------------------------------------------------

def _smoke_test() -> None:
    """Instantiate every registered strategy at defaults, scan the FULL universe,
    print latency + signal counts, and assert a sane boolean mask.

    'Sane' == not 0% and not 100% of scanned rows fire (a degenerate mask would mean
    the signal logic is broken or trivially true).
    """
    logger.info("=" * 78)
    logger.info("SuryaDhana Phase 3 — Novel Alpha Engine smoke test (MODE=%s)", MODE)
    logger.info("=" * 78)

    source = DuckDBDataSource(DB_PATH)
    try:
        total = source.total_universe_size()
        eligible = source.eligible_universe()
        logger.info(
            "Tradeable universe in ohlcv: %d | eligible after gates: %d",
            total,
            len(eligible),
        )
        assert len(eligible) > 1000, (
            f"Expected ~1.3k eligible tickers, got {len(eligible)} — universe scope "
            "regression."
        )

        assert STRATEGY_REGISTRY, "STRATEGY_REGISTRY is empty"

        for sid, cls in STRATEGY_REGISTRY.items():
            logger.info("-" * 78)
            logger.info("Strategy %s (%s) at default params", sid, cls.NAME)
            strat = cls()  # default hyper-parameters
            logger.info("  PARAM_SPEC: %s", cls.param_spec_dict())
            logger.info("  resolved params: %s", strat.params)

            result = strat.scan(source)  # FULL eligible universe, full history

            # --- assertions: output is a well-formed boolean mask ---
            assert isinstance(result.signals, pd.Series), "signals must be a Series"
            assert result.signals.dtype == bool, "signals must be a boolean mask"
            assert result.signals.index.names == ["ticker", "date"], (
                "mask must be indexed by (ticker, date)"
            )
            assert len(result.signals) == result.n_rows_scanned, (
                "mask length must equal rows scanned"
            )
            assert not result.signals.isna().any(), "mask must contain no NaN"

            # --- sanity: not degenerate (0% or 100%) ---
            rate = result.signal_rate
            assert 0.0 < rate < 1.0, (
                f"degenerate signal rate {rate:.4%} for {sid} (0% or 100% => broken)"
            )
            logger.info(
                "  OK: %s signals across %s rows on %d tickers (rate=%.4f%%)",
                f"{result.n_signals:,}",
                f"{result.n_rows_scanned:,}",
                result.universe_size,
                100 * rate,
            )
            logger.info(
                "  latency: SQL=%.3fs  signal=%.3fs  total=%.3fs",
                result.sql_latency_s,
                result.signal_latency_s,
                result.sql_latency_s + result.signal_latency_s,
            )

            # --- Leg-B-only contract check (the robust deployable config) ---
            if sid == GapPolarityStrategy.STRATEGY_ID:
                legb = cls(enable_leg_a=False, enable_leg_b=True)
                rb = legb.scan(source)
                lega = cls(enable_leg_a=True, enable_leg_b=False)
                ra = lega.scan(source)
                # Default == Leg B only (since Leg A defaults OFF).
                assert result.n_signals == rb.n_signals, (
                    "default config must equal Leg-B-only (Leg A is OFF by default)"
                )
                # Combined would be the union of both legs.
                both = cls(enable_leg_a=True, enable_leg_b=True)
                rboth = both.scan(source)
                assert rboth.n_signals >= max(ra.n_signals, rb.n_signals), (
                    "combined legs must cover >= each standalone leg"
                )
                logger.info(
                    "  leg breakdown: LegA=%s  LegB=%s  Combined=%s",
                    f"{ra.n_signals:,}",
                    f"{rb.n_signals:,}",
                    f"{rboth.n_signals:,}",
                )

        logger.info("=" * 78)
        logger.info("SMOKE TEST PASSED — all strategies emit sane boolean masks.")
        logger.info("=" * 78)
    finally:
        source.close()


if __name__ == "__main__":
    _smoke_test()
