"""Portfolio positions and account balance via ICICI Breeze API."""
from __future__ import annotations

import os
import re
from datetime import datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _extract_session_token(raw: str) -> str:
    """Handle both raw token and full redirect URL formats."""
    if raw.startswith("http"):
        m = re.search(r"apisession=([^&\s]+)", raw)
        return m.group(1) if m else raw
    return raw


@lru_cache(maxsize=1)
def _get_breeze_client():
    """Lazily construct and cache the BreezeConnect client."""
    api_key = os.environ.get("ICICI_API_KEY", "")
    api_secret = os.environ.get("ICICI_API_SECRET", "")
    raw_token = os.environ.get("ICICI_SESSION_TOKEN", "")

    if not (api_key and api_secret and raw_token):
        return None, "ICICI credentials not configured in .env"

    session_token = _extract_session_token(raw_token)

    try:
        import requests
        from breeze_connect import BreezeConnect

        # Apply connect timeout so startup never hangs
        _orig_get = requests.get
        def _get_with_timeout(url, **kw):
            kw.setdefault("timeout", 10)
            return _orig_get(url, **kw)
        requests.get = _get_with_timeout

        try:
            breeze = BreezeConnect(api_key=api_key)
            breeze.generate_session(api_secret=api_secret, session_token=session_token)
        finally:
            requests.get = _orig_get

        return breeze, None
    except Exception as exc:
        return None, str(exc)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val not in (None, "", "NA") else default
    except (TypeError, ValueError):
        return default


@router.get("/summary")
async def get_position_summary():
    """Account balance, invested value, P&L — from ICICI Breeze."""
    breeze, err = _get_breeze_client()
    if err:
        return {
            "connected": False,
            "error": err,
            "total_capital_inr": 0,
            "cash_available_inr": 0,
            "invested_value_inr": 0,
            "num_open_positions": 0,
            "total_pnl_inr": 0,
            "total_pnl_pct": 0,
            "max_drawdown_pct": 0,
        }

    try:
        # Fetch fund summary (available margin / cash)
        funds_resp = breeze.get_fund_limit(
            exchange_code="NSE",
            product_type="cash",
            cover_flag="N",
            fno_flag="N",
            brokerage_flag="N",
            physical_flag="N",
        )

        cash_balance = 0.0
        if funds_resp.get("Status") == 200:
            for item in funds_resp.get("Success") or []:
                if item.get("limit_type") == "0":
                    cash_balance = _safe_float(item.get("net_limit"))
                    break

        # Fetch portfolio holdings
        holdings_resp = breeze.get_portfolio_holdings(
            exchange_code="NSE",
            from_date="",
            to_date="",
            stock_code="",
            portfolio_type="",
        )

        invested = 0.0
        total_pnl = 0.0
        num_positions = 0

        if holdings_resp.get("Status") == 200:
            for h in holdings_resp.get("Success") or []:
                qty = _safe_float(h.get("quantity"))
                avg_price = _safe_float(h.get("average_cost"))
                ltp = _safe_float(h.get("market_value_per_share") or h.get("last_traded_price"))
                if qty > 0:
                    invested += qty * avg_price
                    total_pnl += qty * (ltp - avg_price)
                    num_positions += 1

        total_capital = cash_balance + invested
        pnl_pct = (total_pnl / invested * 100) if invested > 0 else 0.0

        return {
            "connected": True,
            "total_capital_inr": round(total_capital, 2),
            "cash_available_inr": round(cash_balance, 2),
            "invested_value_inr": round(invested, 2),
            "num_open_positions": num_positions,
            "total_pnl_inr": round(total_pnl, 2),
            "total_pnl_pct": round(pnl_pct, 2),
            "max_drawdown_pct": 0,
            "as_of": datetime.now().isoformat(),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Breeze API error: {exc}")


@router.get("/open-positions")
async def get_open_positions():
    """Current portfolio holdings with entry price, LTP, and P&L."""
    breeze, err = _get_breeze_client()
    if err:
        return {"connected": False, "error": err, "positions": []}

    try:
        resp = breeze.get_portfolio_holdings(
            exchange_code="NSE",
            from_date="",
            to_date="",
            stock_code="",
            portfolio_type="",
        )

        positions = []
        if resp.get("Status") == 200:
            for h in resp.get("Success") or []:
                qty = _safe_float(h.get("quantity"))
                if qty <= 0:
                    continue
                avg_price = _safe_float(h.get("average_cost"))
                ltp = _safe_float(h.get("market_value_per_share") or h.get("last_traded_price") or avg_price)
                invested = qty * avg_price
                current_val = qty * ltp
                pnl = current_val - invested
                pnl_pct = (pnl / invested * 100) if invested > 0 else 0.0
                positions.append({
                    "symbol": h.get("stock_code", ""),
                    "quantity": int(qty),
                    "buy_price": round(avg_price, 2),
                    "current_price": round(ltp, 2),
                    "invested": round(invested, 2),
                    "current_value": round(current_val, 2),
                    "pnl": round(pnl, 2),
                    "pnl_percent": round(pnl_pct, 2),
                })

        return {"connected": True, "positions": positions, "count": len(positions)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Breeze API error: {exc}")


@router.get("/trade-history")
async def get_trade_history(limit: int = 50):
    """Recent order history from ICICI Breeze."""
    breeze, err = _get_breeze_client()
    if err:
        return {"connected": False, "error": err, "trades": [], "total_trades": 0}

    try:
        from datetime import date, timedelta
        today = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()

        resp = breeze.get_order_list(
            exchange_code="NSE",
            from_date=week_ago,
            to_date=today,
        )

        trades = []
        if resp.get("Status") == 200:
            for o in (resp.get("Success") or [])[:limit]:
                trades.append({
                    "order_id": o.get("order_id"),
                    "symbol": o.get("stock_code"),
                    "side": o.get("action"),
                    "quantity": _safe_float(o.get("quantity")),
                    "price": _safe_float(o.get("average_price") or o.get("price")),
                    "status": o.get("status"),
                    "order_type": o.get("order_type"),
                    "timestamp": o.get("order_datetime"),
                })

        return {"connected": True, "trades": trades, "total_trades": len(trades)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Breeze API error: {exc}")


@router.get("/sector-exposure")
async def get_sector_exposure():
    """Current portfolio sector allocation derived from holdings."""
    breeze, err = _get_breeze_client()
    if err:
        return {"connected": False, "error": err, "sectors": {}}

    try:
        resp = breeze.get_portfolio_holdings(
            exchange_code="NSE",
            from_date="",
            to_date="",
            stock_code="",
            portfolio_type="",
        )

        sector_values: dict[str, float] = {}
        total = 0.0

        if resp.get("Status") == 200:
            for h in resp.get("Success") or []:
                qty = _safe_float(h.get("quantity"))
                if qty <= 0:
                    continue
                ltp = _safe_float(h.get("market_value_per_share") or h.get("last_traded_price"))
                val = qty * ltp
                sector = h.get("sector", "Unknown") or "Unknown"
                sector_values[sector] = sector_values.get(sector, 0.0) + val
                total += val

        sectors = {
            k: {"value": round(v, 2), "pct": round(v / total * 100, 1) if total else 0}
            for k, v in sorted(sector_values.items(), key=lambda x: -x[1])
        }

        return {"connected": True, "sectors": sectors, "total_invested": round(total, 2)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Breeze API error: {exc}")


class SessionTokenRequest(BaseModel):
    token: str


@router.post("/session-token")
async def update_session_token(req: SessionTokenRequest):
    """Update ICICI Breeze session token in-process and reconnect. No .env write needed."""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    session_token = _extract_session_token(token)
    os.environ["ICICI_SESSION_TOKEN"] = session_token

    # Clear cache so next call uses new token
    _get_breeze_client.cache_clear()

    # Eagerly test the new connection
    breeze, err = _get_breeze_client()
    if err:
        return {"connected": False, "error": err}

    return {"connected": True, "message": "Session token updated and Breeze reconnected"}


@router.post("/refresh-session")
async def refresh_breeze_session():
    """Force reconnect — clears cached Breeze client so next call re-connects."""
    _get_breeze_client.cache_clear()
    return {"status": "cache_cleared", "message": "Next API call will reconnect to Breeze"}
