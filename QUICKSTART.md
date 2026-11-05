# SuryaDhana AI — Quick Start Cheat Sheet

## 🚀 TL;DR

```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
./start.sh
```

Then open: **http://localhost:3000**

---

## Commands

| Command | What It Does |
|---------|--------------|
| `./start.sh` | Start all services via Docker |
| `./start-local.sh` | Start UI API + frontend (dev mode) |
| `./start.sh stop` | Stop all services |
| `./start.sh logs -f` | Follow logs in real-time |
| `./start.sh status` | Show container status |
| `./start.sh build` | Rebuild Docker images |
| `./start-local.sh stop` | Stop local services |

---

## Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| **Frontend** | http://localhost:3000 | React app (Stocks, Backtest, Portfolio, etc.) |
| **UI API** | http://localhost:8010 | Backtest engine, analytics, proxy to backends |
| **API Gateway** | http://localhost:8000 | Main backend entry point (Swagger docs: `/docs`) |
| **Redis** | localhost:6379 | Cache & pub/sub (CLI: `redis-cli`) |

---

## Tabs & What's New ⭐

| Tab | Purpose | **NEW** |
|-----|---------|--------|
| Overview | System health, data status | — |
| **Stocks** | Minervini T1–T8 screener | — |
| **Backtest** | Backtest builder & runner | **T1/T2 150-day MA filters** |
| **Portfolio** | Paper/live execution P&L | — |
| **Broker Account** | Real ICICI Breeze P&L | **NEW TAB (live account balance)** |
| ML Engine | Model training, SHAP | — |
| Glass-Box | Alpha signal discovery | — |
| System | Service health, logs | — |

---

## New Features

### 1️⃣ T1/T2 Filters in Backtest
**Location**: Backtest tab → Trend section
- **Price > 150-MA** (T1 component)
- **150-MA > 200-MA** (T2)

Combine them:
- T1 = toggle `Price > 150-MA` + `Price > 200-MA` together
- T2 = toggle `150-MA > 200-MA` alone

### 2️⃣ Live Broker Account P&L
**Location**: New "Broker Account" tab
- Real ICICI Breeze balance & P&L
- Total portfolio, invested, cash available
- Open positions from your demat account
- Refreshes every 15 seconds
- First time: paste ICICI session token

---

## Configuration

### `.env` File
```bash
# Copy template
cp .env.example .env

# Edit with your ICICI credentials
BREEZE_API_KEY=your_key
BREEZE_API_SECRET=your_secret
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Docker won't start | Open Docker Desktop app |
| Services won't start | `./start.sh logs -f` to see errors |
| Port in use | `lsof -i :3000` and kill the process |
| DuckDB locked | `./start.sh stop` then `./start.sh` |
| ICICI not connecting | Verify `.env` has credentials, check Broker Account tab |

---

## Architecture (Quick View)

```
DuckDB (NSE data)
  ↓
Data/Feature Services
  ↓
UI API (backtest engine) ← Backtest Panel
  ↓
Next.js Frontend (React) ← http://localhost:3000
```

---

## Useful Shortcuts

### View Logs
```bash
./start.sh logs -f  # Real-time
./start.sh logs     # Last 50 lines
```

### Enter a Container (Docker)
```bash
docker exec -it suryadhana_ai-ui-1 /bin/bash
```

### Check Redis
```bash
redis-cli
> PING
> KEYS *
```

### Stop Everything
```bash
./start.sh stop
```

---

## Next Steps

1. ✅ Run `./start.sh`
2. ✅ Open http://localhost:3000
3. ✅ Go to **Broker Account** tab, add ICICI credentials (if trading)
4. ✅ Go to **Backtest** tab, toggle **T1** or **T2** filters, run backtest
5. ✅ Watch **Portfolio** tab for live P&L (paper trading)
6. ✅ Watch **Broker Account** tab for real account P&L (live, once connected)

---

**Happy trading!** 🚀
