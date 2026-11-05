# GOLD program — final report (5 Nov 2026, 04:15 IST)

**Status: deployed and live.** The 43rd page `GOLD` (GO `GOLD`, aliases `XAU` `GC`; sub-views HEALTH · DAILY · WEEKLY ·
MONTHLY · POSITIONING · PHYSICAL · MACRO · CONTRACTS · LEARN) runs on the terminal (UI release `20261105-034204`), in the
desktop app (43-page shell installed 4 Nov 23:20) and on the phone through the same ui-api. The pre-open desk, its accuracy
log and the gold one-liners on BRF / WEI moved here (repetition rule T9); CMDT lost its duplicate desk.

## What the owner asked for → where it is

| Ask (26 Oct brief) | Where | Verdict label |
|---|---|---|
| CFTC COT for COMEX gold, who is long / short, what got closed, weekly | POSITIONING p.hero / p.whois / p.history / p.crowd / p.decomp; WEEKLY w.whodid; HEALTH H3 clause; BRF/WEI line; Saturday Telegram digest | `context` — "describes, does not predict" (G-STUDY: 0 of 69 rules beat buy-and-hold) |
| Daily "which positions got closed" | DAILY d.quadrant (OI × price quadrants, 20-day tape); POSITIONING p.daily.comex (CME VOI by product, T+1) and p.daily.mcx (per contract, selected family, "over N sessions" when a session is missing) | `context` |
| OTC deals, supply/demand, physical | PHYSICAL ph.ladder (COMEX → USD/INR → landed → duty → duty-paid → IBJA → MCX, one clock per number), ph.india, ph.shanghai (same-date pair), ph.etf (GLD/IAU, WGC with attribution), ph.official (IMF holders, troy ounces → Moz / t), ph.otc (LBMA turnover, vaults, EFP), ph.comex.stocks link (O-2) | `context` / `arithmetic`; WGC/LBMA rows wait for O-1 |
| Kitco-style chart | DAILY d.24h / d.3day / d.tape from stored 1-minute GC=F bars with session bands (UTC offsets fixed in wave 1c); Kitco stays a link | `arithmetic` |
| Days / weeks / months | DAILY, WEEKLY (grid, COT, IBJA, GLD), MONTHLY (return ladder in $, ₹, basket; seasonality grid with the GS-P4 verdict; official sector bars) | `context` |
| Health check for gold | HEALTH h.verdict: rule-based sentence from the gauges (week, driver GOLD-SPECIFIC / DOLLAR-DRIVEN only when both legs exist, funds, India basis, roll, ETF), every threshold visible in the P layer, ends "describes, does not predict"; no score | `context` |
| Contract selector | header picker (GOLD / GOLDM / GOLDTEN / GUINEA / PETAL × expiry) feeding CONTRACTS (DES card for the matched COMEX month, roll calendar with FND/LTD from the CME calendar, MCX chain, carry in one convention), DAILY/WEEKLY/POSITIONING | `arithmetic` |
| Macro drivers | MACRO mc.drivers (real yield, DXY from DX-Y.NYB, USD/INR, GVZ, breakeven, 2-y), KGX "gold or the dollar" split, Fed path (next FOMC 16 Dec statement), US calendar (full week, ★ High / FOMC) | `context` |
| Beginner → sophisticated | LEARN: curriculum (B/P layers), 160 glossary terms + 272 aliases + a start-here dozen, routines in plain titles; `<Term>` on first use across the views; tooltips on every field (259) | — |
| ICICI auto-login | BRKR "Auto-login (TOTP)" panel + `/api/positions/totp/*`; the secret goes to the Keychain and is never echoed; until the owner registers it the 08:00 job keeps asking for the SMS OTP on Telegram (O-4) | — |
| "Analyse first, publish only if useful" | 140 sources with verdicts (SOURCES.md → docs/GOLD_DATA_DICTIONARY.md); a catalog row gates every panel; FINDINGS.md: every positioning / flow / macro / seasonal series FAILS as a forecast, PASSES as a description; three critics + a re-review before this report | — |

## How it was built and checked

Phase 1 research (10 agents) → PLAN.md; wave 1 (8 builders + 8 adversarial checks) → wave 1b fix round (same) → deploy
4 Nov 23:10 → critics (trader 4.5 HOLD, beginner 6 PUBLISH-WITH-FIXES, data 4 HOLD; 75 findings, 19 blockers) → wave 1c
(5 builders + 5 checks; the PM fixed the three re-check majors by hand) → redeploy 5 Nov 03:50 → 43-page audit 43/43 in
Chromium and WebKit (0 console errors) → re-review by the data and trader critics: **PUBLISH-WITH-FIXES 7.5 and 7** (`critics/REREVIEW.md`; 33 of 36 and 57 of 61 refs closed on the live page, none regressed) → the three leftovers fixed and shipped at 04:10 (UI `20261105-041017`, ui-api restarted): next FOMC from the Fed's published calendar (9 Dec decision, statement 10 Dec 00:30 IST) instead of the Atlanta tracker's IMM horizons; the SGE tile prints the pair date's own CNY/g, USDCNY and $/oz legs and lists a newer SGE print alone; the WEI/BRF headline is cut at a word boundary; the pre-open 'Trade the open only if' sentence became a labelled house rule; the MACRO chip separator. Remaining minors (strip label doubled, COT release listed twice in the event strip, GVZ unit word, c.spec margin-history count, partial-bar flag on the 4 Nov bar) are logged in `critics/REREVIEW.md` for the next polish pass.
Gates at redeploy: core 970 · scripts 361 · ui-api 1,182 · execution 7 · alpha 20 · cargo 154 + clippy/fmt · tsc · ten node
checks (gold.check 221, gold_views, pages 281, desktop 398 …) · validate_learn · dictionary `--check` · parity old vs new
release 42 shared pages at parity + GOLD new.

## Data tier tonight

21 point-in-time `gold_*` tables in market.duckdb: COT 1986→ (6,417 reports), Treasury/FRED/Atlanta Fed daily history,
Yahoo daily 1990→ (19 symbols incl. DXY, USD/INR, FX, GOLDBEES, per-month COMEX contracts) + 1-minute GC=F / INR=X / SGE,
ETF holdings 2004→, SGE 5,110 rows, IMF official sector (ounces, per-month scale check), IBJA, RBI, MCX master + margins,
CME calendar (266 contracts) + product reference + today's VOI/EFRP; the CME 2014→ / 2017→ histories run 5 Nov ≥ 10:00.
Two feeds that had never delivered were fixed on the way: the CME FTP `229` passive reply and FRED's user-agent stall.

## What is still open (owner)

- **O-1** terms posture for WGC / LBMA rows (display with attribution on the private terminal, or links only): the ETF
  region flows, LBMA turnover and vault panels stay empty until then.
- **O-2** CME browser block: bulletin settlements and warehouse stocks stay LINK-ONLY; the strip prints the matched month's
  last trade labelled "Yahoo, not settlement".
- **O-3** confirm the 15 % duty at CBIC (dated constant since 13 May 2026).
- **O-4** register the ICICI authenticator setup key in the BRKR panel (or the Keychain one-liner in OWNER_GUIDE.md) so the
  08:00 login needs no OTP.
- **O-8** MCX bhavcopy / category OI / Breeze daily history: dormant collectors.
- **Pre-open model**: the accuracy log says the ₹300 fair-open heuristic has been worse than "open = yesterday's settlement"
  on the mornings logged so far; the panel says so. Keep logging; retire or re-fit after 20 rows.
- The Telegram COT digest line first fires Sat 7 Nov 02:30 IST (post-DST calendar); glance at it.

Evidence: `build/wave1.md`, `build/wave1b.md`, `build/wave1c.md`, `critics/`, `qa/`, `FINDINGS.md`, `OWNER_GUIDE.md`.
