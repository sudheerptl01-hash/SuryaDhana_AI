"""
Trade ticket: what a delivery trade really costs, from the same model every backtest uses (shared/trading_costs.py).

GET /api/costs/ticket?value=50000&price=707.25&atr_pct=2.18&stop_atr=2&capital=500000
→ shares, round-trip charges itemised (ICICI profile from COST_PROFILE), breakeven move, an ATR stop and the
  ₹ / % of capital at risk, and the tax on an illustrative +10 % gain (short- vs long-term). Read-only arithmetic.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.trading_costs import TaxRules, capital_gains_tax, default_model  # noqa: E402

router = APIRouter()


def ticket(value: float, price: float, atr_pct: float | None, stop_atr: float, capital: float | None) -> dict[str, Any]:
    model = default_model()
    qty = math.floor(value / price) if price > 0 else 0
    notional = qty * price
    rt = model.round_trip(notional)
    intraday = model.round_trip(notional, "intraday")
    out: dict[str, Any] = {
        "profile": model.broker.name, "price": price, "shares": qty, "notional": round(notional, 2),
        "round_trip": rt.as_dict(), "round_trip_pct": round(rt.pct_of(notional), 3) if notional else None,
        "breakeven_move_pct": round(model.breakeven_move_pct(notional), 3) if notional else None,
        "intraday_round_trip": intraday.as_dict(),
        "min_position_for_1pct": model.min_position_for(1.0),
    }
    if atr_pct and notional:
        stop = price * (1 - stop_atr * atr_pct / 100)
        loss = qty * (price - stop) + rt.total
        out["stop"] = {"atr_multiple": stop_atr, "price": round(stop, 2), "distance_pct": round(stop_atr * atr_pct, 2),
                       "loss_if_hit": round(loss, 2),
                       "loss_pct_of_capital": round(loss / capital * 100, 2) if capital else None}
    gain = notional * 0.10
    rules = TaxRules()
    st_tax, _ = capital_gains_tax(gain, 30, 0.0, rules)
    lt_tax, _ = capital_gains_tax(gain, 400, rules.ltcg_exemption, rules)
    out["tax_on_10pct_gain"] = {"gain": round(gain, 2), "short_term": st_tax, "long_term_with_exemption": lt_tax,
                                "rules": rules.as_of}
    return out


@router.get("/ticket")
def get_ticket(value: float = Query(50_000, gt=0, le=1e9), price: float = Query(..., gt=0, le=1e7),
               atr_pct: float | None = Query(None, gt=0, le=100), stop_atr: float = Query(2.0, gt=0, le=10),
               capital: float | None = Query(None, gt=0, le=1e10)) -> dict[str, Any]:
    return ticket(value, price, atr_pct, stop_atr, capital)
