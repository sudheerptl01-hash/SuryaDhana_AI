# W4 — MCXG: the MCX gold desk (build report, 15 Oct 2026 ~03:45 IST)

## Shipped (own files only; shared files untouched — patch blocks below)

| File | What |
|---|---|
| `shared/mcx_specs.py` (new) | MCX 2026 holiday calendar (3 closure kinds), session clock with the US-DST-linked 23:30/23:55 close, GOLD/GOLDM/GOLDPETAL/GOLDGUINEA specs (lot, tick value, delivery, purity), expiry computation (5th-of-cycle-month & month-end, business-day shifted), indicative round-trip cost model with cited rates. Pure stdlib. |
| `services/ui-api/routers/mcx.py` (new) | `/api/mcx/session` · `/specs` · `/quote` · `/overlay` · `POST /ticket`. Builds ON gold_preopen (imports `_load_mcx_master`, `_yahoo_bars`, `reference_price`, `fair_open`, `comex_symbol`, `mcx_close_time`, `previous_session` — zero duplication). errors.py contract (`fail`/`degraded`), TTLCache, sync-def/to_thread purity (scanner green). |
| `ui/components/McxGoldDesk.tsx` (new) | Standalone MCXG tab: session header with live countdown, holiday table, quote panel with source-labeled degrade, COMEX×INR overlay, specs table (click row → select contract), paper ticket with cost legs. Terminal kit only; native fetch (lib/api.ts untouched). |
| `services/ui-api/tests/test_mcx.py` (new) | 25 tests — session clock (full/morning/evening closures, 23:30↔23:55 DST edge, weekend, countdown math, agreement with `gold_preopen.mcx_close_time`), expiry cycle (reproduces the real master), tick/cost math hand-checked, master parse incl. ICICI's 6-char ShortNames, Breeze degrade/broken-memory/success/minute-bar paths, overlay premium, ticket validation. |

**Degrade-first design.** `/quote` always answers 200. Cascade: Breeze `get_quotes`
(stock_code = ICICI short name) → Breeze 1-min bars (`get_historical_data_v2`, the path that
worked on 12 Oct when get_quotes answered HTTP 500) → fallbacks always attached: ICICI
price-band settlement (public master, no session) + COMEX×USD/INR fair value (Yahoo). A broken
Breeze **shape** is remembered 10 min per contract (zero retry storms); a merely-invalid
session is NOT remembered (positions.`_get_breeze_client` already rate-limits, and the 08:00
login can arrive any minute). Whole payload cached 15 s → one broker call per poll window.

**Real-world catch:** ICICI's MCXScripMaster truncates ShortName to 6 chars — the minis are
`GOLDMI`/`GOLDPE`/`GOLDGU` (+`GOLDTE` = Gold Ten, not on this desk). Parser aliases both
spellings; Breeze stock_code uses the ICICI short name (GOLD verified; minis pending, below).

## Verification run (all live, 03:18–03:40 IST — session invalid by design at this hour)

- `pytest services/ui-api/tests` → **461 passed** (includes purity-scanner meta-test — tree stays clean); `tests/` 308 passed; `scripts/tests` 137 passed; `compileall` OK; `ui: npx tsc --noEmit` clean.
- Live curls (ephemeral uvicorn :8899 mounting only routers/mcx.py — running stack untouched, no .env → no login attempt):
  - `/session`: `is_open:false, opens_at 2026-10-15T09:00+05:30, closes_at …23:30 (DST), seconds_to_open 20512`; next holidays `20 Oct Dussehra (morning-closed, eve open) · 10 Nov · 24 Nov`.
  - `/quote?contract=GOLD`: `available:false`, reason "ICICI session invalid …", `expiry 2026-12-04 (observed)`, band settlement **₹149,543** (band 145,057–154,029, OI 17,548 lots), fair value **₹147,612** (COMEX GCZ26 **$4,127.3** × USDINR **95.14**, gap −1,931 vs settlement, landed ₹126,247, implied premium 16.9%), `best = fair value (COMEX × USD/INR model)`.
  - `/specs`: computed expiry == observed master expiry for ALL FOUR — GOLD 2026-12-04 (5th=Sat), GOLDM 2026-11-05, PETAL/GUINEA 2026-10-30 (31st=Sat); settlements 149,543 / 148,293 / 14,939 / 119,550; indicative margins ₹897k / ₹89k / ₹896 / ₹7.2k per lot.
  - `POST /ticket` GOLDM 1 lot @147,612 → notional ₹14,76,120 · margin ₹88,567 (6% ind.) · tick ₹10 · round trip **₹300.97 = 30.1 ticks breakeven** (`paper:true, recorded:false`).

## Patch blocks for the PM (shared files)

`services/ui-api/main.py` — with the other router imports (~line 70) and mounts (~line 138):
```python
from routers import mcx
app.include_router(mcx.router, prefix="/api/mcx", tags=["mcx-gold"])
```

`ui/app/page.tsx` — four spots:
```tsx
// 1. with the lazyTab imports (~line 46)
const McxGoldDesk = lazyTab(() => import('@/components/McxGoldDesk').then(m => m.McxGoldDesk))
// 2. Tab type union (~line 82): add
  | 'mcxgold'
// 3. TAB_IDS (~line 87), after 'commodity': add
  'mcxgold',
// 4. COMMAND_PAGES (~line 121), after the commodity row:
  { id: 'mcxgold', code: 'MCXG', label: 'MCX gold desk', hint: 'session, quotes, specs, paper ticket' },
// 5. render branches (~line 623), after the commodity branch:
            {view === 'mcxgold' && <McxGoldDesk />}
```

## LIVE-VERIFY-PENDING (PM, after the ~08:00 ICICI login; MCX opens 09:00)

```bash
# 1. GOLD quote — the known case: get_quotes 500'd on 12 Oct, 1-min bars worked. Expect either
#    available:true with quote.source "ICICI Breeze"/"ICICI Breeze (1-min bars)", or an honest reason.
curl -s "http://localhost:8010/api/mcx/quote?contract=GOLD" | python3 -m json.tool | head -30
# 2. The minis — stock_code guesses GOLDMI/GOLDPE/GOLDGU come from the master, never broker-verified:
curl -s "http://localhost:8010/api/mcx/quote?contract=GOLDM"     # expect LTP ≈ ₹148,300 ±band
curl -s "http://localhost:8010/api/mcx/quote?contract=GOLDPETAL" # expect LTP ≈ ₹14,940 ±band
# 3. Commodity segment: if every contract degrades with "Breeze gave no MCX … quote", the account's
#    commodity segment is the suspect — reason string says exactly that. Wrong stock_code for a mini →
#    fix BREEZE_CODE in routers/mcx.py (one dict).
```

## Citations

- **Holidays 2026**: ICICI Direct iLearn (icicidirect.com/ilearn/commodity/articles/mcx-holiday-list) · Kotak Neo (kotakneo.com/share-market-holidays/mcx-holidays) · 5paisa (5paisa.com/stock-market-holidays/mcx-holidays). mcxindia.com answers 403 to non-browser clients (curl w/ browser UA included). Conflict on 1 Jan 2026 (Kotak: full; ICICI+5paisa: morning open/evening closed) resolved toward ICICI, the desk's broker. Muhurat: Sun 8 Nov 2026, timings by circular.
- **Specs**: Rupeezy commodity lot/specs sheet (support.rupeezy.in article 21000005285) · OneTradeJournal MCX basics (expiry "5th of contract month, previous working day if holiday"; margins 5–12% typical) · Business Standard 22 Oct 2019 (Gold Petal: 1 g trading, delivery in multiples of 8 g, 999 purity) · Zerodha Market Intel + Fyers notice board expiry bulletins (petal/guinea/goldten expired 30 Jan / 27 Feb / 30 Mar / 30 Apr 2026 — pins the month-end + morning-holiday shift).
- **Costs**: Rupeezy "MCX transaction and other charges" (futures ₹2.10/lakh = 0.0021%; CTT 0.01% sell side non-agri; SEBI ₹10/crore; stamp 0.002% buy) · Bajaj Broking on MCX's post-SEBI true-to-label fee (Oct 2024). GST 18% on brokerage+txn+SEBI. All labeled **indicative** in API and UI.

## Cuts & risks (honest)

- **Holiday table covers 2026 only** — `session_state` emits `calendar_warning` outside 2026; weekends still honoured. Refresh needs a human (MCX blocks scripts).
- **Margins are a flat indicative 6%** (SPAN+exposure moves daily; bullion ran 6–12%). Clearly starred in UI; never for real orders.
- **Gold Ten (GOLDTE)** exists in the master but was cut from the desk (owner trades the four).
- **Delivery-period costs** (staggered delivery, delivery CTT/charges) out of scope — ticket prices squared-off trades and says so.
- **Expiry rule is computed + cross-checked**, not the circular itself; `/specs` labels observed vs computed, and on 15 Oct the two agree for all four contracts.
- **No MCX websocket ticks** — REST cascade with a 15 s cache instead (ICICI quota-safe); Breeze WS commodity subscription is a later, separate verification.
- Overlay premium is only computed against a LIVE broker price — never against the model's own fair value (no circularity).
