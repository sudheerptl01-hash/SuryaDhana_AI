"""
Decision Desk: turns the approved monthly momentum strategy into concrete monthly
actions (a Decision Brief), paper-executes them at NSE's official opening price, and
keeps an auditable book: orders, fills, FIFO tax lots, daily NAV, emergency stop.

Paper only: nothing here talks to a broker.

Daily cycle (called once each evening after the EOD data pipeline, see
master_controller.desk_daily):
  1. load the last ~22 months of the survivorship-free NSE panel + NIFTY
  2. for every new session since the last run:
       accrue liquid-fund yield · apply splits/bonuses to holdings · execute any
       pending plan at that session's official OPEN · settle tax at FY change ·
       mark NAV at the CLOSE · check the −20% emergency stop
  3. if the latest session is the last one of its month, create next month's
     Decision Brief (signal = that close, execution = next session's open)

Decisions come from shared.momentum.compute_targets, the same function the
backtest uses (scripts/phase_b_allocator.py), so live cannot drift from what was tested.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from dataclasses import replace

from shared.momentum import StrategyConfig, compute_targets, industries, signals
from shared.trading_costs import CostModel, TaxRules, capital_gains_tax

IST = ZoneInfo("Asia/Kolkata")
LOOKBACK_DAYS = 700            # ≥ 252 sessions for 12-month momentum + 1-year volatility, with margin
STALE_SESSIONS = 5             # unfilled orders expire after this many sessions
MarketLoader = Callable[[date], tuple[dict[str, pd.DataFrame], pd.Series]]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY, cycle TEXT, kind TEXT, signal_date TEXT, created_at TEXT,
    status TEXT, executed_date TEXT, risk_on INTEGER, exposure REAL, summary TEXT);
CREATE TABLE IF NOT EXISTS orders (
    plan_id TEXT, symbol TEXT, side TEXT, est_qty INTEGER, est_price REAL, est_value REAL,
    est_cost REAL, reason TEXT, rank INTEGER, score REAL, sector TEXT,
    status TEXT, fill_qty INTEGER, fill_price REAL, fill_cost REAL, fill_date TEXT,
    PRIMARY KEY (plan_id, symbol, side));
CREATE TABLE IF NOT EXISTS lots (symbol TEXT, qty REAL, cost_per_share REAL, buy_date TEXT);
CREATE TABLE IF NOT EXISTS nav (
    date TEXT PRIMARY KEY, nav REAL, cash REAL, holdings REAL, positions INTEGER,
    nifty REAL, peak REAL, drawdown REAL);
CREATE TABLE IF NOT EXISTS realized (fy TEXT PRIMARY KEY, st REAL, lt REAL, tax_paid REAL);
CREATE TABLE IF NOT EXISTS events (ts TEXT, kind TEXT, message TEXT);
"""


@contextmanager
def _db(path: Path, lock: threading.Lock) -> Iterator[sqlite3.Connection]:
    with lock:
        conn = sqlite3.connect(path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def fy_of(d: date) -> str:
    return f"FY{d.year + 1 if d.month >= 4 else d.year}"


def next_weekday(d: date) -> date:
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


@dataclass
class Desk:
    ledger_path: Path
    cfg: StrategyConfig
    costs: CostModel
    load_market: MarketLoader
    start_capital: float = 500_000.0

    def __post_init__(self) -> None:
        self.ledger_path = Path(self.ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            if not c.execute("SELECT 1 FROM meta WHERE key='cash'").fetchone():
                self._set(c, "cash", self.start_capital)
                self._set(c, "start_capital", self.start_capital)
                self._set(c, "peak", self.start_capital)
                self._set(c, "stopped", 0)
                self._set(c, "config", json.dumps(self.cfg.as_dict()))
                self._set(c, "cost_profile", self.costs.broker.name)
                self._event(c, "INIT", f"Paper book opened with ₹{self.start_capital:,.0f}; rules {self.cfg.name}, "
                                       f"equity share {self.cfg.equity_share:.0%}")

    # ── ledger primitives ───────────────────────────────────────────────────────

    def _conn(self):
        return _db(self.ledger_path, self._lock)

    @staticmethod
    def _set(c: sqlite3.Connection, key: str, value) -> None:
        c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))

    @staticmethod
    def _get(c: sqlite3.Connection, key: str, default=None):
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    @staticmethod
    def _event(c: sqlite3.Connection, kind: str, message: str) -> None:
        c.execute("INSERT INTO events VALUES (?, ?, ?)", (datetime.now(IST).isoformat(), kind, message))

    @staticmethod
    def _holdings(c: sqlite3.Connection) -> dict[str, float]:
        return {r["symbol"]: r["q"] for r in c.execute(
            "SELECT symbol, SUM(qty) q FROM lots GROUP BY symbol HAVING SUM(qty) > 1e-9")}

    # ── trading primitives (paper) ──────────────────────────────────────────────

    def _sell(self, c: sqlite3.Connection, sym: str, px: float, day: date) -> tuple[float, float, float]:
        """Sell the whole holding at px. Returns (qty, proceeds net of cost, cost)."""
        lots = c.execute("SELECT rowid, qty, cost_per_share, buy_date FROM lots WHERE symbol=? ORDER BY buy_date, rowid",
                         (sym,)).fetchall()
        qty = sum(l["qty"] for l in lots)
        if qty <= 0:
            return 0.0, 0.0, 0.0
        value = qty * px
        cost = self.costs.leg(value, "sell").total
        st = lt = 0.0
        for l in lots:
            gain = l["qty"] * (px - l["cost_per_share"]) - cost * (l["qty"] / qty)
            if (day - date.fromisoformat(l["buy_date"])).days > 365:
                lt += gain
            else:
                st += gain
        c.execute("DELETE FROM lots WHERE symbol=?", (sym,))
        fy = fy_of(day)
        c.execute("INSERT INTO realized VALUES (?, 0, 0, 0) ON CONFLICT(fy) DO NOTHING", (fy,))
        c.execute("UPDATE realized SET st = st + ?, lt = lt + ? WHERE fy = ?", (st, lt, fy))
        self._set(c, "cash", self._get(c, "cash") + value - cost)
        return qty, value - cost, cost

    def _buy(self, c: sqlite3.Connection, sym: str, target_value: float, px: float, day: date) -> tuple[int, float]:
        """Buy whole shares worth ≤ target_value at px. Returns (qty, cost)."""
        cash = self._get(c, "cash")
        qty = math.floor(min(target_value, cash) / px) if px > 0 else 0
        while qty > 0 and qty * px + self.costs.leg(qty * px, "buy").total > cash:
            qty -= 1
        if qty <= 0:
            return 0, 0.0
        value = qty * px
        cost = self.costs.leg(value, "buy").total
        c.execute("INSERT INTO lots VALUES (?, ?, ?, ?)", (sym, qty, (value + cost) / qty, day.isoformat()))
        self._set(c, "cash", cash - value - cost)
        return qty, cost

    def _settle_tax(self, c: sqlite3.Connection, fy: str, rules: TaxRules = TaxRules()) -> float:
        row = c.execute("SELECT st, lt, tax_paid FROM realized WHERE fy=?", (fy,)).fetchone()
        if not row or row["tax_paid"]:
            return 0.0
        st, lt = row["st"], row["lt"]
        if st < 0:
            lt += st
            st = 0.0
        tax = capital_gains_tax(max(st, 0), 1, 0, rules)[0] + capital_gains_tax(max(lt, 0), 400,
                                                                                 rules.ltcg_exemption, rules)[0]
        c.execute("UPDATE realized SET tax_paid=? WHERE fy=?", (tax if tax > 0 else 1e-9, fy))
        if tax > 0:
            self._set(c, "cash", self._get(c, "cash") - tax)
            self._event(c, "TAX", f"{fy} capital-gains tax ₹{tax:,.0f} (STCG {st:,.0f}, LTCG {lt:,.0f})")
        return tax

    # ── market helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _raw(panel: dict, field: str, day: pd.Timestamp, sym: str) -> float:
        """Real (unadjusted) price as NSE printed it that day."""
        try:
            adj = panel[field].at[day, sym]
            factor = panel["close"].at[day, sym] / panel["raw_close"].at[day, sym]
        except KeyError:
            return float("nan")
        return float(adj / factor) if np.isfinite(adj) and np.isfinite(factor) and factor > 0 else float("nan")

    def _book_value(self, c: sqlite3.Connection, panel: dict, day: pd.Timestamp, field: str = "close") -> float:
        hv = 0.0
        last = self._get(c, "last_px", {}) or {}
        for sym, q in self._holdings(c).items():
            px = self._raw(panel, field, day, sym)
            if not np.isfinite(px):
                px = last.get(sym, 0.0)
            hv += q * px
        return hv

    # ── plans ───────────────────────────────────────────────────────────────────

    def _nav_curve(self, c: sqlite3.Connection) -> pd.Series:
        rows = c.execute("SELECT date, nav FROM nav ORDER BY date").fetchall()
        return pd.Series({pd.Timestamp(r["date"]): r["nav"] for r in rows}, dtype=float)

    def build_plan(self, c: sqlite3.Connection, panel: dict, sig: dict, nifty: pd.Series, s: int,
                   kind: str = "REBALANCE") -> dict:
        """Decision Brief for signal row s (not persisted here)."""
        sday = panel["close"].index[s]
        held = set(self._holdings(c))
        curve = self._nav_curve(c)
        # vol target is defined on the strategy book; the total NAV holds equity_share of it
        book_curve = None
        if self.cfg.overlay == "nifty200_vt" and len(curve) > 60:
            r = curve.pct_change().fillna(0) / max(self.cfg.equity_share, 1e-9)
            book_curve = (1 + r).cumprod()
        dec = compute_targets(self.cfg, panel, sig, nifty, s, held, book_curve)
        targets = [] if kind == "EMERGENCY_EXIT" else dec.targets
        score = sig[self.cfg.signal if self.cfg.signal != "blend" else "mom_nse"].iloc[s]
        uni_scores = score.reindex(dec.targets).dropna()
        # rank within the same liquid universe the selection uses (so it matches the buffer rule)
        ranked = score.reindex(dec.universe or []).dropna().sort_values(ascending=False)
        rank = {sym: i + 1 for i, sym in enumerate(ranked.index)}
        secs = industries()
        nav = self._get(c, "cash") + self._book_value(c, panel, sday)
        per_name = min(self.cfg.equity_share * nav * dec.exposure / max(self.cfg.n, 1),
                       self.cfg.max_position_pct * nav)
        orders = []
        for sym in sorted(held - set(targets)):
            px = self._raw(panel, "close", sday, sym)
            q = self._holdings(c)[sym]
            if kind == "EMERGENCY_EXIT":
                why = f"EMERGENCY STOP: portfolio drawdown reached {self.cfg.emergency_dd:.0%}"
            elif not dec.risk_on:
                why = "Risk-off: NIFTY closed below its 200-day average → move to liquid fund"
            elif sym in rank and rank[sym] <= int(self.cfg.buffer * self.cfg.n):
                why = f"Momentum rank {rank[sym]}: sector cap reached (max {int(self.cfg.sector_cap * self.cfg.n) if self.cfg.sector_cap else '-'} per industry)"
            elif sym in rank:
                why = f"Momentum rank fell to {rank[sym]} (kept only while ≤ {int(self.cfg.buffer * self.cfg.n)})"
            else:
                why = "Left the liquid universe (liquidity/price/series filter)"
            est = q * px if np.isfinite(px) else 0.0
            orders.append({"symbol": sym, "side": "SELL", "est_qty": int(q), "est_price": px, "est_value": est,
                           "est_cost": self.costs.leg(est, "sell").total if est else 0.0, "reason": why,
                           "rank": rank.get(sym), "score": float(score.get(sym, np.nan)), "sector": secs.get(sym, "Unknown")})
        for sym in [t for t in targets if t not in held]:
            px = self._raw(panel, "close", sday, sym)
            q = math.floor(per_name / px) if np.isfinite(px) and px > 0 else 0
            r6, r12 = sig["ret6"].iloc[s].get(sym, np.nan), sig["ret12"].iloc[s].get(sym, np.nan)
            orders.append({"symbol": sym, "side": "BUY", "est_qty": q, "est_price": px, "est_value": q * px,
                           "est_cost": self.costs.leg(q * px, "buy").total if q else 0.0,
                           "reason": f"Momentum rank {rank.get(sym)} of {len(ranked)} · 6m {r6:+.0%} · 12m {r12:+.0%}"
                                     + ("" if q else " · price too high for the slot (skipped)"),
                           "rank": rank.get(sym), "score": float(uni_scores.get(sym, np.nan)),
                           "sector": secs.get(sym, "Unknown")})
        # informational: what the strategy would hold if the crash filter were off / once it clears
        watch = dec.targets if dec.risk_on else compute_targets(replace(self.cfg, overlay="none"), panel, sig,
                                                                nifty, s, held).targets
        watchlist = [{"symbol": w, "rank": rank.get(w), "sector": secs.get(w, "Unknown"),
                      "ret6": float(sig["ret6"].iloc[s].get(w, np.nan)), "ret12": float(sig["ret12"].iloc[s].get(w, np.nan)),
                      "close": self._raw(panel, "close", sday, w)} for w in watch]
        nv = float(nifty.asof(sday))
        nm = float(nifty.rolling(200).mean().asof(sday))
        summary = {
            "signal_date": str(sday.date()), "kind": kind, "risk_on": dec.risk_on,
            "nifty": round(nv, 2), "nifty_200dma": round(nm, 2), "exposure": round(dec.exposure, 3),
            "equity_share": self.cfg.equity_share, "nav_estimate": round(nav, 2), "per_name_target": round(per_name, 2),
            "holding_after": sorted((held - {o["symbol"] for o in orders if o["side"] == "SELL"})
                                    | {o["symbol"] for o in orders if o["side"] == "BUY" and o["est_qty"] > 0}),
            "trades": len(orders), "est_costs": round(sum(o["est_cost"] for o in orders), 2),
            "universe_size": dec.universe_size, "rules": self.cfg.name,
            "blocked_new_entries": dec.blocked or [],
            "watchlist": watchlist,
        }
        return {"summary": summary, "orders": orders, "risk_on": dec.risk_on, "exposure": dec.exposure,
                "signal_date": sday}

    def _persist_plan(self, c: sqlite3.Connection, plan: dict, cycle: str, kind: str) -> str:
        pid = f"{cycle}-{kind[:3]}-{uuid.uuid4().hex[:6]}"
        c.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?)",
                  (pid, cycle, kind, str(plan["signal_date"].date()), datetime.now(IST).isoformat(),
                   int(plan["risk_on"]), plan["exposure"], json.dumps(plan["summary"], default=str)))
        for o in plan["orders"]:
            c.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?, 'PENDING', NULL, NULL, NULL, NULL)",
                      (pid, o["symbol"], o["side"], o["est_qty"], o["est_price"], o["est_value"], o["est_cost"],
                       o["reason"], o["rank"], o["score"], o["sector"]))
        self._event(c, "PLAN", f"{kind} brief {pid}: {len(plan['orders'])} orders, signal {plan['signal_date'].date()}")
        return pid

    def _execute(self, c: sqlite3.Connection, pid: str, panel: dict, day: pd.Timestamp) -> dict:
        """Fill a pending plan at `day`'s official open: sells first, then buys sized at the open."""
        orders = c.execute("SELECT * FROM orders WHERE plan_id=? AND status='PENDING'", (pid,)).fetchall()
        filled = []
        for o in [o for o in orders if o["side"] == "SELL"]:
            px = self._raw(panel, "open", day, o["symbol"])
            if not np.isfinite(px):
                continue                                  # not traded today → retry next session
            qty, _, cost = self._sell(c, o["symbol"], px, day.date())
            c.execute("UPDATE orders SET status='FILLED', fill_qty=?, fill_price=?, fill_cost=?, fill_date=? "
                      "WHERE plan_id=? AND symbol=? AND side='SELL'", (qty, px, cost, str(day.date()), pid, o["symbol"]))
            filled.append(("SELL", o["symbol"], qty, px))
        plan = c.execute("SELECT * FROM plans WHERE plan_id=?", (pid,)).fetchone()
        summary = json.loads(plan["summary"])
        nav_open = self._get(c, "cash") + self._book_value(c, panel, day, "open")
        per_name = min(self.cfg.equity_share * nav_open * (plan["exposure"] or 1.0) / max(self.cfg.n, 1),
                       self.cfg.max_position_pct * nav_open)
        for o in [o for o in orders if o["side"] == "BUY"]:
            px = self._raw(panel, "open", day, o["symbol"])
            if not np.isfinite(px):
                continue
            qty, cost = self._buy(c, o["symbol"], per_name, px, day.date())
            status = "FILLED" if qty else "SKIPPED"
            c.execute("UPDATE orders SET status=?, fill_qty=?, fill_price=?, fill_cost=?, fill_date=? "
                      "WHERE plan_id=? AND symbol=? AND side='BUY'", (status, qty, px, cost, str(day.date()), pid,
                                                                      o["symbol"]))
            filled.append(("BUY", o["symbol"], qty, px))
        left = c.execute("SELECT COUNT(*) FROM orders WHERE plan_id=? AND status='PENDING'", (pid,)).fetchone()[0]
        if not left:
            c.execute("UPDATE plans SET status='EXECUTED', executed_date=? WHERE plan_id=?", (str(day.date()), pid))
        self._event(c, "FILL", f"{pid} @ {day.date()} open: {len(filled)} fills, {left} pending "
                               f"(per-name target ₹{per_name:,.0f}, rules {summary.get('rules')})")
        return {"plan_id": pid, "fills": filled, "pending": left}

    # ── the daily cycle ─────────────────────────────────────────────────────────

    def daily(self, today: Optional[date] = None) -> dict:
        today = today or datetime.now(IST).date()
        panel, nifty = self.load_market(today - timedelta(days=LOOKBACK_DAYS))
        sig = signals(panel)
        idx = panel["close"].index
        ca = panel.get("corporate_actions")
        out = {"sessions_marked": 0, "executions": [], "plan": None, "emergency": False}
        with self._conn() as c:
            last_mark = self._get(c, "last_mark")
            new_days = [d for d in idx if last_mark is None or d > pd.Timestamp(last_mark)]
            if last_mark is None:
                new_days = new_days[-1:]                  # a new book starts at the latest close
            daily_cash = (1 + self.cfg.cash_yield) ** (1 / 252) - 1
            for day in new_days:
                if last_mark is not None:
                    self._set(c, "cash", self._get(c, "cash") * (1 + daily_cash))
                # splits/bonuses on held names: more shares, lower cost per share
                if ca is not None and len(ca):
                    for ev in ca[ca["date"] == day].itertuples():
                        if ev.symbol in self._holdings(c):
                            c.execute("UPDATE lots SET qty = qty / ?, cost_per_share = cost_per_share * ? "
                                      "WHERE symbol=?", (ev.k, ev.k, ev.symbol))
                            self._event(c, "CORP_ACTION", f"{ev.symbol} factor {ev.k:.4g} on {day.date()} ({ev.source})")
                prev_fy = self._get(c, "fy")
                if prev_fy and prev_fy != fy_of(day.date()):
                    self._settle_tax(c, prev_fy)
                self._set(c, "fy", fy_of(day.date()))
                for p in c.execute("SELECT plan_id, signal_date FROM plans WHERE status='PENDING' AND signal_date < ? "
                                   "ORDER BY created_at", (str(day.date()),)).fetchall():
                    out["executions"].append(self._execute(c, p["plan_id"], panel, day))
                    waited = int(((idx > pd.Timestamp(p["signal_date"])) & (idx <= day)).sum())
                    if waited >= STALE_SESSIONS:          # e.g. suspended stock: give up, don't block the book
                        n = c.execute("UPDATE orders SET status='EXPIRED' WHERE plan_id=? AND status='PENDING'",
                                      (p["plan_id"],)).rowcount
                        c.execute("UPDATE plans SET status='EXECUTED', executed_date=? WHERE plan_id=? "
                                  "AND status='PENDING'", (str(day.date()), p["plan_id"]))
                        if n:
                            self._event(c, "EXPIRED", f"{p['plan_id']}: {n} orders unfilled after {waited} sessions")
                # mark at the close
                last_px = self._get(c, "last_px", {}) or {}
                for sym in self._holdings(c):
                    px = self._raw(panel, "close", day, sym)
                    if np.isfinite(px):
                        last_px[sym] = px
                self._set(c, "last_px", last_px)
                hv = self._book_value(c, panel, day)
                nav = self._get(c, "cash") + hv
                peak = max(self._get(c, "peak"), nav)
                dd = nav / peak - 1
                self._set(c, "peak", peak)
                c.execute("INSERT OR REPLACE INTO nav VALUES (?,?,?,?,?,?,?,?)",
                          (str(day.date()), nav, self._get(c, "cash"), hv, len(self._holdings(c)),
                           float(nifty.asof(day)), peak, dd))
                self._set(c, "last_mark", str(day.date()))
                out["sessions_marked"] += 1
                if dd <= self.cfg.emergency_dd and not self._get(c, "stopped") and self._holdings(c):
                    self._set(c, "stopped", 1)
                    s = idx.get_loc(day)
                    self._persist_plan(c, self.build_plan(c, panel, sig, nifty, s, "EMERGENCY_EXIT"),
                                       f"{day:%Y-%m}-E", "EMERGENCY_EXIT")
                    self._event(c, "EMERGENCY", f"Drawdown {dd:.1%} ≤ {self.cfg.emergency_dd:.0%}: "
                                                "selling everything at the next open; re-enable manually")
                    out["emergency"] = True

            # month-end: create next month's brief once (signal = last session of the month)
            latest = idx[-1]
            month_end = next_weekday(today).month != latest.month or today.month != latest.month
            cycle = f"{(latest + pd.offsets.MonthBegin(1)):%Y-%m}"
            exists = c.execute("SELECT 1 FROM plans WHERE cycle=? AND kind='REBALANCE'", (cycle,)).fetchone()
            if month_end and not exists and not self._get(c, "stopped"):
                plan = self.build_plan(c, panel, sig, nifty, len(idx) - 1)
                pid = self._persist_plan(c, plan, cycle, "REBALANCE")
                out["plan"] = {"plan_id": pid, **plan["summary"]}
        return out

    def preview(self, today: Optional[date] = None) -> dict:
        """What would the brief say if the month ended at the latest close? (Not saved.)"""
        today = today or datetime.now(IST).date()
        panel, nifty = self.load_market(today - timedelta(days=LOOKBACK_DAYS))
        sig = signals(panel)
        with self._conn() as c:
            plan = self.build_plan(c, panel, sig, nifty, len(panel["close"].index) - 1)
        return {"summary": plan["summary"], "orders": plan["orders"]}

    # ── read side ───────────────────────────────────────────────────────────────

    def reenable(self) -> dict:
        with self._conn() as c:
            self._set(c, "stopped", 0)
            nav = c.execute("SELECT nav FROM nav ORDER BY date DESC LIMIT 1").fetchone()
            if nav:
                self._set(c, "peak", nav["nav"])          # new peak baseline after a manual review
            self._event(c, "REENABLE", "Emergency stop cleared by the owner")
        return {"stopped": False}

    def status(self) -> dict:
        with self._conn() as c:
            meta = {k: self._get(c, k) for k in ("cash", "start_capital", "peak", "stopped", "last_mark",
                                                  "cost_profile", "config")}
            nav = [dict(r) for r in c.execute("SELECT * FROM nav ORDER BY date")]
            last_px = self._get(c, "last_px", {}) or {}
            positions = []
            for r in c.execute("SELECT symbol, SUM(qty) q, SUM(qty*cost_per_share)/SUM(qty) avg, MIN(buy_date) since "
                               "FROM lots GROUP BY symbol HAVING SUM(qty) > 1e-9 ORDER BY symbol"):
                px = last_px.get(r["symbol"])
                positions.append({"symbol": r["symbol"], "qty": r["q"], "avg_cost": r["avg"], "last": px,
                                  "value": r["q"] * px if px else None,
                                  "pnl_pct": (px / r["avg"] - 1) * 100 if px and r["avg"] else None,
                                  "since": r["since"], "sector": industries().get(r["symbol"], "Unknown")})
            plans = [dict(r) for r in c.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 12")]
            for p in plans:
                p["summary"] = json.loads(p["summary"])
                p["orders"] = [dict(o) for o in c.execute("SELECT * FROM orders WHERE plan_id=? ORDER BY side DESC, rank",
                                                          (p["plan_id"],))]
            events = [dict(r) for r in c.execute("SELECT * FROM events ORDER BY ts DESC LIMIT 50")]
            realized = [dict(r) for r in c.execute("SELECT * FROM realized ORDER BY fy")]
        latest = nav[-1] if nav else None
        meta["config"] = json.loads(meta["config"]) if isinstance(meta["config"], str) else meta["config"]
        return {"meta": meta, "latest": latest, "positions": positions, "plans": plans, "nav": nav,
                "events": events, "realized": realized}
