# SuryaDhana AI — CLAUDE.md

## Project

Quantitative Algorithmic Trading System for NSE/BSE Indian stocks.
- **Exchange**: NSE India (100 selected large/mid-cap stocks)
- **Strategy**: XGBoost ML signals → RL portfolio optimization → ICICI Breeze execution
- **Horizon**: 5-day holding period per trade
- **Capital**: ₹10,000 starting (scalable to ₹100M+)

## Python Environment

Always use:
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python
/Users/sudheer/Desktop/jupyter_env/bin/pip install <package>
```

Never use system Python, pyenv, or conda.

## Architecture

7 independent FastAPI microservices + 1 API gateway:

| Service | Port | Responsibility |
|---------|------|----------------|
| `api-gateway` | 8000 | Single entry point, routing, auth |
| `data-service` | 8001 | OHLCV fetch (yfinance historical, ICICI live), DuckDB |
| `feature-service` | 8002 | 40+ technical indicators, 5-day return labels |
| `ml-service` | 8003 | XGBoost classifier + regressor, walk-forward, SHAP |
| `rl-service` | 8004 | Portfolio optimization (Stable-Baselines3 PPO) |
| `risk-service` | 8005 | Kelly Criterion sizing, position/sector limits |
| `execution-service` | 8006 | ICICI Breeze order placement + fill tracking |
| `monitoring-service` | 8007 | Telegram alerts, Prometheus metrics, daily reports |

Shared infrastructure: DuckDB (time-series DB), Redis (pub/sub + Celery task queue).

## Key Files

- `shared/models/` — Pydantic v2 schemas (Stock, OHLCV, Signal, Order, Portfolio)
- `shared/config.py` — All config via Pydantic Settings (reads `.env`)
- `shared/logging.py` — Structured JSON logging with correlation IDs
- `data/FINAL_100_STOCKS.csv` — Locked stock universe (100 NSE stocks)
- `data/market.duckdb` — Central time-series database

## Data Sources

- **Historical**: yfinance (5 years of NSE OHLCV data, free)
- **Live/Execution**: ICICI Direct Breeze API (requires credentials in `.env`)

## Trading Rules (DO NOT CHANGE without review)

- Max 5 simultaneous positions
- Max 15% of portfolio per stock
- Max 40% of portfolio per sector
- Per-trade stop-loss: **k·ATR volatility-adaptive** (k=2.0 default), optional minimum-width floor (`stop_floor_pct`, default off). _Approved review change (audit §3.4): relaxed from the old fixed -2% cap so high-ATR storm names get a wider stop (≈6.5% on the median name) instead of being knocked out on noise. Applies to the per-trade stop only._
- Time-stop: exit after 5 trading days
- Daily loss limit: -2% → halt trading for the day (HARD — unchanged)
- Max drawdown: -20% → emergency stop (HARD — unchanged)

## Anti-Patterns (Critical)

- **NEVER** use future data in feature calculation (look-ahead bias)
- **NEVER** shuffle time-series data before train/test split
- **NEVER** hardcode API keys, secrets, or credentials
- **NEVER** skip walk-forward validation for backtests
- **NEVER** account for < 0.15% total transaction costs per trade

## Running Services

```bash
# Full stack
docker compose -f infra/docker-compose.yml up

# Single service (dev)
cd services/data-service
/Users/sudheer/Desktop/jupyter_env/bin/python -m uvicorn main:app --reload --port 8001

# Tests
/Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests/ -v --cov

# Type check
/Users/sudheer/Desktop/jupyter_env/bin/python -m mypy shared/ services/ --ignore-missing-imports
```

## Development Workflow

1. Each service is independently runnable with `uvicorn main:app --reload`
2. All services expose `/health`, `/ready`, `/metrics` endpoints
3. Inter-service communication via async HTTP (httpx) through internal Docker DNS
4. Redis pub/sub for events: `signal.generated`, `order.filled`, `stop_loss.triggered`
5. All config reads from `.env` via `shared/config.py`

## 16-Week Roadmap

| Phase | Weeks | Deliverable | Status |
|-------|-------|-------------|--------|
| 1 | 1–3   | `data/FINAL_100_STOCKS.csv` | ⏳ |
| 2 | 4–6   | DuckDB + ICICI API + 5yr data | ⏸ |
| 3 | 7–9   | 40+ features + labels | ⏸ |
| 4 | 10–12 | XGBoost models (55%+ accuracy) | ⏸ |
| 5 | 13–14 | Walk-forward backtest + RL agent | ⏸ |
| 6 | 15–16 | Paper trading → live ₹10K | ⏸ |
