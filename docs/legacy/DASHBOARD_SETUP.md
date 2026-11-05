# SuryaDhana Dashboard — Setup Guide

## Overview

The dashboard is a **two-tier system**:

1. **FastAPI ui-api service** (port 8010) — reads from DuckDB, exposes REST endpoints
2. **Next.js frontend** (port 3000) — beautiful UI with modular components

## Quick Start (Dev Mode)

### Terminal 1: Start ui-api service

```bash
cd services/ui-api
/Users/sudheer/Desktop/jupyter_env/bin/pip install -r requirements.txt
/Users/sudheer/Desktop/jupyter_env/bin/python -m uvicorn main:app --reload --port 8010
```

Visit http://localhost:8010/docs to see all API endpoints.

### Terminal 2: Start Next.js frontend

```bash
cd ui
npm install  # (first time only)
npm run dev
```

Visit http://localhost:3000

---

## What You'll See

### 📊 **Overview Tab**
- **System Health** section: Total stocks, data freshness, fundamentals coverage, date range
- **Status** section: Green/yellow/red indicator based on data staleness
- **CTA button** to explore stocks

### 📈 **Stocks Tab**
- **Paginated table** of all stocks with:
  - Ticker + latest price
  - Data coverage (years & row count)
  - **Density bar** — visual % of data completeness
  - Last update + color-coded freshness (mint = fresh, coral = stale)
  - Quality badge (Excellent/Good/Fair/Poor)
- **Click any row** to open detailed modal

### 🔬 **Analysis Tab** (Future)
- Will show: signal coverage, feature quality, label distribution
- Populated after running `ml-service` and `feature-service`

### 💰 **Portfolio Tab** (Future)
- Will show: open positions, balance, P&L, trade history
- Populated during paper trading phase

---

## Stock Detail Modal — What You'll See

Click any stock row to see **deep-dive inspection**:

### 📊 OHLCV Data
- Total rows: `119,365` (example for 96 tickers × 5yr)
- Data density: `97.3%` (green bar showing % coverage)
- **Missing days**: How many gaps exist in the date range
- Date range: `2021-05-14 → 2026-05-22`

### 💼 Fundamentals (if available)
- P/E, P/B, ROE, Debt/Equity, Dividend Yield, Sector
- Analyst recommendation (if enriched)

### 📅 Upcoming Events
- Earnings date
- Ex-dividend date

### ✓ Data Quality Summary
- Overall status: Excellent/Good/Fair/Poor
- Days since last update
- Completeness %

### Additional Info
- Dividend history count
- Stock split count

---

## Color Palette (By Design)

| Color | Use Case | Meaning |
|---|---|---|
| **Mint** 🟢 | Positive, health, fresh | Data is current, system OK |
| **Coral** 🟠 | Warning, caution | Data is stale, attention needed |
| **Lavender** 🟣 | Info, future insights | Fundamentals, upcoming events |
| **Slate** ⚫ | Neutral, base text | Normal UI, no special meaning |

---

## Architecture — Why This Design

### FastAPI ui-api (`services/ui-api/`)
- **Reason**: DuckDB is a query engine, not a REST API. The FastAPI service acts as a translation layer
- **Modularity**: Each router (`dashboard.py`, `stocks.py`, etc.) is independent and testable
- **Future-proof**: Can add caching, auth, rate-limiting without touching the frontend
- **Scalability**: One api-api instance can serve many dashboard instances (e.g., multiple users)

### Next.js Frontend (`ui/`)
- **Modular Components**:
  - `KPICard`: Reusable metric display (color, trend, icon)
  - `StockTable`: Paginated, clickable, inline quality badges
  - `StockDetailModal`: Deep-dive inspector with smooth animations
- **Styling**: Tailwind + custom config for soft palette
- **Type Safety**: Full TypeScript for reliability
- **SSR-ready**: Next.js App Router for SEO + performance

---

## Adding a New Page

Example: Create a "Backtesting Results" page

### Step 1: Create API endpoint
File: `services/ui-api/routers/backtest.py`
```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/results")
async def get_backtest_results():
    # Query DuckDB for backtest results
    return { "sharpe": 1.23, "returns": 15.5, ... }
```

### Step 2: Register in main.py
```python
from routers import backtest
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
```

### Step 3: Create React component
File: `ui/components/BacktestChart.tsx`
```typescript
export function BacktestChart() {
  const [results, setResults] = useState(null)
  
  useEffect(() => {
    client.get('/api/backtest/results')
      .then(res => setResults(res.data))
  }, [])
  
  return <div>Charting results...</div>
}
```

### Step 4: Add to page
File: `ui/app/page.tsx` — add `'backtest'` to nav tabs, render `<BacktestChart/>` when selected

---

## Deploy to Production

### Via Docker
```bash
# Build both services
docker compose -f infra/docker-compose.ui.yml build

# Run
docker compose -f infra/docker-compose.ui.yml up
```

### Via Manual (recommend for dev)
```bash
# Terminal 1
cd services/ui-api && python -m uvicorn main:app --port 8010

# Terminal 2
cd ui && npm run build && npm start
```

---

## Debugging

### API not responding?
```bash
curl http://localhost:8010/health
```
Should return `{"status": "ok", "service": "ui-api"}`

### Dashboard shows "Loading..." forever?
Check browser console (F12 > Network tab):
- Is the request to http://localhost:8010 succeeding?
- If CORS error: update `CORSMiddleware` in `services/ui-api/main.py`

### Stock detail modal won't open?
- Click on a stock row in the table
- Check console for network errors
- Verify `http://localhost:8010/api/stocks/{ticker}/detail` works

---

## Future Enhancements

- [ ] Real-time WebSocket updates for live quotes
- [ ] Advanced filtering (sector, price range, quality threshold)
- [ ] Export reports (CSV, PDF)
- [ ] Dark mode toggle
- [ ] Mobile-responsive refinement
- [ ] Performance charts (Recharts integration)
- [ ] User authentication (multi-user portfolios)

---

Enjoy the dashboard! 🚀
