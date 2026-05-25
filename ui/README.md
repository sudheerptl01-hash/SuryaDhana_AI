# SuryaDhana Dashboard

Enterprise-grade UI for the quantitative trading system. Built with Next.js 15 + TypeScript + Tailwind + shadcn/ui.

## Features

- **Overview Dashboard**: System health, data freshness, enrichment coverage
- **Stock Explorer**: Paginated table with data quality metrics, density indicators
- **Stock Details**: Click any stock to see OHLCV stats, fundamentals, dividends, splits, upcoming events
- **Soft Color Palette**: Mint, coral, lavender — designed for long viewing sessions
- **Modular Architecture**: Components (KPICard, StockTable, StockDetailModal) are reusable and testable
- **Real-time API Integration**: Fetches from FastAPI ui-api service

## Setup

```bash
cd ui
npm install
npm run dev
```

Open http://localhost:3000

## Architecture

```
app/
├── layout.tsx          # Root layout with tailwind setup
├── page.tsx            # Main dashboard component
└── globals.css         # Global styles

components/
├── KPICard.tsx         # Reusable KPI metric card
├── StockTable.tsx      # Paginated stock list with inline quality badges
└── StockDetailModal.tsx # Deep-dive stock inspector

lib/
└── api.ts             # API client (axios) + typed endpoints

tailwind.config.ts     # Soft color palette config
```

## Design System

**Colors:**
- Mint (primary): positive, healthy data
- Coral (warning): stale or poor quality
- Lavender (info): future insights
- Slate (neutral): base text, borders

**Components:**
- KPICards: 4-column dashboard grid
- StockTable: sortable, hoverable, clickable
- Modal: smooth backdrop blur, keyboard-closeable

## API Endpoints (consumed from ui-api)

- `GET /api/dashboard/summary` — KPI data
- `GET /api/dashboard/enrichment-status` — Fundamentals coverage
- `GET /api/stocks/list` — Paginated stock list with metrics
- `GET /api/stocks/{ticker}/detail` — Deep stock inspection
- `GET /api/analytics/*` — Future: signals, features, labels
- `GET /api/performance/*` — Future: backtest, model, strategy
- `GET /api/positions/*` — Future: portfolio, trades

## Future Enhancements

- Real-time WebSocket updates
- Advanced filtering (sector, price range, quality)
- Export CSV/PDF reports
- Dark mode toggle
- Mobile responsive refinement
