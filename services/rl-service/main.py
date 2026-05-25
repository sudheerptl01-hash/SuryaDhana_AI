from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from agent import PPOPortfolioAgent

logger = get_logger(__name__)

_agent: PPOPortfolioAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _agent
    settings = get_settings()
    configure_logging("rl-service", settings.log_level)

    agent_path = "models/rl_agent_v1"
    if Path(f"{agent_path}.zip").exists():
        _agent = PPOPortfolioAgent.load(agent_path)
    else:
        logger.info("No trained RL agent found — will use fallback allocation until trained")
        _agent = PPOPortfolioAgent(
            max_positions=settings.max_portfolio_positions,
        )

    logger.info("RL service started", agent_ready=_agent is not None)
    yield
    logger.info("RL service stopped")


app = FastAPI(
    title="SuryaDhana — RL Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "rl-service",
        "agent_trained": _agent is not None and _agent._model is not None,
    }


# ── Training ───────────────────────────────────────────────────────────────────

class TrainAgentRequest(BaseModel):
    signals_data: list[list[dict]]  # list of daily signal batches
    total_timesteps: int = 100_000


@app.post("/train")
async def train_agent(req: TrainAgentRequest) -> dict:
    global _agent
    settings = get_settings()

    _agent = PPOPortfolioAgent(
        max_positions=settings.max_portfolio_positions,
        total_timesteps=req.total_timesteps,
    )
    _agent.train(req.signals_data)
    _agent.save("models/rl_agent_v1")

    return {"status": "trained", "timesteps": req.total_timesteps}


# ── Portfolio optimization ─────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    signals: list[dict]


class OptimizeResponse(BaseModel):
    allocations: dict[str, float]
    selected_count: int
    method: str


@app.post("/optimize/portfolio", response_model=OptimizeResponse)
async def optimize_portfolio(req: OptimizeRequest) -> OptimizeResponse:
    if _agent is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="RL agent not initialised")

    if not req.signals:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No signals provided")

    allocations = _agent.optimize(req.signals)
    method = "ppo" if _agent._model is not None else "equal_weight_fallback"

    return OptimizeResponse(
        allocations=allocations,
        selected_count=len(allocations),
        method=method,
    )
