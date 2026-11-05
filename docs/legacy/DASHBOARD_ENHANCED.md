# SuryaDhana Enhanced Dashboard — Complete Guide

## 🎨 Visual Features & Styling

### Color Palette (Now Vibrant & Live)
- **Mint (Fresh/Positive)**: `#14b8a6` → Used for healthy metrics, growth, buy signals
- **Coral (Warning/Caution)**: `#ff7a4a` → Used for stale data, bearish signals, risk
- **Lavender (Info/Future)**: `#a855f7` → Used for upcoming events, analytics, advanced features
- **Slate (Neutral)**: `#64748b` → Used for text, backgrounds, secondary UI

### Responsive Design
✅ **Mobile-first**: All components scale from 320px → 7680px displays
✅ **Adaptive layouts**: Grid columns adjust (1col mobile → 4col desktop)
✅ **Touch-friendly**: Button sizes, tap targets optimized for mobile
✅ **Fast on slow networks**: Images lazy-loaded, CSS minified

---

## 📊 Dashboard Tabs (5 Total)

### 1. **Overview Tab** 📊
System health & portfolio snapshot.

**KPI Cards:**
- Total Stocks (501)
- Data Freshness (%)
- Latest Trading Date
- Days Stale (Max staleness)

**Health Status Card:**
- System Status (🟢 LIVE)
- Stocks updated today
- Data range (2021-04-26 → 2026-05-22)

---

### 2. **Stocks Tab** 📈
Stock filtering, analysis, and drill-down.

**Technical Filters (T1-T8 IBD-Style):**
```
T1: Price > 150-day & 200-day moving averages
T2: 150-day MA > 200-day MA
T3: 200-day MA trending upward ≥1 month
T4: 50-day MA > both 150/200 MAs
T5: Price > 50-day MA
T6: Price ≥30% above 52-week low
T7: Price within 25% of 52-week high
T8: Relative Strength (RS) ≥70
```

**Stock Table Columns:**
- Ticker (clickable → detail modal)
- Latest Price (₹)
- Coverage (years & row count)
- **Data Density Bar** (visual % completeness, color-coded)
- Freshness Badge (mint=fresh, coral=stale)
- Quality Badge (Excellent/Good/Fair/Poor)

**Stock Detail Modal** (on row click):
- OHLCV completeness (total rows, density %, missing days)
- Fundamentals grid (P/E, Market Cap, ROE, Sector, etc.)
- Upcoming events (earnings, dividends)
- Data quality assessment
- Dividend & split history counts

---

### 3. **Analysis Tab** 🔬
Advanced ML/trading analytics (coming soon).

**Placeholder Cards:**
- Signal Quality: XGBoost model performance
- Feature Coverage: 40+ technical indicators
- Label Distribution: 5-day return predictions

---

### 4. **Portfolio Tab** 💰
**Live P&L & Position Management**

**Summary Cards:**
- Total Balance (₹)
- Amount Invested (with % allocation)
- Cash Available (ready to deploy)
- Total P&L (₹ + %)

**Portfolio Composition:**
- Invested vs. Cash allocation bars
- Risk metrics (Max Drawdown, Win Rate, Trades today)

**Open Positions Table:**
| Symbol | Qty | Buy Price | Current | P&L (₹) | Return (%) |
|--------|-----|-----------|---------|---------|-----------|
| AXISBANK | 50 | ₹1200 | ₹1245 | ₹+2250 | +3.75% |
| INFY | 20 | ₹1800 | ₹1890 | ₹+1800 | +5.0% |

**Upcoming Events:**
- Earnings announcements (dated)
- Dividend ex-dates (dated)
- Stock split notices

---

### 5. **Pipeline Tab** ⚙️
**Data Flow Architecture Visualization**

Shows 4 stages:

#### Stage 1: Data Ingestion 📡
- **yfinance**: 5-year historical OHLCV (batch daily)
- **ICICI Breeze API**: Live quotes (9:15-15:30 IST)
- **NSE CSV**: 504 Nifty 500 tickers
- **Smart Sync**: Only fetch missing days (incremental)

#### Stage 2: DuckDB Storage 💾
- **OHLCV Table**: 547K+ rows, 501 tickers, 5-year span
- **Fundamentals**: P/E, Market Cap, ROE, Sector, Analyst ratings
- **Events**: Earnings dates, dividends, splits
- **Read-only** optimized for analytics

#### Stage 3: FastAPI REST Layer ⚡
- `/api/dashboard/summary` → KPIs & health
- `/api/stocks/list` → Paginated stock list
- `/api/stocks/{ticker}/detail` → Deep inspection
- `/api/analytics/*` → Signal quality, features
- `/api/positions/*` → Live portfolio (from Breeze)

#### Stage 4: Next.js Dashboard 🌐
- Responsive UI with real-time data
- Modular components (KPICard, StockTable, Modal)
- Soft color palette, smooth animations

**Data Flow Metrics Card:**
- 547K+ data points indexed
- 501 Nifty 500 tickers tracked
- Daily sync + live quotes
- <100ms P99 API latency

---

## 🔌 API Endpoints (FastAPI /docs)

### Dashboard
```
GET /api/dashboard/summary
  → {total_stocks, latest_date, data_freshness, health}

GET /api/dashboard/enrichment-status
  → {coverage %} for fundamentals, dividends, events
```

### Stocks
```
GET /api/stocks/list?skip=0&limit=50
  → Paginated: {total, skip, limit, stocks[]}
  
GET /api/stocks/{ticker}/detail
  → {ohlcv_stats, fundamentals, dividends, splits, events, quality}
```

### Analytics (Future)
```
GET /api/analytics/signal-coverage
GET /api/analytics/feature-quality
GET /api/analytics/label-distribution
```

### Portfolio (Breeze Integration)
```
GET /api/positions/summary
  → {balance, invested, cash, total_pnl, positions[]}

GET /api/positions/open-positions
GET /api/positions/trade-history
GET /api/positions/sector-exposure
```

---

## 🚀 Running the Dashboard

### Via Docker (Recommended)
```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI

docker compose -f infra/docker-compose.ui.yml up -d
```

Visit:
- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8010/docs

### Via Local Development
```bash
# Terminal 1: FastAPI backend
cd services/ui-api
/Users/sudheer/Desktop/jupyter_env/bin/python -m uvicorn main:app --reload --port 8010

# Terminal 2: Next.js frontend
cd ui
npm run dev
```

---

## 📊 Data Quality Classification

Based on `days_since_update` and `data_density_pct`:

| Quality | Days Stale | Density | Color |
|---------|-----------|---------|-------|
| **Excellent** | 0-1 | ≥95% | 🟢 Mint |
| **Good** | 1-3 | ≥90% | 🟢 Mint |
| **Fair** | 3-7 | ≥80% | 🟡 Slate |
| **Poor** | >7 | <80% | 🔴 Coral |

---

## 💾 Database Schema (DuckDB)

### OHLCV Table
```sql
CREATE TABLE ohlcv (
  ticker VARCHAR,
  date DATE,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  volume BIGINT,
  PRIMARY KEY (ticker, date)
)
```

### Fundamentals Table
```sql
CREATE TABLE fundamentals (
  ticker VARCHAR,
  market_cap BIGINT,
  pe_ratio DOUBLE,
  roe DOUBLE,
  debt_to_equity DOUBLE,
  dividend_yield DOUBLE,
  sector VARCHAR,
  analyst_recommendation VARCHAR,
  analyst_target DOUBLE
)
```

### Events Table (Earnings, Dividends, Splits)
```sql
CREATE TABLE corporate_events (
  ticker VARCHAR,
  event_type VARCHAR,
  event_date DATE,
  details JSON
)
```

---

## 🔄 Data Pipeline Resume Support

Pipeline maintains `.pipeline_state.json`:
```json
{
  "AXISBANK": {
    "status": "completed",
    "updated": "2026-05-22",
    "rows": 1255,
    "error": null
  },
  "INFY": {
    "status": "in_progress",
    "updated": "2026-05-22T14:30:00Z",
    "rows": 1250,
    "error": null
  }
}
```

**If interrupted**, next run resumes from last checkpoint without re-downloading completed tickers.

---

## ⚙️ Pipeline Modes

```bash
cd scripts/

# Initial load (full 5yr for new, delta for stale)
python nifty500_pipeline.py --mode initial

# Daily refresh (incremental sync)
python nifty500_pipeline.py --mode daily

# Enrich with fundamentals, dividends, splits
python nifty500_pipeline.py --mode enrich

# Apply filters (remove delisted, etc.)
python nifty500_pipeline.py --mode filter

# View database statistics
python nifty500_pipeline.py --mode status

# Reset and retry failed tickers
python nifty500_pipeline.py --mode reset
```

---

## 🛠️ Tech Stack Summary

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Data Sources** | yfinance, ICICI Breeze API v2, NSE CSV | OHLCV + live quotes |
| **Database** | DuckDB | Time-series, analytical queries |
| **Backend** | FastAPI + Python 3.13 | REST API, data aggregation |
| **Frontend** | Next.js 15 + React 19 + TypeScript | Dashboard UI |
| **Styling** | Tailwind CSS + custom utilities | Soft colors, responsive |
| **Container** | Docker + Docker Compose | Deployment |
| **CI/CD** | GitHub Actions (pending) | Automated testing |

---

## 📈 Future Enhancements

- [ ] Real-time WebSocket updates (live quotes)
- [ ] Advanced technical analysis (Ichimoku, VWAP)
- [ ] ML-based signal generation (XGBoost)
- [ ] Backtesting engine (walk-forward)
- [ ] Dark mode toggle
- [ ] Export reports (CSV, PDF)
- [ ] User authentication (multi-user)
- [ ] Custom watchlists
- [ ] Mobile app (React Native)
- [ ] Email alerts (earnings, dividend ex-dates)

---

## 🐛 Troubleshooting

### Dashboard shows "Loading..." forever
1. Check API health: `curl http://localhost:8010/health`
2. Check browser console (F12 > Network tab)
3. Verify DuckDB connection: `docker logs infra-ui-api-1`

### Stock detail modal won't open
1. Click on a stock row in the table
2. Check if `/api/stocks/{ticker}/detail` endpoint works
3. Verify DuckDB has fundamentals data

### Colors appear pale/not vibrant
1. Hard-refresh browser (Cmd+Shift+R / Ctrl+Shift+R)
2. Clear browser cache
3. Check Tailwind CSS is building: `npm run build`

---

**Made with ☀️ by SuryaDhana AI Trading System**

Last updated: 2026-05-23
