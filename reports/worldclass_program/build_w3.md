# W3 — OSTR options strategy builder (build report, 15 Oct 2026)

## Shipped (own files only)

| File | What |
|---|---|
| `services/ui-api/options_math.py` | Pure math, no I/O: Black-76 on the forward (r 6.5%, same model/conventions as `ui/lib/black76.ts` behind OMON) — price, N(d1) futures-equivalent delta, gamma, theta ₹/day, vega ₹/vol-pt, rho (−T·V per +1%), prob-ITM. `Leg` (buy/sell · CE/PE/FUT · strike · premium · lots · lot_size · iv · days). **Exact breakevens**: roots solved on each linear segment of the piecewise-linear expiry payoff (never sampled); calendar books fall back to bisection (1e-7) on the smooth nearest-expiry curve. Max profit/loss with honest bounded/unbounded flags over S∈[0,∞) (downside always bounded at S=0 — a short put's worst case is K−premium; only the S→∞ tail can be unbounded, from the net slope above the top strike). Payoff grid ±max(2.5σ, 12%) that **includes every kink and breakeven as a grid point** (chart corners/zero-crossings exact). Margin ESTIMATE (long = premium; short ≈ fut-margin% × notional + premium; defined-risk floor = \|max loss\| shown). NSE F&O cost ESTIMATE, itemised round trip. |
| `services/ui-api/routers/options_strategy.py` | `POST /api/options/strategy/analyze` — Pydantic contract (≤ 4 legs enforced), sync `def` (threadpool → event-loop purity; work is µs), errors via `errors.fail` (400 `invalid` + 422 envelope). Returns entry cashflow (credit/debit), breakevens, max P&L, per-leg + net Greeks, to-scale payoff grid (expiry + today), margin + costs (both `estimate: true`), `paper_only: true`. |
| `ui/components/StrategyBuilder.tsx` | OSTR page, terminal kit (`T.*`, PageHeader/Panel/Chip/Stat/Select/Input). Left: leg table (≤4; BUY/SELL + CE/PE/FUT toggles, strike select from the chain, premium/IV/lots editable; per-leg Δ/θ/ν + model price) + 8 templates (long call/put, bull call spread, bear put spread, straddle, strangle, iron condor, covered call fut+CE) seeded from real chain strikes (ATM ± index steps) with chain premiums and parity-fallback IVs (leg IV → other side → ATM, same as OptionPricer). Right: to-scale SVG payoff (repo pattern, no chart lib) — expiry curve green/red split exactly at breakevens, today curve (B-76) cyan, labelled BE/forward lines, ₹ + strike axes — Greeks strip (net Δ with ₹ exposure, Γ, θ ₹/day, ν, ρ), NET DEBIT/CREDIT + BE + max-P&L chips, margin/costs panel labelled **ESTIMATE**. Header chip: `PRICES ONLY · NO ORDERS` (no order buttons anywhere). Chain from the cached EOD endpoint `GET /api/market/option-chain/{symbol}` (markets.py untouched) — works with the ICICI session invalid. Debounced (350 ms) analyze; lot size **always from the chain payload** (NIFTY is 65 in the current chain — never hardcoded). |
| `services/ui-api/tests/test_options_math.py` | 18 tests, all green (below). |

## Patch blocks for the PM (shared files — NOT edited by me)

### 1. `ui/app/page.tsx`
a) dynamic import (with the other `lazyTab` lines, ~line 56):
```tsx
const StrategyBuilder = lazyTab(() => import('@/components/StrategyBuilder').then(m => m.StrategyBuilder))
```
b) `Tab` type union + `TAB_IDS` array: add `'ostrategy'` (suggest right after `'options'` in both).
c) `COMMAND_PAGES` (after the OMON row, line ~100):
```tsx
  { id: 'ostrategy', code: 'OSTR',  label: 'Options strategies',    hint: 'payoffs, Greeks, breakevens' },
```
d) render branch (next to `{view === 'options' && <OptionChain />}`, ~line 602):
```tsx
            {view === 'ostrategy' && <StrategyBuilder />}
```

### 2. `services/ui-api/main.py`
```python
from routers import options_strategy
...
app.include_router(options_strategy.router, prefix="/api/options", tags=["options-strategy"])
```
(Frontend posts to `/api/options/strategy/analyze`; Next.js already rewrites `/api/*`.)

## Test results

- `pytest tests/test_options_math.py -q` → **18 passed** in 0.17 s.
- Full ui-api suite → **383 passed** right after my build (baseline 365 + 18 new, zero regressions). A later re-run shows 414 pass + 1 fail in `tests/test_derivatives.py` — that file (and `routers/derivatives.py`) is **W2's in-flight work**, untracked, created 03:12 while I ran; excluding only W2's file: **400 passed, 0 failed**. Nothing of mine touches it.
- `tsc --noEmit` → clean. `compileall` → OK. `mypy options_math.py routers/options_strategy.py --ignore-missing-imports` → **no issues**.
- Hard assertions, exactly as tasked: put-call parity `C−P = df·(F−K)` to 1e-9 across moneyness/tenor/vol · **bull-call-spread BE = K1 + net debit exactly** (1e-9) · **iron condor max profit = net credit** (and max loss = (width−credit)·lot, BEs = short strikes ∓ credit, exact) · **B-76 delta → 1 deep ITM** (and −1 put, 0 OTM) · **theta < 0 for long ATM** call and put · short call unbounded loss vs short put bounded at K−premium (at S=0) · straddle two exact BEs + unbounded-profit flag · covered call (fut+CE) capped profit = (K−entry+prem)·lot · calendar-book bisection roots verified to \|payoff\| < 0.05 · grid contains kinks + BEs with 0 P&L at the BE row · STT on sell side only; round-trip symmetry · 422 on 5 legs, 400 `invalid` on a CE without strike.

## Worked example — real NIFTY chain (pulled live from `GET /api/market/option-chain/NIFTY`)

Chain: NIFTY, bhavcopy **2026-10-14**, expiry **2026-10-19** (5d, priced at 5.5d), spot 22 622.70, **forward 22 612.46** (put-call parity), **lot 65**, ATM 22 600, ATM IV 12.5%. ATM row: CE ₹144.20 (IV 12.5), PE ₹131.75 (IV 12.5).

**Long straddle, 1 lot each (buy 22600 CE @144.20 + buy 22600 PE @131.75):**
- Entry: **NET DEBIT ₹17,936.75** (= (144.20+131.75) × 65)
- Breakevens (exact): **22 324.05 / 22 875.95** (= 22 600 ∓ 275.95, strike ∓ total premium)
- Max loss **−₹17,936.75 at 22 600** (bounded) · max profit **unbounded** (upside flag)
- Net Greeks: Δ **+2.26** units (≈ ₹51k of NIFTY — forward sits 12.46 over the strike), Γ 0.149, **θ −₹1,630/day**, ν +₹1,437/vol-pt, ρ −₹2.7/+1%
- Model check: B-76 at chain IVs reprices the legs ₹144.56 / ₹132.11 vs market 144.20 / 131.75 (the chain rounds IV to 0.1 — the model reproduces the market, as it must by construction)
- Margin ESTIMATE ₹17,936.75 (both legs long → premium only) · Costs ESTIMATE round trip **₹127.93** (brokerage ₹80 @ ₹20/order, STT ₹17.94 sell-side only, txn ₹12.57, GST ₹16.67, stamp/SEBI/IPFT ₹0.76)
- Payoff grid 104 points spanning 19 899 → 25 326 with both BEs as exact grid points (expiry P&L = 0.00 there); at the forward: expiry −₹17,127, today +₹47.

## Cuts (stated, not hidden)

- **Margin is a heuristic, loudly labelled**: no SPAN file parsing; short ≈ fut-margin% (index 12 / stock 20, overridable) × notional + premium; spread benefit shown only as the defined-risk \|max loss\| floor.
- **`shared/trading_costs.py` gap stated in the payload**: it models cash equity only (delivery/intraday literals), so NSE F&O statutory FY25-26 rates are encoded in `options_math.py` (STT 0.1% sell premium / 0.02% fut sell, txn 0.03503%/0.00173%, SEBI ₹10/cr, stamp 0.003%/0.002% buy, IPFT, GST 18%); square-off assumed; **exercise STT at expiry (0.125% of intrinsic) not modelled** — the note says so.
- Calendar spreads: supported in the model (per-leg `days`, nearest-expiry payoff with B-76 residual value, bisection BEs) but the UI seeds one expiry per book in v1.
- Futures legs: delta only (carry/basis ignored — stated in the Greeks note). IV solver not needed (chain supplies IVs; parity fallback for the ITM side).
- Position-Greeks wiring to the paper book (GAPS §2 "PARTIAL") is a follow-up: the math is now a reusable lib.

## Risks

- EOD chain premiums go stale intraday; the subtitle shows the bhavcopy date and every premium/IV is editable. Live reseeding could later use `option-chain-live` during market hours (deliberately not wired: quota + session discipline).
- Deep-ITM strikes can carry null IV on both sides in thin chains → leg falls back to ATM IV (today-curve shape only; expiry math is IV-free).
- Black-76 theta can be slightly positive deep ITM (discount unwind) — correct math; tests pin the ATM-negative claim.
- `scripts/ui_audit.py` page count: OSTR adds a 38th page once the PM lands the patch blocks.
