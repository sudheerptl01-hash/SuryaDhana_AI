"""
SuryaDhana — Live Execution Engine
Phase 6: Paper → Live trading with kill switch and daily loss guard.

Execution modes:
  PAPER — all fills simulated in SQLite, zero broker API calls
  LIVE  — real orders sent to ICICI Breeze; NEVER switch without explicit confirmation

Design principles:
  - Fail-safe: every state mutation guarded by asyncio.Lock
  - Defensive: every broker call wrapped in retry+timeout logic
  - Hard-wired 2% daily loss limit (cannot be disabled at runtime)
  - Full audit trail: every order, fill, and state change persisted to SQLite
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:  # sibling module (bare import in-service; package-qualified in tests)
    from execution_scheduler import ExecutionAlgo, ExecutionReport, simulate_execution
except ImportError:  # pragma: no cover - test/package import path
    from .execution_scheduler import ExecutionAlgo, ExecutionReport, simulate_execution  # type: ignore

logger = logging.getLogger("suryadhana.execution")

# ── Hardwired constants — DO NOT modify without review ─────────────────────────
DAILY_LOSS_LIMIT_PCT: float = 0.02       # 2 % of equity — kill switch trips here
MAX_POSITIONS: int = 5                    # never exceed 5 simultaneous positions
MAX_POSITION_PCT: float = 0.15           # 15 % per stock
TRANSACTION_COST_PCT: float = 0.0015    # 0.15 % per-side (brokerage + STT + stamp)
ORDER_TIMEOUT_S: int = 10               # broker API timeout
MAX_RETRIES: int = 3                    # per-order retry attempts
RETRY_BASE_DELAY_S: float = 1.0         # exponential backoff base


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE  = "LIVE"


class EngineState(str, Enum):
    ACTIVE  = "ACTIVE"
    HALTED  = "HALTED"   # kill switch tripped — no new orders
    COOLING = "COOLING"  # post-halt cooldown


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_entry_price: float
    signal_source: str          # e.g. "XGBoost" | "RL Agent" | "Manual"
    entry_time: str
    stop_loss_price: float = 0.0
    ltp: float = 0.0            # filled by reconcile loop
    unrealized_pnl: float = 0.0 # filled by reconcile loop
    unrealized_pnl_pct: float = 0.0


@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    side: str           # "BUY" | "SELL"
    quantity: int
    price: float
    mode: str           # "PAPER" | "LIVE"
    status: str         # "FILLED" | "REJECTED" | "CANCELLED"
    signal_source: str
    broker_order_id: str
    timestamp: str
    notes: str = ""


@dataclass
class DailyPnL:
    date: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    equity_start: float = 0.0
    loss_pct: float = 0.0       # negative if loss
    kill_switch_triggered: bool = False


class ExecutionEngine:
    """
    Central execution engine. Single instance per process.

    Thread safety: all public mutating methods acquire _lock before touching state.
    Kill switch: checked after every order submission and price reconcile cycle.
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.PAPER,
        db_path: str | None = None,
        initial_equity: float = 10_000.0,
        active_model: str = "XGBoost",
        price_guard_pct: float | None = None,
    ) -> None:
        self._mode = mode
        # Max allowed gap between a submitted order price and the live market price
        # (percent). Paper fills book at the SUBMITTED price, so without this guard a
        # typo or test call (e.g. RELIANCE @ ₹100 while it trades ~₹1,400) creates a
        # fictitious position with a meaningless P&L. 0 disables (unit tests only).
        if price_guard_pct is None:
            price_guard_pct = float(os.environ.get("PAPER_PRICE_GUARD_PCT", "10"))
        self._price_guard_pct = price_guard_pct
        self._state = EngineState.ACTIVE
        # _cash: liquid cash available (decreases on buy, increases on sell)
        # total portfolio value = _cash + sum(position cost basis)
        self._cash = initial_equity
        self._equity_start_of_day = initial_equity  # total portfolio at day open
        self._tx_costs_today: float = 0.0          # accumulated transaction costs today
        self._active_model = active_model
        self._lock = asyncio.Lock()
        self._positions: dict[str, Position] = {}
        self._kill_switch_reason: str = ""

        # SQLite path: env var > Docker data mount > local project root
        if db_path is None:
            from_env = os.environ.get("PAPER_TRADES_DB", "")
            if from_env:
                db_path = from_env
            elif Path("/app/data").exists():
                db_path = "/app/data/paper_trades.db"
            else:
                db_path = str(
                    Path(__file__).resolve().parents[2] / "data" / "paper_trades.db"
                )
        self._db_path = db_path
        self._init_db()

        # Lazy ICICI Breeze client (only used in LIVE mode)
        self._breeze: Any = None

        logger.info("ExecutionEngine initialized", extra={
            "mode": mode.value,
            "db": db_path,
            "equity": initial_equity,
        })

    @property
    def _equity(self) -> float:
        """Total portfolio value: cash + cost basis of all open positions."""
        cost_basis = sum(p.avg_entry_price * p.quantity for p in self._positions.values())
        return self._cash + cost_basis

    # ── Database ────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id        TEXT PRIMARY KEY,
                    symbol          TEXT NOT NULL,
                    side            TEXT NOT NULL,
                    quantity        INTEGER NOT NULL,
                    price           REAL NOT NULL,
                    mode            TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    signal_source   TEXT,
                    broker_order_id TEXT,
                    timestamp       TEXT NOT NULL,
                    notes           TEXT
                );

                CREATE TABLE IF NOT EXISTS positions (
                    symbol          TEXT PRIMARY KEY,
                    quantity        INTEGER NOT NULL,
                    avg_entry_price REAL NOT NULL,
                    signal_source   TEXT,
                    entry_time      TEXT NOT NULL,
                    stop_loss_price REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS daily_pnl (
                    date                    TEXT PRIMARY KEY,
                    realized_pnl            REAL DEFAULT 0,
                    unrealized_pnl          REAL DEFAULT 0,
                    total_pnl               REAL DEFAULT 0,
                    equity_start            REAL DEFAULT 0,
                    loss_pct                REAL DEFAULT 0,
                    kill_switch_triggered   INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS engine_state (
                    key     TEXT PRIMARY KEY,
                    value   TEXT NOT NULL,
                    updated TEXT NOT NULL
                );

                -- G9: per-child execution audit trail for sliced (TWAP/VWAP/POV) orders.
                CREATE TABLE IF NOT EXISTS order_fills (
                    fill_id         TEXT PRIMARY KEY,
                    parent_order_id TEXT NOT NULL,
                    symbol          TEXT NOT NULL,
                    side            TEXT NOT NULL,
                    algo            TEXT NOT NULL,
                    slice_idx       INTEGER NOT NULL,
                    requested_qty   INTEGER NOT NULL,
                    filled_qty      INTEGER NOT NULL,
                    fill_price      REAL NOT NULL,
                    slippage_bps    REAL NOT NULL,
                    participation   REAL NOT NULL,
                    timestamp       TEXT NOT NULL
                );
            """)
            conn.commit()
        self._restore_state_from_db()

    @contextmanager
    def _get_db(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _restore_state_from_db(self) -> None:
        """Restore positions and equity from previous session."""
        try:
            with self._get_db() as conn:
                rows = conn.execute("SELECT * FROM positions").fetchall()
                for row in rows:
                    self._positions[row["symbol"]] = Position(
                        symbol=row["symbol"],
                        quantity=row["quantity"],
                        avg_entry_price=row["avg_entry_price"],
                        signal_source=row["signal_source"] or "Unknown",
                        entry_time=row["entry_time"],
                        stop_loss_price=row["stop_loss_price"],
                    )

                state_rows = conn.execute("SELECT key, value FROM engine_state").fetchall()
                state_map = {r["key"]: r["value"] for r in state_rows}
                if "cash" in state_map:
                    self._cash = float(state_map["cash"])
                if "equity_start" in state_map:
                    self._equity_start_of_day = float(state_map["equity_start"])
                if "tx_costs_today" in state_map:
                    self._tx_costs_today = float(state_map["tx_costs_today"])
                if "mode" in state_map:
                    try:
                        self._mode = ExecutionMode(state_map["mode"])
                    except ValueError:
                        pass

                logger.info(
                    "Engine state restored",
                    extra={"positions": len(self._positions), "equity": self._equity},
                )
        except Exception as exc:
            logger.warning("State restore failed (fresh start)", extra={"error": str(exc)})

    def _persist_state(self, conn: sqlite3.Connection) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for key, value in [
            ("cash", str(self._cash)),
            ("equity_start", str(self._equity_start_of_day)),
            ("tx_costs_today", str(self._tx_costs_today)),
            ("mode", self._mode.value),
            ("state", self._state.value),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO engine_state (key, value, updated) VALUES (?,?,?)",
                (key, value, now),
            )

    def _persist_position(self, conn: sqlite3.Connection, pos: Position) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO positions
               (symbol, quantity, avg_entry_price, signal_source, entry_time, stop_loss_price)
               VALUES (?,?,?,?,?,?)""",
            (pos.symbol, pos.quantity, pos.avg_entry_price,
             pos.signal_source, pos.entry_time, pos.stop_loss_price),
        )

    def _delete_position(self, conn: sqlite3.Connection, symbol: str) -> None:
        conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))

    def _log_order(self, conn: sqlite3.Connection, rec: OrderRecord) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO orders
               (order_id, symbol, side, quantity, price, mode, status,
                signal_source, broker_order_id, timestamp, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.order_id, rec.symbol, rec.side, rec.quantity, rec.price,
             rec.mode, rec.status, rec.signal_source, rec.broker_order_id,
             rec.timestamp, rec.notes),
        )

    def _log_execution_report(self, conn: sqlite3.Connection, parent_order_id: str,
                              report: "ExecutionReport") -> None:
        """Persist each child fill of a sliced order to `order_fills` for the audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        for f in report.fills:
            conn.execute(
                """INSERT OR REPLACE INTO order_fills
                   (fill_id, parent_order_id, symbol, side, algo, slice_idx,
                    requested_qty, filled_qty, fill_price, slippage_bps, participation, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"{parent_order_id}-{f.slice_idx}", parent_order_id, report.symbol,
                 report.side, report.algo, f.slice_idx, f.requested_qty, f.filled_qty,
                 f.fill_price, f.slippage_bps, f.participation_rate, now),
            )

    def _update_daily_pnl(self, conn: sqlite3.Connection) -> None:
        today = date.today().isoformat()
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        # C8 — telemetry must report the TRUE intraday hole, not just paid costs.
        # Persist the same figure the active kill-switch evaluates (check_daily_loss_limit:
        # daily_pnl = unrealized - tx_costs_today) so the operator dashboard cannot show a
        # benign "-tx_costs only" number while the guard is silently tracking a -1.9% MTM
        # drawdown toward the -2% halt. Observability fix only — control path unchanged.
        daily_loss = unrealized - self._tx_costs_today
        loss_pct = daily_loss / max(self._equity_start_of_day, 1)
        conn.execute(
            """INSERT OR REPLACE INTO daily_pnl
               (date, unrealized_pnl, total_pnl, equity_start, loss_pct, kill_switch_triggered)
               VALUES (?,?,?,?,?,?)""",
            (today, unrealized, daily_loss,
             self._equity_start_of_day, loss_pct,
             int(self._state == EngineState.HALTED)),
        )

    # ── ICICI Breeze (LIVE mode only) ───────────────────────────────────────────

    def _get_breeze(self) -> Any:
        if self._breeze is not None:
            return self._breeze
        api_key    = os.environ.get("ICICI_API_KEY", "")
        api_secret = os.environ.get("ICICI_API_SECRET", "")
        raw_token  = os.environ.get("ICICI_SESSION_TOKEN", "")
        if not (api_key and api_secret and raw_token):
            raise RuntimeError("ICICI credentials not configured in environment.")
        try:
            try:      # breeze_connect downloads ICICI's security master at import, with no timeout: use the cache
                from shared.breeze_cache import install as _breeze_cache_install
                _breeze_cache_install()
            except Exception:  # noqa: BLE001
                pass
            from breeze_connect import BreezeConnect  # type: ignore[import]
            breeze = BreezeConnect(api_key=api_key)
            breeze.generate_session(api_secret=api_secret, session_token=raw_token)
            self._breeze = breeze
            logger.info("ICICI Breeze connected for LIVE orders.")
            return self._breeze
        except Exception as exc:
            raise RuntimeError(f"Breeze connection failed: {exc}") from exc

    def _breeze_place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "market",
    ) -> str:
        """Place order via Breeze with retry and timeout. Returns broker_order_id."""
        breeze = self._get_breeze()
        stock_code = symbol.replace(".NS", "")
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                resp = breeze.place_order(
                    stock_code=stock_code,
                    exchange_code="NSE",
                    product="cash",
                    action=side.lower(),
                    order_type=order_type,
                    stoploss="0",
                    quantity=str(quantity),
                    price=str(round(price, 2)) if order_type == "limit" else "0",
                    validity="day",
                )
                if resp.get("Status") == 200:
                    broker_id = resp["Success"]["order_id"]
                    logger.info("LIVE order placed", extra={
                        "symbol": symbol, "side": side, "qty": quantity,
                        "broker_id": broker_id,
                    })
                    return broker_id
                raise RuntimeError(f"Broker rejected order: {resp}")

            except (ConnectionError, TimeoutError) as exc:
                last_exc = exc
                delay = RETRY_BASE_DELAY_S * (2 ** attempt)
                logger.warning(
                    "Broker API transient error, retrying",
                    extra={"attempt": attempt + 1, "delay": delay, "error": str(exc)},
                )
                time.sleep(delay)

            except RuntimeError:
                raise

            except Exception as exc:
                last_exc = exc
                if "rate" in str(exc).lower() or "429" in str(exc):
                    time.sleep(RETRY_BASE_DELAY_S * (2 ** attempt))
                    continue
                raise RuntimeError(f"Unexpected broker error: {exc}") from exc

        raise RuntimeError(
            f"Order for {symbol} failed after {MAX_RETRIES} attempts. Last: {last_exc}"
        )

    def _breeze_cancel_order(self, broker_order_id: str, symbol: str) -> bool:
        try:
            breeze = self._get_breeze()
            resp = breeze.cancel_order(
                exchange_code="NSE",
                order_id=broker_order_id,
            )
            return resp.get("Status") == 200
        except Exception as exc:
            logger.error("Cancel order failed", extra={
                "broker_id": broker_order_id, "error": str(exc)
            })
            return False

    def _breeze_get_ltp(self, symbol: str) -> float:
        """Fetch last traded price. Returns 0 on any error."""
        try:
            breeze = self._get_breeze()
            resp = breeze.get_quotes(
                stock_code=symbol.replace(".NS", ""),
                exchange_code="NSE",
                expiry_date="",
                product_type="cash",
                right="",
                strike_price="",
            )
            if resp.get("Status") == 200:
                success = resp.get("Success") or []
                if success:
                    return float(success[0].get("last_traded_price", 0) or 0)
        except Exception as exc:
            logger.warning("LTP fetch failed", extra={"symbol": symbol, "error": str(exc)})
        return 0.0

    def _get_yfinance_ltp(self, symbol: str) -> float:
        """Fallback LTP via yfinance for paper mode or when Breeze is unavailable."""
        try:
            import yfinance as yf
            ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
            data = yf.Ticker(ticker).fast_info
            return float(getattr(data, "last_price", 0) or 0)
        except Exception:
            return 0.0

    # ── Core Order Logic ────────────────────────────────────────────────────────

    async def _submit_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        signal_source: str,
        stop_loss_price: float = 0.0,
    ) -> OrderRecord:
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        broker_id = ""
        status = "REJECTED"
        notes = ""

        tx_cost = price * quantity * TRANSACTION_COST_PCT

        if self._mode == ExecutionMode.PAPER:
            # Cash moves; position cost basis offsets on the portfolio side
            if side == "BUY":
                self._cash -= (price * quantity + tx_cost)
            else:
                self._cash += (price * quantity - tx_cost)
            self._tx_costs_today += tx_cost
            broker_id = f"PAPER-{order_id[:8]}"
            status = "FILLED"
            notes = f"Paper fill @ ₹{price:.2f}; txcost ₹{tx_cost:.2f}"
            logger.info("PAPER order filled", extra={
                "symbol": symbol, "side": side, "qty": quantity,
                "price": price, "tx_cost": tx_cost,
            })

        else:  # LIVE
            try:
                broker_id = self._breeze_place_order(
                    symbol, side, quantity, price,
                    order_type="market" if stop_loss_price == 0 else "limit",
                )
                if side == "BUY":
                    self._cash -= (price * quantity + tx_cost)
                else:
                    self._cash += (price * quantity - tx_cost)
                self._tx_costs_today += tx_cost
                status = "FILLED"
                notes = f"Live fill @ ₹{price:.2f}; txcost ₹{tx_cost:.2f}"
            except Exception as exc:
                status = "REJECTED"
                notes = f"Live order failed: {exc}"
                logger.error("LIVE order rejected", extra={
                    "symbol": symbol, "side": side, "qty": quantity, "error": str(exc)
                })

        rec = OrderRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            mode=self._mode.value,
            status=status,
            signal_source=signal_source,
            broker_order_id=broker_id,
            timestamp=now,
            notes=notes,
        )

        with self._get_db() as conn:
            self._log_order(conn, rec)
            if status == "FILLED":
                if side == "BUY":
                    if symbol in self._positions:
                        existing = self._positions[symbol]
                        total_qty = existing.quantity + quantity
                        avg_price = (
                            (existing.avg_entry_price * existing.quantity + price * quantity)
                            / total_qty
                        )
                        pos = Position(
                            symbol=symbol,
                            quantity=total_qty,
                            avg_entry_price=avg_price,
                            signal_source=signal_source,
                            entry_time=existing.entry_time,
                            stop_loss_price=stop_loss_price or existing.stop_loss_price,
                        )
                    else:
                        pos = Position(
                            symbol=symbol,
                            quantity=quantity,
                            avg_entry_price=price,
                            signal_source=signal_source,
                            entry_time=now,
                            stop_loss_price=stop_loss_price,
                        )
                    self._positions[symbol] = pos
                    self._persist_position(conn, pos)
                else:  # SELL
                    if symbol in self._positions:
                        existing = self._positions[symbol]
                        remaining = existing.quantity - quantity
                        if remaining <= 0:
                            del self._positions[symbol]
                            self._delete_position(conn, symbol)
                        else:
                            pos = Position(
                                symbol=symbol,
                                quantity=remaining,
                                avg_entry_price=existing.avg_entry_price,
                                signal_source=existing.signal_source,
                                entry_time=existing.entry_time,
                                stop_loss_price=existing.stop_loss_price,
                            )
                            self._positions[symbol] = pos
                            self._persist_position(conn, pos)
            self._persist_state(conn)
            self._update_daily_pnl(conn)
            conn.commit()

        return rec

    # ── Public API (called from FastAPI router) ─────────────────────────────────

    async def set_mode(self, mode: ExecutionMode) -> None:
        async with self._lock:
            if mode == ExecutionMode.LIVE and self._state == EngineState.HALTED:
                raise ValueError(
                    "Engine is HALTED (kill switch). Reset the engine before enabling LIVE mode."
                )
            self._mode = mode
            with self._get_db() as conn:
                self._persist_state(conn)
                conn.commit()
            logger.warning("Execution mode changed", extra={"mode": mode.value})

    async def set_active_model(self, model_name: str) -> None:
        async with self._lock:
            self._active_model = model_name

    def get_status(self) -> dict:
        unrealized_pnl = sum(p.unrealized_pnl for p in self._positions.values())
        total_equity = self._equity  # cash + cost_basis (property)
        # daily_pnl = unrealized PnL - transaction costs paid today
        daily_pnl = unrealized_pnl - self._tx_costs_today
        daily_pnl_pct = (daily_pnl / max(self._equity_start_of_day, 1)) * 100

        return {
            "mode": self._mode.value,
            "state": self._state.value,
            "active_model": self._active_model,
            "equity": round(total_equity, 2),
            "cash": round(self._cash, 2),
            "equity_start_of_day": round(self._equity_start_of_day, 2),
            "daily_pnl_inr": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 3),
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT * 100,
            "kill_switch_headroom_pct": round(
                (DAILY_LOSS_LIMIT_PCT * 100) + daily_pnl_pct, 3
            ),
            "unrealized_pnl_inr": round(unrealized_pnl, 2),
            "tx_costs_today": round(self._tx_costs_today, 2),
            "open_positions": len(self._positions),
            "kill_switch_reason": self._kill_switch_reason,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    def _mark_price(self, symbol: str) -> float:
        if self._mode == ExecutionMode.LIVE and self._breeze:
            return self._breeze_get_ltp(symbol)
        return self._get_yfinance_ltp(symbol)

    async def get_positions(self) -> list[dict]:
        """Returns current positions with live LTP and unrealized PnL."""
        # Price lookups are blocking network calls (Breeze / yfinance): run them in
        # worker threads, concurrently, so polling this never stalls the event loop.
        symbols = list(self._positions)
        prices = await asyncio.gather(*(asyncio.to_thread(self._mark_price, s) for s in symbols))
        marks = dict(zip(symbols, prices))
        result = []
        async with self._lock:
            for symbol, pos in self._positions.items():
                ltp = marks.get(symbol, 0.0)

                if ltp <= 0:
                    ltp = pos.avg_entry_price

                unrealized = (ltp - pos.avg_entry_price) * pos.quantity
                unrealized_pct = (ltp - pos.avg_entry_price) / max(pos.avg_entry_price, 1) * 100
                pos.ltp = ltp
                pos.unrealized_pnl = unrealized
                pos.unrealized_pnl_pct = unrealized_pct
                result.append({**asdict(pos), "market_value": round(ltp * pos.quantity, 2)})
        return result

    async def get_orders(self, limit: int = 50) -> list[dict]:
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Weight Translation ───────────────────────────────────────────────────────

    async def translate_weights_to_orders(
        self,
        target_weights: dict[str, float],
        prices: dict[str, float],
        signal_sources: dict[str, str] | None = None,
    ) -> list[dict]:
        """
        Translates target portfolio weights → discrete share quantities → orders.

        target_weights: {symbol: 0.0–1.0 fraction of equity}
        prices: {symbol: current_ltp}
        Returns list of proposed orders (not yet executed).
        """
        async with self._lock:
            if self._state != EngineState.ACTIVE:
                return []
            if len(target_weights) > MAX_POSITIONS:
                target_weights = dict(
                    sorted(target_weights.items(), key=lambda x: -x[1])[:MAX_POSITIONS]
                )

            orders = []
            equity = self._equity

            for symbol, weight in target_weights.items():
                weight = min(weight, MAX_POSITION_PCT)
                target_value = equity * weight
                price = prices.get(symbol, 0.0)
                if price <= 0:
                    continue

                target_qty = int(target_value / price)
                current_qty = self._positions.get(symbol, Position(
                    symbol, 0, 0, "", ""
                )).quantity

                delta = target_qty - current_qty
                if delta == 0:
                    continue

                orders.append({
                    "symbol": symbol,
                    "side": "BUY" if delta > 0 else "SELL",
                    "quantity": abs(delta),
                    "price": price,
                    "target_weight": weight,
                    "signal_source": (signal_sources or {}).get(symbol, self._active_model),
                })

            return orders

    # ── Reconciliation ──────────────────────────────────────────────────────────

    async def reconcile_positions(
        self,
        broker_positions: list[dict],
    ) -> list[dict]:
        """
        Compares broker's reported positions vs our internal ledger.
        Returns list of delta orders needed to reconcile discrepancies.
        """
        async with self._lock:
            broker_map = {p["symbol"]: int(p.get("quantity", 0)) for p in broker_positions}
            delta_orders = []

            # Check for positions we think we have but broker does not
            for symbol, pos in list(self._positions.items()):
                broker_qty = broker_map.get(symbol, 0)
                if broker_qty == 0 and pos.quantity > 0:
                    delta_orders.append({
                        "symbol": symbol,
                        "side": "SELL_PHANTOM",
                        "internal_qty": pos.quantity,
                        "broker_qty": 0,
                        "action": "REMOVE_INTERNAL",
                    })
                elif broker_qty != pos.quantity:
                    diff = broker_qty - pos.quantity
                    delta_orders.append({
                        "symbol": symbol,
                        "side": "BUY" if diff > 0 else "SELL",
                        "quantity": abs(diff),
                        "internal_qty": pos.quantity,
                        "broker_qty": broker_qty,
                        "action": "RECONCILE",
                    })

            # Positions broker has that we don't track
            for symbol, broker_qty in broker_map.items():
                if symbol not in self._positions and broker_qty > 0:
                    delta_orders.append({
                        "symbol": symbol,
                        "side": "UNKNOWN_HOLDING",
                        "broker_qty": broker_qty,
                        "action": "MANUAL_REVIEW",
                    })

            return delta_orders

    # ── Kill Switch ─────────────────────────────────────────────────────────────

    async def check_daily_loss_limit(self) -> bool:
        """Returns True if kill switch was just tripped."""
        async with self._lock:
            if self._state != EngineState.ACTIVE:
                return False
            unrealized = sum(p.unrealized_pnl for p in self._positions.values())
            daily_pnl = unrealized - self._tx_costs_today
            loss_pct = daily_pnl / max(self._equity_start_of_day, 1)
            if loss_pct <= -DAILY_LOSS_LIMIT_PCT:
                reason = (
                    f"Daily loss limit breached: {loss_pct*100:.2f}% "
                    f"(limit: -{DAILY_LOSS_LIMIT_PCT*100:.1f}%)"
                )
                logger.critical("KILL SWITCH TRIGGERED — DAILY LOSS LIMIT", extra={
                    "loss_pct": loss_pct, "equity": self._equity,
                    "equity_start": self._equity_start_of_day,
                })
                # Don't release lock — call internal flatten directly
                await self._flatten_all_positions_internal(reason)
                return True
        return False

    async def execute_kill_switch(self, reason: str = "Manual LIQUIDATE") -> dict:
        """
        External kill switch: cancels all open orders, flattens all positions to cash.
        DOES NOT release lock between individual sell orders — atomic w.r.t. state.
        """
        async with self._lock:
            return await self._flatten_all_positions_internal(reason)

    async def _flatten_all_positions_internal(self, reason: str) -> dict:
        """Must be called with _lock held."""
        self._state = EngineState.HALTED
        self._kill_switch_reason = reason
        flattened = []
        errors = []

        for symbol, pos in list(self._positions.items()):
            try:
                price = 0.0
                if self._mode == ExecutionMode.LIVE and self._breeze:
                    price = self._breeze_get_ltp(symbol)
                if price <= 0:
                    price = self._get_yfinance_ltp(symbol)
                if price <= 0:
                    price = pos.avg_entry_price

                rec = await self._submit_order_internal(
                    symbol=symbol,
                    side="SELL",
                    quantity=pos.quantity,
                    price=price,
                    signal_source="KILL_SWITCH",
                    stop_loss_price=0.0,
                )
                flattened.append({"symbol": symbol, "qty": pos.quantity, "price": price})
                logger.warning("Position flattened by kill switch", extra={
                    "symbol": symbol, "qty": pos.quantity
                })
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
                logger.error("Kill switch flatten failed for symbol", extra={
                    "symbol": symbol, "error": str(exc)
                })

        with self._get_db() as conn:
            self._persist_state(conn)
            self._update_daily_pnl(conn)
            conn.commit()

        logger.critical("ENGINE HALTED", extra={
            "reason": reason,
            "flattened": len(flattened),
            "errors": len(errors),
        })

        return {
            "halted": True,
            "reason": reason,
            "flattened_positions": flattened,
            "errors": errors,
            "equity_after": round(self._equity, 2),
        }

    async def _submit_order_internal(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        signal_source: str,
        stop_loss_price: float = 0.0,
    ) -> OrderRecord:
        """Internal version — must be called with _lock already held."""
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        broker_id = ""
        status = "REJECTED"
        notes = ""

        kx_cost = price * quantity * TRANSACTION_COST_PCT
        if self._mode == ExecutionMode.PAPER:
            if side == "BUY":
                self._cash -= (price * quantity + kx_cost)
            else:
                self._cash += (price * quantity - kx_cost)
            self._tx_costs_today += kx_cost
            broker_id = f"PAPER-{order_id[:8]}"
            status = "FILLED"
            notes = f"Paper fill @ ₹{price:.2f}; txcost ₹{kx_cost:.2f}"
        else:
            try:
                broker_id = self._breeze_place_order(symbol, side, quantity, price)
                if side == "BUY":
                    self._cash -= (price * quantity + kx_cost)
                else:
                    self._cash += (price * quantity - kx_cost)
                self._tx_costs_today += kx_cost
                status = "FILLED"
                notes = f"Live fill @ ₹{price:.2f}; txcost ₹{kx_cost:.2f}"
            except Exception as exc:
                status = "REJECTED"
                notes = f"Kill switch sell failed: {exc}"

        rec = OrderRecord(
            order_id=order_id, symbol=symbol, side=side, quantity=quantity,
            price=price, mode=self._mode.value, status=status,
            signal_source=signal_source, broker_order_id=broker_id,
            timestamp=now, notes=notes,
        )

        with self._get_db() as conn:
            self._log_order(conn, rec)
            if status == "FILLED":
                now_ts = now
                if side == "BUY":
                    if symbol in self._positions:
                        existing = self._positions[symbol]
                        total_qty = existing.quantity + quantity
                        avg_p = (existing.avg_entry_price * existing.quantity + price * quantity) / total_qty
                        pos = Position(
                            symbol=symbol, quantity=total_qty, avg_entry_price=avg_p,
                            signal_source=signal_source, entry_time=existing.entry_time,
                            stop_loss_price=stop_loss_price or existing.stop_loss_price,
                        )
                    else:
                        pos = Position(
                            symbol=symbol, quantity=quantity, avg_entry_price=price,
                            signal_source=signal_source, entry_time=now_ts,
                            stop_loss_price=stop_loss_price,
                        )
                    self._positions[symbol] = pos
                    self._persist_position(conn, pos)
                elif side == "SELL" and symbol in self._positions:
                    existing = self._positions[symbol]
                    remaining = existing.quantity - quantity
                    if remaining <= 0:
                        del self._positions[symbol]
                        self._delete_position(conn, symbol)
                    else:
                        pos = Position(
                            symbol=symbol, quantity=remaining,
                            avg_entry_price=existing.avg_entry_price,
                            signal_source=existing.signal_source,
                            entry_time=existing.entry_time,
                            stop_loss_price=existing.stop_loss_price,
                        )
                        self._positions[symbol] = pos
                        self._persist_position(conn, pos)
            conn.commit()

        return rec

    def _reference_price(self, symbol: str) -> float:
        """Current market price used to sanity-check order prices (0 = unknown)."""
        if self._mode == ExecutionMode.LIVE:
            ltp = self._breeze_get_ltp(symbol)
            if ltp > 0:
                return ltp
        return self._get_yfinance_ltp(symbol)

    async def _price_guard_error(self, symbol: str, price: float) -> str | None:
        """None when ``price`` is plausible vs the market, else a rejection reason."""
        if not self._price_guard_pct or self._price_guard_pct <= 0:
            return None
        ref = await asyncio.to_thread(self._reference_price, symbol)
        if ref <= 0:
            return (f"No market reference price for {symbol} — refusing to fill at a "
                    f"client-supplied price (₹{price:,.2f}). Retry when market data is available.")
        gap_pct = abs(price / ref - 1) * 100
        if gap_pct > self._price_guard_pct:
            return (f"Order price ₹{price:,.2f} for {symbol} is {gap_pct:,.1f}% away from the "
                    f"market price ₹{ref:,.2f} (limit {self._price_guard_pct:g}%) — rejected.")
        return None

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        signal_source: str,
        stop_loss_price: float = 0.0,
    ) -> dict:
        """Public order placement — validates price vs market, checks kill switch."""
        guard = await self._price_guard_error(symbol, price)
        if guard:
            logger.warning("Order rejected by price guard", extra={"symbol": symbol, "price": price})
            return {"error": guard, "status": "REJECTED", "symbol": symbol}
        async with self._lock:
            if self._state != EngineState.ACTIVE:
                return {
                    "error": f"Engine is {self._state.value} — no new orders allowed.",
                    "kill_switch_reason": self._kill_switch_reason,
                }
            rec = await self._submit_order_internal(
                symbol, side, quantity, price, signal_source, stop_loss_price
            )
        await self.check_daily_loss_limit()
        return asdict(rec)

    async def execute_scheduled(
        self,
        symbol: str,
        side: str,
        quantity: int,
        arrival_price: float,
        signal_source: str,
        algo: str = "TWAP",
        n_slices: int = 6,
        adv: float | None = None,
        volatility_bps: float = 80.0,
        impact_coef: float = 1.0,
        participation_cap: float = 0.10,
        max_participation: float = 0.25,
        stop_loss_price: float = 0.0,
    ) -> dict:
        """Sliced execution (G9): schedule child orders (TWAP/VWAP/POV), fill against
        finite per-bucket liquidity with √-law slippage and partial fills, then book the
        parent at the realised execution VWAP — not the naive arrival fill. Returns the
        booked order plus the implementation-shortfall report.

        PAPER-safe: every child fill is simulated in-process. The parent is booked via the
        same audited path as `place_order`, so positions/cash reflect true slippage. A
        fully-unfilled schedule (e.g. an order far larger than available liquidity) books
        nothing and reports `filled_qty=0` rather than silently assuming the fill.
        """
        guard = await self._price_guard_error(symbol, arrival_price)
        if guard:
            logger.warning("Scheduled order rejected by price guard",
                           extra={"symbol": symbol, "price": arrival_price})
            return {"order": None, "error": guard, "status": "REJECTED"}
        async with self._lock:
            if self._state != EngineState.ACTIVE:
                return {
                    "error": f"Engine is {self._state.value} — no new orders allowed.",
                    "kill_switch_reason": self._kill_switch_reason,
                }
            try:
                algo_enum = ExecutionAlgo(str(algo).upper())
            except ValueError:
                algo_enum = ExecutionAlgo.TWAP
            report = simulate_execution(
                symbol, side, int(quantity), float(arrival_price), algo=algo_enum,
                n_slices=n_slices, adv=adv, volatility_bps=volatility_bps,
                impact_coef=impact_coef, participation_cap=participation_cap,
                max_participation=max_participation,
            )
            rec = None
            if report.filled_qty > 0:
                # Book the parent at the slippage-adjusted VWAP for the qty we actually got.
                rec = await self._submit_order_internal(
                    symbol, side, report.filled_qty, report.avg_fill_price,
                    signal_source, stop_loss_price,
                )
                with self._get_db() as conn:
                    self._log_execution_report(conn, rec.order_id, report)
                    self._persist_state(conn)
                    self._update_daily_pnl(conn)
                    conn.commit()
        if rec is not None:
            await self.check_daily_loss_limit()
        return {
            "order": asdict(rec) if rec is not None else None,
            "execution": {
                **asdict(report),
                "fill_ratio": round(report.fill_ratio, 4),
            },
        }

    async def reset_engine(self, new_equity: float | None = None) -> dict:
        """
        Reset the halted engine for a new trading day.
        Only callable manually — never automatic.
        """
        async with self._lock:
            self._state = EngineState.ACTIVE
            self._kill_switch_reason = ""
            self._tx_costs_today = 0.0
            today_equity = new_equity if new_equity is not None else self._equity
            self._equity_start_of_day = today_equity
            with self._get_db() as conn:
                self._persist_state(conn)
                conn.commit()
        logger.info("Engine reset", extra={"equity_start": self._equity_start_of_day})
        return {"state": self._state.value, "equity_start_of_day": self._equity_start_of_day}


# ── Module-level singleton (shared across FastAPI routes) ──────────────────────

_engine: ExecutionEngine | None = None


def get_engine() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine(
            mode=ExecutionMode(os.environ.get("EXECUTION_MODE", "PAPER")),
            initial_equity=float(os.environ.get("INITIAL_EQUITY", "10000")),
            active_model=os.environ.get("ACTIVE_MODEL", "XGBoost"),
        )
    return _engine
