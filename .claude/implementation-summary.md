# Implementation Summary — Live Broker P&L + Backtest Lab T1/T2

## ✅ Part A — Add T1/T2 (150-day MA) to Backtest Lab

### Backend Changes
**File**: `services/ui-api/backtest_engine.py`

1. **Line 127** (in `compute_indicators()`): Added 150-day moving average computation
   ```python
   df["ma150"] = g["close"].transform(lambda x: x.rolling(150, min_periods=40).mean())
   ```
   - Positioned between `ma50` and `ma200` for logical grouping
   - Uses 40 minimum periods (approx 2 months of data) for warm-up window
   - Fully backward-looking, zero look-ahead bias

2. **Lines 87, 90** (in `BOOLEAN_FILTERS` dict): Added two new filter predicates
   ```python
   "price_gt_ma150": lambda d: d["close"] > d["ma150"],  # T1 component
   "ma150_gt_ma200": lambda d: d["ma150"] > d["ma200"],  # T2 complete
   ```
   - T1 (Price above 150-day AND 200-day MA) = toggle `price_gt_ma150` + `price_gt_ma200` together
   - T2 (150-day MA above 200-day MA) = toggle `ma150_gt_ma200` alone
   - Identical lambda pattern to existing MA50/MA200 filters → no changes to `apply_filters()` needed

### Frontend Changes
**File**: `ui/components/BacktestPanel.tsx`

Added to the **Trend** section of `FILTER_CATALOG` (lines 29, 32):
```typescript
{ id: 'price_gt_ma150', label: 'Price > 150-MA', toggle: true, op: 'gt', val: 0, desc: 'Above intermediate trend (Minervini T1 — combine with Price > 200-MA)' },
{ id: 'ma150_gt_ma200', label: '150-MA > 200-MA', toggle: true, op: 'gt', val: 0, desc: 'Stage-2 uptrend (Minervini T2)' },
```
- Both are toggle-style filters (`toggle: true`)
- Descriptions cross-reference Minervini naming for user clarity
- No changes needed to filter state, payload, or rendering logic — all generic

---

## ✅ Part B — Surface Real Breeze P&L in New "Broker Account" Tab

### Frontend Changes
**File**: `ui/app/page.tsx`

1. **Line 39**: Import the orphaned `PortfolioSummary` component
   ```typescript
   import { PortfolioSummary } from '@/components/PortfolioSummary'
   ```

2. **Line 41**: Extend the `Tab` union type
   ```typescript
   type Tab = '...' | 'broker' | '...'
   ```

3. **Line 265**: Add "Broker Account" tab descriptor
   ```typescript
   { id: 'broker',    label: 'Broker Account' },
   ```
   - Positioned right after "Portfolio" (which remains as the execution-engine view)
   - No badge needed (always shows live connection status)

4. **Line 514**: Render `PortfolioSummary` in view branch
   ```typescript
   {view === 'broker' && <PortfolioSummary />}
   ```

### What's Already Wired (No Changes Needed)
- **Backend**: `GET /api/positions/summary` (services/ui-api/routers/positions.py:87-152)
  - Calls `breeze.get_funds()` + `breeze.get_portfolio_holdings()`
  - Returns: `total_capital_inr`, `cash_available_inr`, `invested_value_inr`, `total_pnl_inr`, `total_pnl_pct`
  
- **API client**: `ui/lib/api.ts:112-128`
  - `getPositionSummary()`, `getOpenPositions()`, `getICICIConnectionStatus()`
  - `saveICICICredentials()`, `updateSessionToken()`, `getTradingConfig()`
  - All functions already exist and match the component's expectations

- **UI Component**: `ui/components/PortfolioSummary.tsx` (lines 14-24, 87-152)
  - Full ICICI Breeze connection UI (credentials, session token, live status)
  - KPI cards (Total Portfolio, Invested, Cash, P&L %)
  - Capital allocation bars
  - Open positions table with symbol/qty/entry/LTP/P&L
  - Auto-refresh every 15 seconds
  - All API calls match backend field names exactly

### Known Limitations (Out of Scope)
- `PortfolioSummary.tsx` uses fixed light-theme Tailwind classes (`bg-white`, `text-gray-900`) and does **not** accept the app's `isDark` prop → will render as a light card regardless of theme toggle (cosmetic only, not a functional issue)
- `max_drawdown_pct` in `/api/positions/summary` is hardcoded to `0` server-side (not computed from holdings) → this was pre-existing and is not part of this request

---

## Testing & Verification

### Part A — Backtest Lab T1/T2
1. Start the UI stack (or run `npm run dev` in the `ui/` directory)
2. Navigate to the **Backtest** tab
3. In the **Trend** filter section, you should now see:
   - "Price > 150-MA" (new)
   - "150-MA > 200-MA" (new)
   - Plus the existing "Price > 50-MA", "Price > 200-MA", "50-MA > 200-MA"
4. **Test T1**: Toggle "Price > 150-MA" + "Price > 200-MA" together, run a backtest
5. **Test T2**: Toggle only "150-MA > 200-MA", run a backtest
6. Confirm the candidate universe shrinks vs. no filter
7. Cross-check against the Stocks tab's T1/T2 screener (which uses the same definitions)

### Part B — Broker Account Tab
1. With `.env` Breeze credentials configured, start the UI
2. Navigate to the new **Broker Account** tab (located between "Portfolio" and "Pipeline")
3. **If not connected**:
   - Fill in ICICI API credentials or paste a session token
   - Click "Connect" and wait for authentication
4. **When connected**:
   - Verify KPI cards update (Total Portfolio, Invested, Cash, Total P&L)
   - Verify the open positions table populates (or shows "No active holdings" if empty)
   - Verify capital allocation bars render correctly
   - Check that data refreshes every 15s (look at "Last refresh" timestamp)
5. **Cross-check**:
   - Compare `total_capital_inr` = `invested_value_inr` + `cash_available_inr`
   - Compare `total_pnl_inr` and `total_pnl_pct` against your ICICI Breeze app/web account

### Type Checking & Linting
```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
/Users/sudheer/Desktop/jupyter_env/bin/python -m py_compile services/ui-api/backtest_engine.py
/Users/sudheer/Desktop/jupyter_env/bin/python -m mypy services/ui-api/backtest_engine.py --ignore-missing-imports
# TypeScript: run `npm run build` in the ui/ directory to catch any module resolution issues
```

---

## Commit Message

```
feat: add T1/T2 150-day MA filters to backtest lab + surface real breeze P&L in broker account tab

Backend:
- Add 150-day moving average (ma150) computation in backtest_engine.compute_indicators()
- Add two boolean filter predicates: price_gt_ma150, ma150_gt_ma200 (Minervini T1/T2)

Frontend:
- Add 'price_gt_ma150' and 'ma150_gt_ma200' toggles to BacktestPanel filter catalog
- Add 'broker' tab to main app, rendering PortfolioSummary (real ICICI Breeze P&L)
- Import PortfolioSummary component (was orphaned, now wired)
- Extend Tab union type to include 'broker'

P&L component shows:
- Live account balance (total capital, invested, cash available)
- Realized & unrealized P&L (₹ and %)
- Open positions table (qty, entry price, LTP, P&L per position)
- Auto-refreshing every 15 seconds from ICICI Breeze API

Closes: Live broker account balance tracking request
```
