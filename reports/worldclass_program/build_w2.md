# Build W2 — DERV, the NSE F&O analytics desk (15 Oct 2026, ~03:30 IST)

## Shipped (owned files, all new)
| File | What |
|---|---|
| `services/data-service/fo_analytics.py` | GET-only router `/db/fo/*`: term-structure, basis-history, rollover, pcr-history, vix, symbols. Pure math + SQL helpers are standalone-testable; `main` is imported lazily inside handlers (no circular import). Sync `def` handlers → threadpool. |
| `services/ui-api/routers/derivatives.py` | `/api/derivatives/*`: pure async httpx proxies (event-loop clean), errors per `errors.fail` contract. Also proxies the EXISTING `/db/option-history/{sym}` (near-expiry IV/PCR/max-pain archive, NIFTY+BANKNIFTY) and trims `/db/option-chain/{sym}` to scalars (`/max-pain/{sym}`, ~300 B — no 50-strike rows; W7 payload rule). markets.py untouched. |
| `ui/components/DerivativesDesk.tsx` | DERV tab: summary strip (spot, near basis ann, DTE, PCR+max pain, rollover-so-far, VIX pctile), term-structure table + 5y basis chart, rollover tracker (curve vs prior-cycle average by DTE, per-expiry finals, cost of carry), PCR & max-pain section, INDIA VIX vs realized panel. Inline-SVG charts in the MarketMonitor pattern — no new chart lib (W1 owns that decision). |
| `services/ui-api/tests/test_derivatives.py` | 15 tests (below). |
| `data/nse_archive/derived/fo_futures_panel.csv.gz` | Pre-seeded derived futures panel (356,072 rows, 2024-07-08→2026-10-14, 4.5 MB gz, 19.7 s full build) so integration starts warm; data-service extends it incrementally (1 file/day) in a background thread, option_history.json pattern. |

## Data-grain honesty (baked into payload `note`s and the tab footer)
- `nse_fo_daily` = 1 row/underlying/day (near fut close, ALL-expiry OI sums) → **basis history is near-month**, **PCR history is all-expiry aggregate OI** (OMON's near-expiry chain PCR is a different number; both labeled).
- Per-contract rows exist only in cached UDiFF bhavcopies (**Jul-2024 →**) → term structure + rollover come from the derived panel; rollover history starts Jul-2024.
- **Max-pain history: NIFTY + BANKNIFTY only** (existing `option_history.json` archive). Stocks get the current session's chain max pain only — **no fabricated series** (stated in the UI).
- **BANKNIFTY basis history**: `market_index_daily` stores NIFTY50 + INDIAVIX only → endpoint 404s with that exact reason; the UI shows it as a note. BANKNIFTY term structure, rollover, PCR, option-history all work (spot comes from the file).
- Participant OI is already the MKT tab's ParticipantPositioning panel (GAPS: HAVE) — not duplicated.

## Patch blocks (PM applies — shared files untouched by me)

**`services/data-service/main.py`** — after the other `@app` routes (anywhere post-`app = FastAPI(...)`; `fo_analytics` does not import `main` at module level, so top placement of the import is also safe):
```python
import fo_analytics                           # W2 (DERV): F&O analytics
app.include_router(fo_analytics.router)       # /db/fo/*
```

**`services/ui-api/main.py`** — with the sibling imports (line ~70) and mounts (line ~138):
```python
from routers import derivatives
app.include_router(derivatives.router, prefix="/api/derivatives", tags=["derivatives"])
```

**`ui/app/page.tsx`** — five one-liners:
```tsx
// 1) with the lazyTab imports (~line 58, near OptionChain):
const DerivativesDesk = lazyTab(() => import('@/components/DerivativesDesk').then(m => m.DerivativesDesk))
// 2) Tab union (~line 82): add  | 'derivatives'   (suggest after 'options')
// 3) TAB_IDS (~line 86): add  'derivatives',      (same spot)
// 4) COMMAND_PAGES (~line 100, after the OMON row):
  { id: 'derivatives', code: 'DERV', label: 'Derivatives desk', hint: 'basis, rollover, PCR, VIX' },
// 5) nav TABS list (~line 407, after { id: 'markets', label: 'Markets' }):
    { id: 'derivatives', label: 'Deriv' },
// 6) render branches (~line 619, after the markets line):
            {view === 'derivatives' && <DerivativesDesk onSelectTicker={setSelectedTicker} />}
```

## Tests + verification (all run tonight)
- `tests/test_derivatives.py` — **15 passed**: basis annualization vs hand-computed + real NIFTY row; dte/zero/None guards; term legs (ordering, labels, contango sign, real-leg values); rollover % + two-cycle `rollover_view` (final 75 %, carry 6.52 % ann, per-DTE prior-average curve, avg3); PCR zero-call guard; VIX percentile + flat-price rv=0; **the real SQL on an in-memory DuckDB with the production schemas** (NIFTY spot source vs EQ-bhavcopy source vs missing-spot 404 path, series-EQ pick over BE, PCR 0.86, percentile 100 on a rising series); ui-api symbol-guard 422/`invalid` (`m&m`→`M&M` passes) and the max-pain payload trim.
- Full ui-api suite: **461 passed** (446 baseline + 15), 3 consecutive runs. One mid-run flake of `test_bulk_cache.py` (W7's new file, being edited concurrently) — passes alone and in all 3 reruns; not a W2 interaction.
- `cd ui && npx tsc --noEmit` — clean. `compileall` — clean. `mypy` on both new modules — **0 errors** (the 52 errors mypy prints are pre-existing in data-service main.py et al. when following imports).

## Live evidence (real archive + :8001, 14 Oct 2026 EOD)
- **NIFTY** spot 22,622.70 (= market_index_daily close exactly): near 27-Oct 22,648.5 → **+3.20 % ann**, next 23-Nov 22,756.0 → +5.38 %, far 29-Dec 22,903.1 → +5.95 % — contango, upward carry curve ✓.
- **RELIANCE** spot 1,174.61 (= EQ bhavcopy): +18.14 / +10.71 / +8.50 % ann. Panel OI sum near+next+far = **173,944,000 shares = the stored `nse_fo_daily.fut_oi` to the share** (cross-checked vs `/db/security/RELIANCE`, independent code). Basis 0.646 % vs security.py's 0.65 ✓.
- **BANKNIFTY** spot 55,316.0 (file): +8.36 / +7.91 / +7.22 % ann ✓.
- **Rollover NIFTY**: now **14.2 % at T−13 vs 14.8 % prior-cycle average at the same DTE** (on pace); finals Jun 80.3 / Jul 71.8 / Aug 77.4 / Sep 74.3 % (avg3 74.5); carry into next 5.38 % ann. RELIANCE: 15.8 % at T−13 vs 16.0 % avg; finals ~94 % (single-stock futures roll higher — physical delivery) ✓.
- **VIX**: 14.60 (+0.48 vs 14.12 on 13 Oct), **71st pctile 1y, 55th 5y**; NIFTY 20d realized 14.75 → spread **−0.15** (options ≈ realized). INDIAVIX history 4,187 sessions from 2009-09-22.
- **Option-history NIFTY** (existing archive, served through my proxy): 14 Oct → PCR 0.86, max pain 22,600 vs spot 22,622.7, ATM IV 12.5, expiry 2026-10-19.
- New endpoints can't be curled until the PM mounts + restarts (restart ban) — the SQL ran against the production schemas in pytest and every formula ran against the real cached files above; post-integration spot-check: `curl :8010/api/derivatives/term-structure?symbol=NIFTY` and `…/rollover?symbol=RELIANCE`.

## Cuts (deliberate)
- Rollover history before Jul-2024 (old-format fo…bhav.csv.zip files are cached and parseable — a later `build_panel` extension).
- Stock max-pain history (needs per-strike archive discipline for stocks first — GAPS already lists IV-surface/chain archive as "later").
- No intraday F&O, no Breeze calls, no option-Greeks (W3 owns OSTR).
- `ui/lib/api.ts` untouched (shared): the component carries its own typed fetch helper.

## Risks / notes for PM
- Panel build thread is single-flight with atomic writes and corrupt-file skip; while building, `/rollover` returns `updating: true` and the UI self-polls (8 s × 12). Pre-seeded cache makes this instant in practice.
- `fo_analytics` handlers hold `store._lock` only around `_conn.execute` (same convention as main.py's own endpoints).
- If the PM prefers the import grouped: `import fo_analytics` must stay AFTER `sys.path` setup in main.py (it imports `option_chain`/`shared.*` like the other data-service modules).
