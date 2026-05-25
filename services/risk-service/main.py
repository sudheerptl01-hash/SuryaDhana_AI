from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from position_sizer import fractional_kelly, size_position
from risk_checks import run_all_checks, RiskCheckResult

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging("risk-service", settings.log_level)
    logger.info("Risk service started")
    yield
    logger.info("Risk service stopped")


app = FastAPI(title="SuryaDhana — Risk Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "risk-service"}


# ── Position sizing ────────────────────────────────────────────────────────────

class SizeRequest(BaseModel):
    portfolio_value_inr: float
    stock_price: float
    win_rate: float = 0.54
    avg_win_pct: float = 2.0
    avg_loss_pct: float = 2.0
    kelly_fraction: float = 0.5
    max_position_pct: float = 0.15


class SizeResponse(BaseModel):
    shares: int
    allocated_inr: float
    position_pct: float
    kelly_full: float
    kelly_fractional: float


@app.post("/size", response_model=SizeResponse)
async def size_position_endpoint(req: SizeRequest) -> SizeResponse:
    from position_sizer import kelly_fraction as kf
    full_kelly = kf(req.win_rate, req.avg_win_pct, req.avg_loss_pct)
    frac_kelly = fractional_kelly(req.win_rate, req.avg_win_pct, req.avg_loss_pct, req.kelly_fraction, req.max_position_pct)
    shares, allocated = size_position(req.portfolio_value_inr, frac_kelly, req.stock_price)
    return SizeResponse(
        shares=shares,
        allocated_inr=round(allocated, 2),
        position_pct=round(frac_kelly * 100, 2),
        kelly_full=round(full_kelly, 4),
        kelly_fractional=round(frac_kelly, 4),
    )


# ── Risk checks ────────────────────────────────────────────────────────────────

class RiskCheckRequest(BaseModel):
    ticker: str
    sector: str
    proposed_value_inr: float
    portfolio_value_inr: float
    current_positions: int
    existing_sector_value_inr: float = 0.0
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0


class RiskCheckResponse(BaseModel):
    all_passed: bool
    action: str
    checks: list[dict]


@app.post("/check", response_model=RiskCheckResponse)
async def check_risk(req: RiskCheckRequest) -> RiskCheckResponse:
    settings = get_settings()
    results = run_all_checks(
        ticker=req.ticker,
        sector=req.sector,
        proposed_value_inr=req.proposed_value_inr,
        portfolio_value_inr=req.portfolio_value_inr,
        current_positions=req.current_positions,
        existing_sector_value_inr=req.existing_sector_value_inr,
        daily_pnl_pct=req.daily_pnl_pct,
        drawdown_pct=req.drawdown_pct,
        max_position_pct=settings.max_position_pct,
        max_sector_pct=settings.max_sector_pct,
        max_positions=settings.max_portfolio_positions,
        daily_loss_limit=settings.daily_loss_limit_pct,
        max_drawdown=settings.max_drawdown_pct,
    )

    all_passed = all(r.passed for r in results)
    action = "allow"
    for r in results:
        if r.action == "halt":
            action = "halt"
            break
        if r.action == "reject":
            action = "reject"

    return RiskCheckResponse(
        all_passed=all_passed,
        action=action,
        checks=[{"passed": r.passed, "reason": r.reason, "action": r.action} for r in results],
    )
