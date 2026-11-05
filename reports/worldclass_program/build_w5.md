# Build W5 — RSK · portfolio risk dashboard (15 Oct 2026)

**Shipped** (own files only; shared files untouched — patch blocks below):

- `services/ui-api/risk_math.py` — pure, tested math. Hist-sim VaR/ES (k-th-worst order
  statistic, k = ceil((1−a)·n), float-eps guarded), √h horizon scaling (labeled
  approximation), beta (cov/var on common sessions), Euler risk contributions (sum = σ_p
  exactly), stress window compounding with honest coverage exclusion, sector concentration
  vs the 40 % cap (positions share — the Desk rule as written), drawdown ladder vs the
  −20 % HARD stop and −2 % daily halt, severity thresholds (documented in `THRESHOLDS_DOC`).
- `services/ui-api/routers/riskdash.py` — `GET /api/risk/dashboard`. Sync `def` handler
  (FastAPI threadpool); the N-ticker history fan-out runs on a bounded
  `ThreadPoolExecutor(8)` — purity scanner green. Payload cached 120 s (`cache.TTLCache`,
  telemetry-registered). Error contract: `errors.fail/degraded` only.
- `ui/components/RiskDashboard.tsx` — kit-conventions page: severity chips
  (VAR/BETA/SECTOR/DD with threshold tooltips), 6-stat summary strip, hand-rolled SVG
  return histogram with VaR95/99 markers (no new libs), holdings-risk table (β, risk
  share, VaR-exclusion notes), sector cap meters, stress-replay table, drawdown-ladder
  visual + KV, what-if basket input (+ one-click "Desk watchlist").
- `services/ui-api/tests/test_risk_math.py` — 17 tests, every number hand-computed first.

**Book & data (verified shapes):** Desk paper book via `routers.desk.get_desk().status()`
(the DESK tab's status endpoint code path — ledger only, no market load); broker last-known
holdings from `data/last_holdings.json` (as-of surfaced + stale-hours; **never calls
Breeze** — zero quota). History over data-service HTTP only: `GET :8001/ohlcv/{t}?start=…`
(adjusted closes → 750-session VaR panel + 250-session betas; **this table starts
2020-09-16**, so) stress windows use `GET :8001/db/security/{t}/history?days≈2500`
(bhavcopy, split-adjusted change_pct — reaches COVID); NIFTY via
`GET :8001/db/index-daily?symbol=NIFTY50`. A symbol missing a leg is excluded from that
block with the reason, never guessed; ohlcv-missing names fall back to the bhavcopy series
(provenance noted).

**Honest-degradation reality check:** both books are EMPTY tonight (Desk all-cash since
the 2026-10 cycle, broker file `[]` as of 2026-10-14 15:13). Live book call → 200
`degraded(…, "state", "The book is all cash — nothing at market risk today")` with the
ladder still live from the 13 EOD NAV marks. The page says so and offers the what-if path.

## Patch blocks (PM applies; shared files untouched by me)

`ui/app/page.tsx` — ① registry (COMMAND_PAGES array, after the 'research' row):
```ts
  { id: 'risk',      code: 'RSK',   label: 'Risk dashboard',        hint: 'VaR, beta, stress, drawdown ladder' },
```
② `type Tab` union + `TAB_IDS`: add `'risk'` (I suggest after `'research'` in both).
③ dynamic import (with the other lazyTab consts):
```ts
const RiskDashboard = lazyTab(() => import('@/components/RiskDashboard').then(m => m.RiskDashboard))
```
④ render branch (next to the DecisionDesk branch):
```tsx
            {view === 'risk' && <RiskDashboard isDark={isDark} />}
```
(Optional: `{ id: 'risk', label: 'Risk' },` in `tabList` for the visible strip — otherwise
RSK is reachable via the GO bar and the header's `more` overflow, which filters on the registry.)

`services/ui-api/main.py`:
```py
from routers import riskdash
app.include_router(riskdash.router, prefix="/api/risk", tags=["risk"])
```

`ui/lib/api.ts` (optional — the component uses the default `client` export, so it compiles
and runs without this):
```ts
export const getRiskDashboard = (symbols?: string) =>
  client.get('/api/risk/dashboard', { params: symbols ? { symbols } : {}, timeout: 120000 })
```

## Tests & checks (all run tonight)

- `pytest services/ui-api/tests/test_risk_math.py -q` → **17 passed** (VaR95=4 %/ES95=6.6 %
  on the hand-built 100-point series; β(y=2x)=2.0 exact; Σ contributions = σ_p;
  COVID-window compounding −31.6 % = 0.95·0.90·0.80−1; ladder 100→110→99 distances).
- Full `pytest services/ui-api/tests -q` → **461 passed** (no regressions).
- `scripts/check_event_loop.py` → 0 findings. `compileall` routers + tests → clean.
- `npx tsc --noEmit` → **0 errors in my files** (pre-existing errors only in
  `McxGoldDesk.tsx` — W4's file, mid-build tonight).

## Live numbers (scratch uvicorn :8111 mounting only this router → real :8001 + real ledger; killed after)

Live book (empty): 200, `ok:false`, ladder nav ₹5,01,389 · peak ₹5,01,389 · DD 0.00 % ·
stop-NAV ₹4,01,111 (a further −20.0 %) · today +0.02 % → room before −2 % halt 2.02 % ·
severity DD ok, rest `na`. Broker as-of shown (12.0 h stale).

What-if = the Desk's October watchlist (20 names, equal weight on ₹5,01,389), 1.2 s cold / 1 ms cached:
- **VaR95 1d ₹11,433 (2.28 %)** < **VaR99 1d ₹20,859 (4.16 %)** ✓ ordering; ES95 3.33 % ≤ ES99 4.69 %;
  VaR95 5d 5.10 % = 2.28·√5 ✓ (labeled approximation). 750 sessions 2023-09-27→2026-10-14, 100 % value covered.
- **Portfolio β 1.14** (plausible 0.5–1.5 ✓; small-cap momentum book); worst single β MOREPENLAB 1.51; risk shares sum 100.1 % (rounding).
- Sectors: Capital Goods 7/20 = 35 % → **warn** (≥ 80 % of the 40 % cap), no breach.
- Stress: **COVID −42.5 % on covered (NIFTY −37.0 %)**, worst WELCORP −66.5 %, covered 50 %
  (10 of 20 not listed pre-COVID — excluded, named); **election day −6.6 % (NIFTY −5.9 %)**,
  covered 90 %; **2022 H1 −7.8 % (NIFTY −9.1 %)**, covered 60 %.
- Severity: VAR **crit** (2.28 % ≥ 2 % of book — a 1-in-20 day on a fully-deployed basket
  would statistically trip the −2 % daily halt; the Desk itself deploys 66 %), BETA ok, SECTOR warn, DD ok.
- Sanity vs large caps: RELIANCE+TCS basket → β 0.88, VaR95 2.01 %, COVID −31.5 % with
  worst RELIANCE −40.5 % (matches history). Unknown symbol → excluded with `ohlcv 404` /
  `bhavcopy history 404`, never silently dropped.

## Cuts & risks

- **Cut:** intraday halt distance — the ladder's "today" leg uses the ledger's EOD marks
  (stated on the page); wiring live ticks into the halt line is a later, small job.
- **Cut:** Desk-vs-broker ladders are not separate; the −20 % ladder is the Desk ledger's
  (sole NAV history). Entry-value fallback exists and states itself.
- **Risk:** stress replays price broker lines at bhavcopy last close and compound
  split-adjusted `change_pct`; a symbol with a corrupt adjustment upstream would carry it —
  same exposure as the Profile page's HP (shared code path).
- **Risk:** what-if deploys 100 % of NAV (pre-trade worst case) — the Desk's real
  deployment is 66 % equity share; noted on the page notice.
- Payload ~35 KB (histogram 31 bins, ≤ 40 holdings) — inside W7's 150 KB bar; 120 s TTL
  cache keeps the 2-leg×N fan-out off data-service on UI polls.
