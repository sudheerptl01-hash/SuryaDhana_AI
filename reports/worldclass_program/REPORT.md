# World-Class Program — Final Report to the Owner
**15 Oct 2026, 03:00–05:00 IST · two agent teams: 8 expert builders + 2 adversarial critics**
Trail: `PLAN.md → GAPS.md → build_w1..w8.md → critique_trader.md + critique_engineering.md →
evidence_brief_check.md + feature_brief_status.md → this report.` Builds on the Bloomberg program
(14–15 Oct, `reports/bloomberg_program/`).

## Verdicts (both critics, same night, independently)
- **Trader critic (C1, full trading-day walkthrough, 30+ screenshots, every number hand-footed):**
  **TRADE-READY** for NSE cash (EOD swing/positional), NSE F&O analytics + pricing, MCX gold
  pre-open/paper. **NOT YET** for intraday execution-grade work (the tick store has never seen a
  live session) or live MCX session trading (quote entitlement unverified until the 08:00 login).
  Workflow scores: pre-market 9 · pre-open 8.5 · NSE session 8 · MCX gold 8 · EOD 8 · cross-cutting 7.
- **Engineering critic (C2, four independent recomputations, all EXACT):** **SHIP-WITH-FIXES** —
  and the fixes shipped the same hour (below). Bloomberg bar, previous night → now:
  FAST 6→7.5 · LIVE 3→5 · NEVER-LIES 6.5→**8** · SURVIVES 3→4.5 · SCALES 7→7.5 · DISCIPLINED 7.5→8.

## What the 8 builders shipped (all live, 42 terminal pages now)
| Page | What a trader gets | Verified |
|---|---|---|
| **CHRT** Chart studio | candles + volume, EMA/BB/RSI, D/W/M + intraday-ready (W6 contract), crosshair, provenance labels | W/M resample exact vs raw; 15 tests |
| **DERV** Derivatives desk | futures term structure, annualized basis history, rollover tracker (per-expiry panel built from UDiFF bhavcopies), PCR/VIX percentile | basis legs reconcile to stored OI **to the share**; C2 recomputed from raw files — exact |
| **OSTR** Options strategies | 8 templates, ≤4 legs, exact breakevens, B-76 Greeks, max P&L, cost/margin estimates, `paper_only` | put-call parity 1e-9; C1 hand-footed the straddle; 18 tests |
| **MCXG** MCX gold desk | session clock 09:00–23:30 + MCX 2026 holiday calendar, GOLD/GOLDM/GOLDPETAL/GUINEA specs + expiry engine, Breeze quote path (honest degrade), COMEX×INR overlay, paper ticket | expiry observed==computed all 4 contracts; ticket to the rupee; 25 tests |
| **RSK** Risk dashboard | hist-sim VaR95/99 + ES, β decomposition, COVID/election/2022 stress replays, drawdown ladder vs the −20% HARD stop, empty-book honesty | C2 recomputed VaR/ES/β — exact to 2dp; 17 tests |
| Tick persistence (W6) | live ticks → daily parquet parts + 1m/5m/15m bars + VWAP endpoints (feeds CHRT) | 26 synthetic-tick tests; cumulative-ttq volume logic hand-checked; **first live session still pending** |
| Flaw fixes (W7) | 60s bulk cache: `alpha/universe` 1.45s→**55 ms**, `lw/screener` 3.0→1.4 s; payload trims (announcements poll −84%); clean 404s; one 422 envelope everywhere | measured before/after + single-flight proven under 10 concurrent |
| Research ops (W8) | **MC drawdown lens** (10k block-bootstrap; pre-registered DD-FRAGILE rule): S1 gateA within budget, **S1-gateB/S1H flag DD-FRAGILE** — owner should read `alpha_lab/reports/mc_drawdown.md`; **Friday decision journal** 20:10 job | 15 tests; dry-run produced the real page |

**Gate after integration: 934 → 937 tests, 0 failures · tsc clean · 42/42 pages, zero console errors.**

## Critic findings → status (same night)
| Finding | Severity | Status |
|---|---|---|
| GO bar startsWith-matching hid the new pages ("gold" never surfaced MCXG) | MED-HIGH (C1) | **FIXED** — substring across code+label+hint, ranked |
| Unbounded `days` on 2 GETs → unclamped panel pulls, 2 GB RSS ratchet | HIGH (C2 E1) | **FIXED** — Query bounds (422), `_LOCKS` capped; verified live |
| fo_analytics panel-build race (claim outside lock) | MED (C2 E2) | **FIXED** — atomic claim under lock |
| MCX ticket accepted "NaN"/"Infinity" | LOW | **FIXED** — finite check, 422 |
| RSK "Unknown" sector tripped the 40% crit chip | LOW | **FIXED** — unclassified bucket excluded from the cap check |
| mc.py traceback on short curves | LOW | **FIXED** — clean exit |
| PORT tab is the dormant legacy book with a LIQUIDATE button | LOW-MED (C1) | **Mitigated** — labeled "LEGACY engine book (dormant) — live paper NAV is on DESK"; full banner queued |
| Journal composer reported healthy jobs as errored ("done" missing) | — (PM catch) | **FIXED** earlier + regression test |
| tick_store shutdown join >10s edge | LOW (C2) | noted — inert until LIVE_TICKS=1; queued |
| W5's 2.01% VaR sanity figure | INFO | C2's recompute (1.89%) is the number; β matched |

## THE MISSING LIST (your explicit ask)
**Buildable next, ranked by trading value (C1's ranking + the briefs' additions):**
1. **Prove intraday end-to-end**: one market-hours session with `LIVE_TICKS=1` → ticks → parquet →
   CHRT 1m bars + VWAP. Everything is wired; it has simply never seen an open market. (Owner flips the switch.)
2. **MCX gold price history + chart** from free MCX bhavcopy (a gold desk without a gold chart) — ingest + CHRT extension.
3. **MCX trend sleeve research** (Evidence Brief sleeve 3: EWMAC/breakout/carry on gold/crude/natgas) — pre-registered study after #2's data lands.
4. **Real SPAN margin** from free NSE/MCX SPAN files (current heuristic over-margins condors ~10×, labeled).
5. **Index intraday in CHRT** + ticker→CHRT suffix + profile→chart link (C1 #3 polish).
6. **Per-strike option archive build** (feature brief §12 recipe) — unlocks IV-surface/skew features (OPT-02/03/04/06).
7. **Four pre-registered P1 tests** queued in claims_matrix §B: O/S ₹-volume · variance risk premium · index OI-PCR · F&O-exclusion events.
8. IC-decay monthly report · event sub-signals (index add/delete, lock-ins) · slippage-audit closed loop · CF "since last close" dawn window · HRP when a second sleeve passes gates.

**External — money or agreements, not code (verified by C1):** true L2/L3 depth (NSE TBT/colo) ·
professional news wire · consensus estimates · real-time F&O OI · MCX tick history · live CME
gold · SEBI algo-ID path for live order routing. One correction from C1: **FX reference rates are
buildable free (RBI)** — moved off the external list.

## The two owner actions that outrank everything above
1. **Git commit + private remote (10 min).** Still: no remote, last commit 14 Jun, ~503 untracked
   files including the frozen trading rules. The 02:15 backup now exists and is sha256-verified —
   but it is same-disk. This remains the single biggest risk to the whole system.
2. **`LIVE_TICKS=1` in `.env`** when you want live prices — the first market-hours session is the
   acceptance test for ticks, VWAP, intraday charts and the honest LIVE chips.
   (PM deferred check: after the 08:00 login, `curl :8010/api/mcx/quote?contract=GOLD` — exact
   expectations in build_w4.md.)

## What the critics called genuinely world-class already
The honesty system end-to-end (every degrade carries its reason + as-of; the terminal displays its
own critic's NO verdict in RSCH) · math exactness everywhere both critics recomputed · the
measured performance work (55 ms where 1.45 s was, single-flight proven under concurrency) ·
paper-only + frozen rules verified at runtime by both critics independently.
