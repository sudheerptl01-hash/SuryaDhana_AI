# R-DRIVERS — Which companies drive NIFTY (index-contribution leaderboard)

Date: Wed 4 Nov 2026, 22:30 IST · Author: terminal-v2 research agent R-DRIVERS · Posture: READ-ONLY review + prototype
(nothing under `services/`, `ui/`, `scripts/`, `data/` was changed; the prototype ran on a read-only copy of the
4 Nov DuckDB backup). Evidence files: `reports/terminal_v2/R-DRIVERS/evidence/` and the chart
`reports/terminal_v2/R-DRIVERS/nifty_drivers_prototype.png`. Label of everything proposed here: **DESCRIPTIVE
(attribution) — `arithmetic` with a fit chip, `context` for concentration and driver changes; never a forecast, never a
feed into the Decision Desk.**

## Executive summary (10 lines)

1. The owner's "CBOS"-style ask is an **index-contribution leaderboard**: Bloomberg's `IMAP` (sector-grouped movers by
   contribution), `MEMB` (members + weights) and `MRR`/`PORT` contribution-to-return views. The terminal already has the
   *today-only* half of it (MOV "Who moved the index", MEMB), rebuilt live at request time — no history, no horizons, no
   driver-change view, no BANKNIFTY history, no Desk-vs-NIFTY, and MEMB's YTD attribution is wrong by construction.
2. Method established and prototyped: points_i,d = prev index level × PIT free-float weight_i,d × adjusted return_i,d,
   summed per name across sessions (additive, so 1d/5d/1m/3m/60s/YTD are the same table sliced).
3. Fit on 229 sessions (2 Dec 2025 → 4 Nov 2026) against NSE's own closes: **R² 0.996, MAE 9.4 points per day** (mean
   |daily move| 165), YTD −2,132 explained of −2,169 actual (98 %). Good enough to show, with the residual on the page.
4. Free weights: NSE publishes **no full daily weight file**; `equity-stockIndices` (which once carried `ffmc`) is gone
   (404). What is free and verified today: the daily **top-10 weights** file (53.13 % of NIFTY 50), the constituent lists
   (50 / 14 names, with industry), every index's daily close in `ind_close_all`, and the monthly factsheet PDF.
   Rebuilt weights (shares × price × (1 − promoter %)) land within **0.22 pp MAE** of the official top-10 and can be
   calibrated name by name (LT needs ×0.88, the banks ×1.03–1.05).
5. Who drives NIFTY now (descriptive): 20-session leaders on 4 Nov are **BHARTIARTL +163, RELIANCE +130, ICICIBANK +121**
   points; monthly leaders flipped in 5 of the last 6 months (May RELIANCE↓, Jun ICICIBANK↑, Jul–Aug HDFCBANK↓, Sep
   ICICIBANK↓, Oct **INFY↑**, Nov RELIANCE↑). YTD the index's fall is HDFCBANK −775, RELIANCE −375, INFY −324, ITC −323.
6. A raw "leader" flips every 2 sessions (63 changes in 208); with hysteresis (lead ≥ 1.3× the runner-up for 5 sessions)
   it is 5 changes in 2026, and on a 60-session window 3 (HDFCBANK → INFY 14 Jul → ICICIBANK 27 Jul → HDFCBANK 11 Sep).
7. Breadth vs index: equal-weight 50 minus NIFTY over 20 sessions is **−0.95 pp** (narrow rally since 13 Oct; YTD +5.55 pp:
   the heavyweights did the damage, the median member did not).
8. Three data traps found and fixed in the prototype: `nse_bhavcopy.prev_close` is unadjusted (KOTAKBANK 1:5 split on
   14 Jan 2026 showed as −80 %); the Yahoo `market_index_daily` series **lacks the Sunday 1 Feb 2026 Budget session**
   that the bhavcopy and NSE's file both carry (a 492-point one-day miss, and a one-day shift in the 200-DMA crash
   filter); NIFTY BANK closes live only in a weekly-rebuilt CSV (last 30 Oct).
9. Proposal: four PIT tables, one 19:25 job (2–3 paced GETs/day), `/api/market/index-drivers`, MEMB extended with a
   horizon selector + driver-regime strip + monthly leaderboard + sector/breadth panels (MOV keeps the live today panel;
   no page added, no number twice), the Desk-vs-NIFTY panel on DESK, tests for PIT/identity/split/special-session.
10. Ratings (this scope): UI 5/10 · data update 4/10 · scalability 6/10 · honesty of what exists 8/10. Total build
    ≈ 3–4 builder-days; everything free; paid NSE Indices constituent weights only if the owner wants exact weights.

## 1. What the owner asked, and what the best terminals do

| Need in the brief | Where it exists elsewhere (function / product) | Free Indian data that feeds it |
|---|---|---|
| "which companies are driving Nifty now … earlier Infosys" | Bloomberg `IMAP` (intraday market map: sector groups, each member's contribution to the index move), `MEMB` (members, weights, contribution), `MRR` (member ranked returns), `MOV` (index movers in points); LSEG Workspace "Index Constituents → Contribution"; TradingView heatmap sized by market cap; NSE's own site shows "contribution to index" per member; Trendlyne / Moneycontrol "Nifty contributors" widgets | `nse_bhavcopy` closes (stored, 2010→), NSE daily index file `ind_close_all`, the top-10 weights file, constituent lists, XBRL shares + shareholding (stored) |
| 1d / 5d / 1m / 3m / YTD attribution | Bloomberg `PORT` attribution tab (daily-linked contribution), `MEMB` with period selector | the same table, sliced (points are additive across sessions) |
| sector contribution | `IMAP` groups, `GRR` (group ranked returns) | the `Industry` column of `ind_nifty50list.csv` (NSE industry) |
| concentration | `MEMB` top-N weight, HHI in `PORT` risk tab | weights (rebuilt + calibrated) |
| "driver change" | no standard function; Bloomberg users read `MRR` over windows | our rolling-window leader with hysteresis (new) |
| breadth vs index | Bloomberg `BRDTH`, equal-weight vs cap-weight indices (NIFTY50 EW is a paid index) | equal-weight of the 50 vs NIFTY from stored closes |
| BANKNIFTY | same functions on `NSEBANK Index` | `ind_niftybanklist.csv` + `ind_close_all` "Nifty Bank" row + NSE Bank capping rules |
| the Desk vs NIFTY | `PORT` attribution (Brinson allocation / selection) | the Desk's lots (SQLite) × stored closes |

Where paid data would help, plainly: NSE Indices sells daily constituent-level weights (and the Investable Weight
Factors); Bloomberg `MEMB` carries exact weights. Nothing here needs them: the free top-10 file plus a calibrated
rebuild explains 99.6 % of daily variance.

## 2. What the terminal has today (evidence) and the gap

**Exists, works, is honest:**
- `services/data-service/main.py` `/db/index-contribution` (lines 1617–1665): live members from NSE `heatmap-symbols`,
  weights rebuilt as shares (XBRL filing, `financials.shares_estimate`) × previous close × (1 − promoter % from
  `nse_shareholding`), points = prev level × weight × % change; returns `explained_points` next to the actual move.
  Today: actual +149.8, explained +154.4 (`evidence/sample_db_index_contribution_today.json`).
- `/db/index-memb` (lines 1668–1716): the same weights plus 1M/3M/YTD/1Y returns, 52-week distance, P/E, growth, top-5
  weight, weight-implied P/E, and `ytd_contrib_pp = today's weight × YTD return`.
- UI: MOV page panel "WHO MOVED THE INDEX" (`ui/components/IndexContribution.tsx`, hosted in `LiveMovers.tsx` and in
  BRF) with the chip "actual +149.8 pts · explained +154.4 (3 % off)" — screenshot `evidence/movers_2026-11-04.png`;
  MEMB page (`ui/components/IndexMembers.tsx`) with WEIGHT / TODAY / PTS / 1M / 3M / YTD / YTD PTS columns and the strip
  "Top 5 weight 36.6 %" — screenshot `evidence/memb_2026-11-04.png`. Both pages audited clean (0 console / page / request
  errors, `ui_audit.py --tabs memb,movers`, chromium).
- Stored inputs: `nse_bhavcopy` 2010-01-04 → 2026-11-04 (8.26 M rows, 4,181 EQ symbols), `nse_shareholding` 5,921
  filings (2015-12-31 → 2026-10-27), `data/nse_archive/financials/*.json` (2,028 companies, `shares`, `face_value`,
  `filed_at`), `splits` (1,038 rows incl. KOTAKBANK 2026-01-14 ×5, HDFCBANK 2025-08-26 ×2), `market_index_daily`
  (NIFTY50 + INDIAVIX only, Yahoo, 2009-09-22 →), `data/nse_archive/derived/index_valuation_history.csv` (15 NSE
  indices, daily closes 2012-02-21 → 2026-10-30, rebuilt weekly by the 19:15 job), `index_membership` table (snapshot
  only — `scripts/backfill_index_membership.py` says so).

**Gaps (each is a finding, with the evidence):**
1. **Nothing is stored.** Weights and contributions are rebuilt on every request from a live NSE call; there is no
   point-in-time history, so "who drove the index over the last month / since the leader changed" cannot be answered
   (the MEMB page took 6.8 s to settle in the audit; ui-api gives the route a 60 s timeout, `routers/markets.py:916`).
2. **MEMB's YTD attribution is wrong by construction**: `ytd_contrib_pp = today's weight × YTD return` with today's
   members; the page itself admits "today's members × weights explain −5.4 %" of a **−11.8 %** year (screenshot). The
   daily-linked PIT sum explains −2,132 of −2,169 points (98 %).
3. **No horizons beyond today**, no sector contribution, no concentration over time, no driver-change view, no
   breadth-vs-index divergence, no BANKNIFTY / NEXT 50 / IT history (only NIFTY50 is in `market_index_daily`).
4. **Free official weights unused**: the daily `top10nifty50_DDMMYY.csv` (verified 200 today) is listed in
   `docs/NSE_DATA_DICTIONARY.md` but nothing ingests it; it would calibrate the 10 names that are 53 % of the index.
5. **Index-level series from Yahoo misses special sessions**: `market_index_daily` has no 2026-02-01 (Sunday Budget
   session) while `nse_bhavcopy` (3,079 rows that day) and NSE's `ind_close_all` (NIFTY 50 24,825.45) have it. Yahoo and
   NSE closes agree to 0.0 points on every common day, so the only defect is the missing session. Side effect outside
   this scope: `shared/momentum.py`'s crash filter (NIFTY vs 200-DMA) reads this series, so its average is one session
   off since February.
6. **`nse_bhavcopy.prev_close` is unadjusted** (the store's own `adjusted_closes` docstring says so, `duckdb_store.py:965`).
   Any history must go through `shared.nse_panel.adjust` + `splits`; the live panel is safe because it uses NSE's `pChange`.
7. **Membership is not point-in-time**: the current 50 applied to 11 months. NIFTY 50 is reconstituted semi-annually
   (effective the last trading day of March and September) — a name added in September carries pre-entry points in the
   3m/YTD slices until a membership history exists.
8. **`ind_niftybanklist.csv` now lists 14 names** (AUBANK, YESBANK, UNIONBANK, CANBK included); NIFTY Bank was 12 for
   years. Verify against the current methodology before shipping the bank panel.

## 3. Method (what the job will compute)

- **Universe per day**: constituents of the index on that day (PIT table; until a history exists, the current list with
  the "members as of <date>" chip).
- **Return per name per day**: `adj_close_d / adj_close_{d-1} − 1` from `shared.nse_panel.adjust(pick_equity_rows(bhav),
  splits)` — the store's own adjustment; a residual |move| > 25 % is flagged and excluded (none remained in the window).
- **Weight per name per day (PIT)**: `ffmc = shares × prev_close × (1 − promoter %)`, where `shares` come from the newest
  XBRL filing with `filed_at ≤ d` (scaled by any split with date in (filing period_end, d]) and `promoter %` from the
  newest shareholding filing with `broadcast_ts ≤ d` (fallback period_end + 21 days); weights normalised to 100 %.
  **Calibration**: on each day where the top-10 file exists, `iwf_correction_i = official_i / rebuilt_i` for those 10;
  the other 40 share the remaining 100 − 53.13 % pro rata. Store both methods so the page can say which one it shows.
- **Points**: `points_i,d = L_{d-1} × w_i,d × r_i,d` with `L` = NSE's closing index value (`ind_close_all`), never
  Yahoo. Identity check per day: `Σ_i points_i,d` vs `L_d − L_{d-1}` → `residual_d` stored and shown.
- **Horizons**: 1d / 5d / 1m (21) / 3m (63) / 60s / YTD / "since the leader changed" = sums of `points` (additive across
  days, no Cariño smoothing needed because the unit is index points, not %).
- **Sector**: sum of points by NSE industry (the list's `Industry` column).
- **Concentration**: top-5 share of Σ|points|, HHI of |points| shares, weight HHI → effective N, top-5 weight.
- **Driver state (context)**: rolling 20- and 60-session leader by |points|, with hysteresis (a challenger must lead the
  incumbent by ≥ 1.3× for 5 consecutive sessions on the 20s window; ≥ 1.2× for 5 on 60s); store `leader`, `tenure`,
  `leader_share`, `changed_from`, `change_date`. The wording on the page: "BHARTIARTL has led the 20-session move for
  N sessions (12.5 % of all member points) — describes, does not predict."
- **Breadth vs index**: equal-weight return of the members minus the index return over 20 sessions (pp); members up /
  down; "narrow" when EW − CW < −1 pp, "broad" when > +1 pp (thresholded words, no colour).
- **BANKNIFTY**: same pipeline with the bank list, the "Nifty Bank" row of `ind_close_all`, and NSE's capping (single
  name ≤ 33 %, top three ≤ 62 %) applied at each day's weights (approximation; the fit chip shows the cost).
- **Decision Desk vs NIFTY**: per-lot contribution of the Desk book (equal-weight, 66 % equity) in pp of NAV, next to
  NIFTY's points leaderboard over the same window; Brinson-lite split by NSE industry (allocation vs selection) as a
  second step. When the Desk is risk-off (as now) the panel says "book = liquid fund since <date>; nothing to attribute".

## 4. Data sources verified today (paced GETs, browser UA, 22:18–22:20 IST)

| Source | URL (exact) | Status / size | Fields | Cadence · publish (IST) | Terms / verdict |
|---|---|---|---|---|---|
| NIFTY 50 top-10 weights | `https://nsearchives.nseindia.com/content/indices/top10nifty50_041126.csv` (ddmmyy) | 200 · 370 B · text/csv | SYMBOL, SECURITY, WEIGHTAGE(%) — HDFCBANK 10.20, ICICIBANK 9.22, RELIANCE 7.91, BHARTIARTL 5.68, LT 4.17, SBIN 3.65, INFY 3.60, AXISBANK 3.20, KOTAKBANK 3.05, BAJFINANCE 2.45 (Σ 53.13) | daily after close; present at 22:18 today; exact minute not verified — read it in the 19:15 slot (same archive as `ind_close_all`, which that job already reads) with a 20:35 retry | NSE archive, personal / non-commercial use; display with attribution, never re-serve. **USE (PUBLISH-CORE for calibration)** |
| NIFTY 50 constituents | `https://niftyindices.com/IndexConstituent/ind_nifty50list.csv` | 200 · 3,344 B · 50 rows | Company Name, Industry, Symbol, Series, ISIN Code | updated on reconstitution (semi-annual, effective last trading day of Mar / Sep; ad hoc on mergers) — archive it daily to build the PIT history | niftyindices.com terms, personal use. **USE** |
| NIFTY Bank constituents | `https://niftyindices.com/IndexConstituent/ind_niftybanklist.csv` | 200 · 916 B · **14 rows** | same | same | **USE after the 12-vs-14 check** |
| All index closes | `https://nsearchives.nseindia.com/content/indices/ind_close_all_04112026.csv` (ddmmyyyy) | 200 · 15.7 KB | Index Name, Index Date, Open/High/Low/Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield — "Nifty 50, 04-11-2026, …, 23960.6, 149.75, .63, …" | daily, by 19:15 (the existing `index_valuation_daily` job reads it) | already used; **extend** it to upsert every index into `market_index_daily` (source `nse_daily_file`) |
| Monthly factsheet | `https://www.niftyindices.com/Factsheet/ind_nifty50.pdf` | 200 · 263 KB · PDF | top-10 constituents by weight, sector weights, methodology summary | monthly, first week of the next month | **LINK-ONLY** (the daily CSV supersedes it) |
| Per-constituent live incl. `ffmc` | `https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050` | **404** (also through the project's warmed `NseLive` session) | — | retired | **DO NOT USE** (dead) |
| Live members + % change | `https://www.nseindia.com/api/heatmap-symbols?type=…&indices=…` (what `/db/index-contribution` uses) | works via `nse_live.NseLive` | lastPrice, pChange, VWAP, quantityTraded | live, ~1 min delayed | keep for the MOV panel; no weights in it |
| Shares outstanding | NSE XBRL results filings already cached in `data/nse_archive/financials/<SYM>.json` (`paid_up`, `face_value`, `shares`, `eps`, `filed_at`) | stored | — | quarterly, `filed_at` timestamp = PIT | **USE** (with split scaling) |
| Promoter holding | `nse_shareholding` (stored; `broadcast_ts` = PIT) | stored | promoter_pct, fpi_pct, mf_pct | quarterly | **USE** (approximates the IWF; calibrated by the top-10 file) |
| Exact daily weights, IWF | NSE Indices data products (paid), Bloomberg `MEMB` | — | — | daily | **PAID — not needed** |

## 5. Prototype results (`evidence/drivers_proto.py`, `evidence/drivers_results.json`)

Window: 2 Dec 2025 → 4 Nov 2026 (229 NIFTY 50 sessions, NSE closes to 30 Oct + Yahoo for 2–4 Nov after verifying they
match to 0.0 pt on common days). Weights: PIT rebuilt (uncalibrated — the calibration needs the daily file stored).

**Fit (NIFTY 50):** MAE 9.44 pts/day · RMSE 13.3 · mean |actual move| 165 · R² 0.9963 · median explained share 1.003.
Before the two fixes the same run gave R² 0.948 (unadjusted split) and 0.973 (Yahoo index missing 1 Feb).

**Calibration vs the official top-10 (4 Nov):** rebuilt Σ 52.11 % vs official 53.13 %, MAE 0.22 pp. Per name
(official / rebuilt / implied correction): HDFCBANK 10.20 / 9.78 / ×1.043 · ICICIBANK 9.22 / 8.94 / ×1.031 · RELIANCE
7.91 / 7.67 / ×1.031 · BHARTIARTL 5.68 / 5.49 / ×1.034 · **LT 4.17 / 4.75 / ×0.878** · SBIN 3.65 / 3.49 / ×1.046 · INFY
3.60 / 3.50 / ×1.028 · AXISBANK 3.20 / 3.09 / ×1.035 · KOTAKBANK 3.05 / 3.00 / ×1.018 · BAJFINANCE 2.45 / 2.39 / ×1.024.
(LT has no promoter, so the promoter-only free float overstates it; NSE's IWF removes other strategic holders.)

**Horizon leaderboard (index points; "add" / "drag"):**

| Horizon (from) | Index | Explained | Added the most | Took away the most | top-5 share of Σ\|pts\| · up/down · EW − CW |
|---|---|---|---|---|---|
| 1d (4 Nov) | +149.8 | +148.8 | HDFCBANK +36.0 · TITAN +16.8 · ITC +15.9 · BAJFINANCE +14.1 · BEL +13.3 | INFY −14.5 · TCS −13.4 · ETERNAL −9.5 · KOTAKBANK −8.1 · HCLTECH −7.5 | 34 % · 35/15 · +0.27 pp |
| 5d (29 Oct) | +1,261.8 | +1,243.8 | RELIANCE +213.5 · HDFCBANK +164.9 · BHARTIARTL +75.6 · ICICIBANK +69.4 · ITC +53.5 | TCS −5.1 (49 of 50 up) | 46 % · 49/1 · −0.28 pp |
| 1m (6 Oct) | +1,404.8 | +1,360.1 | BHARTIARTL +182.2 · RELIANCE +173.8 · ICICIBANK +137.5 · HDFCBANK +102.3 · INFY +78.2 | SHRIRAMFIN −24.5 · COALINDIA −12.7 · ADANIENT −11.4 | 45 % · 43/7 · −1.03 pp |
| 3m (5 Aug) | −654.3 | −689.3 | KOTAKBANK +94.1 · BHARTIARTL +62.2 · ETERNAL +61.4 · ADANIPORTS +33.2 · RELIANCE +28.2 | BAJFINANCE −90.7 · M&M −89.2 · SHRIRAMFIN −69.7 · MARUTI −58.8 · SBIN −54.6 | 29 % · 11/39 · −1.53 pp |
| 60 sessions (10 Aug) | −610.1 | −628.4 | KOTAKBANK +105.2 · BHARTIARTL +68.6 · ETERNAL +56.5 · ADANIPORTS +35.4 · DRREDDY +25.8 | M&M −102.3 · SBIN −101.0 · SHRIRAMFIN −80.5 · MARUTI −55.2 · BAJFINANCE −49.2 | 34 % · 12/38 · −1.31 pp |
| YTD (1 Jan) | −2,169.0 | −2,131.9 | ICICIBANK +131.7 · ETERNAL +131.0 · BSE +77.1 · ADANIPORTS +65.4 · TITAN +58.0 | **HDFCBANK −775.4 · RELIANCE −375.4 · INFY −323.8 · ITC −322.8 · TCS −153.7** | 55 % · 21/29 · **+5.55 pp** |

Sector points: 1m — Financial Services +363.9, IT +221.1, Telecom +182.2, Oil & Gas +172.0; 3m — Financial Services
−298.1, Auto −220.1, FMCG −89.1 (Telecom +62.2 the only sizeable add); YTD — Financial Services −867.5, IT −490.4,
FMCG −408.2, Oil & Gas −384.9, Auto −268.5 vs Consumer Services +130.6, Metals +87.9.

**Monthly top-5 and the leader (by |points|), last 6 months + November to date:**

| Month | Index pts | Explained | Leader (pts, share of Σ\|pts\|) | Changed? | Added the most | Took away the most |
|---|---|---|---|---|---|---|
| May 2026 | −449.8 | −419.1 | RELIANCE (−155.1, 15 %) | yes | BSE +43.2 · ADANIENT +37.2 · HINDALCO +26.9 · GRASIM +26.3 · TMPV +23.2 | RELIANCE −155.1 · SBIN −89.4 · HDFCBANK −87.3 · ITC −73.3 · TCS −46.0 |
| Jun | +318.0 | +285.4 | ICICIBANK (+177.8, 13 %) | yes | ICICIBANK +177.8 · HDFCBANK +171.7 · BAJFINANCE +56.9 · SBIN +53.5 · INDIGO +45.5 | INFY −116.5 · HINDALCO −51.6 · TCS −48.6 · RELIANCE −38.5 · TATASTEEL −34.8 |
| Jul | +517.8 | +465.7 | HDFCBANK (−159.8, 11 %) | yes | INFY +93.8 · ICICIBANK +89.8 · BAJFINANCE +80.1 · BHARTIARTL +76.1 · ETERNAL +72.4 | HDFCBANK −159.8 · AXISBANK −69.3 · LT −58.7 · TRENT −29.1 · DRREDDY −26.7 |
| Aug | −303.2 | −322.2 | HDFCBANK (−125.0, 12 %) | no | ETERNAL +49.0 · KOTAKBANK +44.5 · AXISBANK +41.9 · LT +30.2 · SBIN +27.7 | HDFCBANK −125.0 · BHARTIARTL −101.0 · ITC −66.2 · BAJFINANCE −49.2 · RELIANCE −42.8 |
| Sep | −1,460.0 | −1,422.1 | ICICIBANK (−197.6, 12.5 %) | yes | ADANIPORTS +33.5 · ITC +18.9 · COALINDIA +11.6 · DRREDDY +10.0 · ADANIENT +3.4 | ICICIBANK −197.6 · RELIANCE −125.4 · INFY −101.5 · SBIN −86.0 · LT −81.6 |
| Oct | +432.6 | +405.9 | **INFY (+138.6, 11 %)** | yes | INFY +138.6 · BHARTIARTL +137.2 · ICICIBANK +113.9 · TCS +96.1 · KOTAKBANK +68.4 | SHRIRAMFIN −62.3 · HDFCBANK −51.1 · RELIANCE −30.9 · TATASTEEL −29.1 · ADANIENT −24.6 |
| Nov (3 sessions) | +907.5 | +888.6 | RELIANCE (+203.9, 20 %) | yes | RELIANCE +203.9 · HDFCBANK +140.8 · BHARTIARTL +59.4 · ICICIBANK +39.0 · ITC +37.5 | INFY −41.2 · TCS −14.2 · HCLTECH −5.1 |

So the owner's intuition is visible in the data: IT (INFY + TCS) led October's rise; in November's first three sessions
the leadership has gone to RELIANCE and the two big banks while INFY is the largest drag.

**Driver change rule (why hysteresis is mandatory):** the naive "largest |20-session points|" leader changed **63
times in 208 sessions** (current tenure 2 sessions). With hysteresis (challenger ≥ 1.3× the incumbent for 5 consecutive
sessions) there are **5 changes in 2026**: ICICIBANK → INFY (2 Mar) → KOTAKBANK (18 Mar) → RELIANCE (4 Jun) → HDFCBANK
(5 Aug) → RELIANCE (13 Oct). On the 60-session window (1.2×, 5 sessions): HDFCBANK → INFY (14 Jul) → ICICIBANK (27 Jul)
→ HDFCBANK (11 Sep). (Dates ±1 session: computed on the run before the NSE-close fix.) Current 20-session ranking (4 Nov):
BHARTIARTL +162.8 · RELIANCE +129.7 · ICICIBANK +121.4 · INFY +83.0 · HDFCBANK +81.0 · TCS +71.5 · LT +50.0 · HCLTECH
+44.3 · KOTAKBANK +42.2 · ITC +34.7; leader share 12.5 %, top-5 share 44.4 %; largest drag SHRIRAMFIN.

**Concentration:** weight HHI 0.0407 → effective N 24.6 of 50; top-5 weight 36.6 %; top-5 share of |points| ranges
29 % (3m, a broad sell-off) to 55 % (YTD). Chart: `nifty_drivers_prototype.png` (rolling contributions of today's top-6,
leader / top-5 share, EW − CW).

**Breadth vs index:** 20-session EW +4.25 % vs NIFTY +5.20 % → **−0.95 pp** (negative every session since 13 Oct; min
−1.80 pp on 23 Oct; max +3.51 pp on 8 May). 70 % of members rose on 4 Nov.

**NIFTY BANK (14-name list, 33 % / 62 % capping, NSE closes to 30 Oct):** R² 0.962, MAE 90.7 pts vs mean |move| 442 —
usable with the chip, visibly rougher than NIFTY 50 (capping approximation, 14 vs 12 names, no top-10 calibration file
for the bank index — the factsheet has it monthly). October: ICICIBANK +746.1, KOTAKBANK +621.1 added; YESBANK −344.1,
HDFCBANK −312.3 took away. YTD: HDFCBANK −4,988.5 of the index's −4,894.9 points. Top-5 weight 83.9 %, effective N 6.0.
Worst days (10 Jun +433, 20 Jul −425, 15 Oct +421 pts residual) coincide with large single-bank moves — the capping
needs the official quarterly cap factors, or the bank page shows "approximate weights" until then.

**Decision Desk vs NIFTY:** the Desk is **risk-off** (plan `2026-11-REB-2fd038`: NIFTY 23,053 < 200-DMA 24,041; 0 lots;
NAV ≈ ₹5.03 L in the liquid fund), so there is nothing to attribute. To show the method, the plan's ranked 20-name
watchlist as a hypothetical equal-weight 66 %-equity book over the same 60 sessions: +16.9 % vs NIFTY −2.5 %, every name
up, largest contributions RATNAVEER +2.15 pp, AEROFLEX +1.12, TFCILTD +1.09, WELCORP +1.04, FCL +0.98 — **ILLUSTRATIVE
ONLY**: the Desk did not hold these, no costs, and a momentum watchlist selected on 30 Oct looking back 60 sessions is
hindsight by construction. The production panel must show the real lots only.

## 6. Proposed design

### 6.1 PIT schema (data-service, `storage/duckdb_store.py`, four tables + one extension)

```sql
-- membership, archived every day from the free lists (history starts the day the job starts; reconstitutions back-filled by hand from niftyindices press releases)
CREATE TABLE index_constituents_daily (index_name VARCHAR, date DATE, symbol VARCHAR, industry VARCHAR, isin VARCHAR,
  source VARCHAR, first_seen_at TIMESTAMP, PRIMARY KEY (index_name, date, symbol));
-- weights, one row per method so the page can name what it shows
CREATE TABLE index_weights_daily (index_name VARCHAR, date DATE, symbol VARCHAR, method VARCHAR,  -- official_top10 | rebuilt | rebuilt_calibrated
  weight_pct DOUBLE, ffmc_cr DOUBLE, shares DOUBLE, shares_filed_at TIMESTAMP, promoter_pct DOUBLE, promoter_public_at DATE,
  iwf_correction DOUBLE, computed_at TIMESTAMP, PRIMARY KEY (index_name, date, symbol, method));
-- the attribution itself (additive across days)
CREATE TABLE index_contribution_daily (index_name VARCHAR, date DATE, symbol VARCHAR, ret_pct DOUBLE, weight_pct DOUBLE,
  points DOUBLE, prev_index_level DOUBLE, index_close_source VARCHAR, flag VARCHAR, computed_at TIMESTAMP, PRIMARY KEY (index_name, date, symbol));
CREATE TABLE index_contribution_fit (index_name VARCHAR, date DATE, actual_points DOUBLE, explained_points DOUBLE,
  residual_points DOUBLE, members_priced INTEGER, members_total INTEGER, computed_at TIMESTAMP, PRIMARY KEY (index_name, date));
-- driver state per window (context)
CREATE TABLE index_driver_state (index_name VARCHAR, date DATE, window_sessions INTEGER, leader VARCHAR, leader_points DOUBLE,
  leader_share DOUBLE, tenure_sessions INTEGER, changed_from VARCHAR, change_date DATE, top5_share DOUBLE, hhi_contrib DOUBLE,
  weight_hhi DOUBLE, effective_n DOUBLE, ew_minus_cw_pp DOUBLE, members_up INTEGER, members_down INTEGER, computed_at TIMESTAMP,
  PRIMARY KEY (index_name, date, window_sessions));
-- extension: every index from ind_close_all into the existing table (symbol e.g. NIFTYBANK, NIFTYNEXT50, NIFTYIT; source 'nse_daily_file')
```

Every row carries the time it was computed and the PIT inputs it used (`shares_filed_at`, `promoter_public_at`);
revisions are new rows by `computed_at` if a restatement is ever needed.

### 6.2 Jobs (master-controller → data-service `POST /jobs/index-drivers`, fetch + compute, never a restart)

- **19:15 `index_valuation_daily` (exists)**: also upsert every index's close from `ind_close_all` into
  `market_index_daily` (source `nse_daily_file`) — one line of work, fixes the special-session gap and gives BANKNIFTY /
  NEXT 50 / IT daily closes. Keep Yahoo rows as a second source; the drivers job prefers `nse_daily_file`.
- **19:25 `index_drivers_daily`** (after bhavcopy 18:30 and the index file 19:15; independent of the 19:30 Desk):
  GET `top10nifty50_<ddmmyy>.csv` (1 call), GET the two constituent lists (conditional, 2 calls; weekly is enough
  but daily archiving is what builds the membership history), compute weights (rebuilt + calibrated), contributions, fit,
  driver state for NIFTY 50 and NIFTY BANK (NEXT 50 / IT when the owner wants them). Retry at 20:35 inside
  `nse_positions_catchup` if the top-10 file was not yet published. Runtime: the prototype did 229 sessions × 50 names in
  under two minutes on the laptop; one day is sub-second.
- **Backfill (one-off, from stored data, no fetch)**: 2019-10 → today for NIFTY 50 (bhavcopy + filings exist; the
  constituent list is the current one until the Mar/Sep histories are entered; the page says "members as of today
  applied before <date>").
- Freeze windows: 19:25 lies inside 18:30–21:15 but this is a compute job on stored data plus three small GETs, in the
  same class as the 19:15 / 19:30 / 20:30 jobs that already run there; no restart, no data-service deploy.

### 6.3 API (ui-api `routers/markets.py`, proxied from data-service reads)

- `GET /api/market/index-drivers?index=NIFTY 50&horizon=1m` → `{as_of, index, horizon:{from,to,sessions}, index_move_pts,
  explained_pts, fit:{mae_60s, r2_60s, residual_today}, weight_method, members:[{symbol, industry, weight_pct, ret_pct,
  points, share_abs}], sectors:[{industry, points, weight_pct}], concentration:{top5_abs_share, hhi_contrib, weight_hhi,
  effective_n, top5_weight_pct}, breadth:{ew_pct, cw_pct, ew_minus_cw_pp, up, down}, driver:{window, leader, tenure,
  leader_share, changed_from, change_date}, history_since, badges:{members:"arithmetic", driver:"context"}}`.
- `GET /api/market/index-drivers/timeline?index=&window=60&days=250` → leader timeline + concentration series for the
  chart. `GET /api/market/index-drivers/monthly?index=&months=12` → the monthly leaderboard.
- `GET /api/desk/attribution?horizon=` → the Desk's real lots × stored closes (pp of NAV), NIFTY's leaderboard over the
  same window, allocation / selection by industry; `{risk_off: true, since}` when in cash.
- Cache: materialised by the job; the routes read DuckDB only (no NSE call on the request path, PLAN §0.1-3).

### 6.4 Page and panels (no new page; the 43-page gates stay)

- **MOV** keeps "WHO MOVED THE INDEX" (live, today) unchanged; its footer gains "history on MEMB ›".
- **MEMB** becomes "Index members & drivers" (GO aliases `DRVR`, `IMAP`): a **horizon selector** 1d · 5d · 1m · 3m ·
  YTD · since-leader-change; the members table's PTS column follows the horizon (the YTD PTS column is replaced by the
  linked sum — fixes finding 2); a **DRIVER REGIME strip** ("20s leader BHARTIARTL, 2 sessions; 60s leader HDFCBANK since
  11 Sep; top-5 of the move 44 %; EW − CW −0.95 pp: narrow") — `context`, neutral token, ends "describes, does not
  predict"; a **SECTOR CONTRIBUTION bar** for the horizon; a **MONTHLY LEADERBOARD** (last 12 months, leader + top-3
  add / drag); a **CONCENTRATION & BREADTH** chart (the three panes of the prototype chart); the **fit chip** on the
  table header ("explains −2,132 of −2,169 YTD points · MAE 9 pts/day over 60 sessions · weights: rebuilt, calibrated to
  NSE's top-10 on 04 Nov"); the index switcher 50 / BANK / NEXT 50 / IT as today. Same number once per page: the strip
  states the leader, the table shows the points, the chart shows the series — none repeats another.
- **DESK** gains "Book vs NIFTY" (real lots only; "in the liquid fund since 30 Oct" today).
- **BRF** keeps its one contribution line.
- **RSCH** CATALOG row: `("Index drivers", "DESCRIPTIVE", "Who moves NIFTY, in points, PIT weights …")` pointing at this
  report; `docs/NSE_DATA_DICTIONARY.md` gains the top-10 file's verified fields (it is listed, not described as ingested).

### 6.5 Labelling (binding, from `reports/gold_program/PLAN.md` §0.1 / §f)

Members, sectors, concentration arithmetic → `arithmetic` (an identity, with its residual shown). Driver regime, breadth
divergence, monthly leader → `context`; no bullish/bearish words, no colour on the leader; green/red only on points.
No composite score. Nothing from these tables enters `shared/momentum.py`, `shared/decision_desk.py`, alerts with a
direction, or the paper ticket. If anyone later wants "the leader change predicts…", that is a pre-registered study
first (FINDINGS row), never a badge change by assertion.

### 6.6 Tests and gates

`tests/test_index_drivers.py`: (1) PIT — no weight row uses `shares_filed_at > date` or `promoter_public_at > date`;
(2) identity — Σ weights = 100 ± 0.01 and Σ points = explained per day; (3) split fixture — KOTAKBANK 14 Jan 2026 return
within ±5 % after adjustment; (4) special session — 1 Feb 2026 present in the fit table with `index_close_source =
nse_daily_file`; (5) fit gate — 60-session MAE ≤ 25 pts else the API sets `fit.degraded = true` and the page shows
STALE-style "approximation degraded"; (6) calibration — on a day with the top-10 file, the 10 calibrated weights equal
the official ones to 0.01 pp; (7) repetition — `pages.check.ts`: the live today panel renders on MOV and BRF only, the
horizon table on MEMB only; (8) hosts — only `nsearchives.nseindia.com` and `niftyindices.com` are fetched.

## 7. Ratings (this scope: index attribution / drivers), with the evidence each rests on

| Area | Score | Evidence |
|---|---|---|
| UI (drivers / attribution) | **5 / 10** | MOV panel with explained-vs-actual chip and MEMB weights exist and audit clean (`evidence/*.png`, `ui_audit` 2/2 PASS); but one horizon only, MEMB "YTD PTS" explains −5.4 % of a −11.8 % year (on-page text), no sector / history / regime / BANKNIFTY-history / Desk views |
| Data update | **4 / 10** | nothing stored (live rebuild per request, `main.py:1617`); the free daily top-10 weights file is catalogued but not ingested; `market_index_daily` = Yahoo NIFTY50 + VIX only and lacks 2026-02-01; NIFTY BANK closes only in a weekly CSV (mtime 30 Oct 19:15); `index_membership` is a snapshot |
| Scalability | **6 / 10** | the maths is trivial (50 × 250 rows, prototype < 2 min for 11 months) but today's route re-fetches NSE and re-reads 50 filings per request (MEMB 6.8 s to settle; 60 s route timeout); materialising it removes the request-path work |
| Honesty of what exists | **8 / 10** | formula printed on the panel; residual shown ("3 % off"); "NSE does not publish live weights" stated; the YTD figure's own caveat is printed, though the number is still shown |

## 8. Top recommendations (value · cost · data)

1. **Store every NSE index close from `ind_close_all` into `market_index_daily`** (source `nse_daily_file`) in the
   19:15 job — fixes the special-session hole (also under the crash filter), gives BANKNIFTY/NEXT50/IT daily closes. S.
2. **Ingest the daily top-10 weights file and archive the constituent lists** into the two PIT tables. S.
3. **Nightly `index_drivers_daily`**: calibrated PIT weights, contributions, fit, driver state (hysteresis), for NIFTY 50
   and NIFTY BANK; backfill from stored data. M.
4. **MEMB → "members & drivers"**: horizon selector, driver-regime strip, sector bar, monthly leaderboard,
   concentration/breadth chart, fit chip; replace YTD PTS with the linked sum. M.
5. **DESK "Book vs NIFTY"** from the real lots (risk-off text when in cash). M.
6. **Membership history** for Mar/Sep reconstitutions 2024–2026 entered by hand from niftyindices press releases so the
   3m/YTD slices stop crediting pre-entry days. M (clerical).
7. **Intraday "who is driving the move right now"**: the 09:00–15:58 `internals_sample` job already polls NSE every 2
   min; add the heatmap members' % change to its sample so the live panel gets a within-day timeline (no extra NSE
   budget). M.
8. **Bank capping from the methodology** (official cap factors per quarter) before the bank panel goes beyond
   "approximate". S once the 12-vs-14 question is settled.
9. If exact weights are ever wanted: NSE Indices' paid constituent-weight product. Not needed for the above.

## 9. Open questions for the owner

- O-D1: extend MEMB (recommended, no page-count change) or add a 44th page `DRVR`?
- O-D2: approve the three small daily fetches (top-10 file, two constituent lists) and the display-only terms posture.
- O-D3: NIFTY Bank constituent file lists 14 names today — confirm against the current factsheet before the bank panel.
- O-D4: replace the Yahoo NIFTY50 series with NSE's daily file everywhere (crash filter, RSK, CHRT) — this changes the
  200-DMA by one session; the Desk rules say "DO NOT CHANGE without review", so it is the owner's call.
- O-D5: should the live MOV panel also apply the top-10 calibration (expected to cut the 3 % miss roughly in half)?
- O-D6: which extra indices beyond NIFTY 50 / BANK (NEXT 50, IT, MIDCAP 150) in the first release?

## 10. Evidence index

`evidence/drivers_proto.py` (the prototype; reads the read-only DB copy and the project's own `financials` /
`shared.nse_panel` helpers) · `evidence/drivers_results.json` (every number above) · `evidence/probe_sources.py` /
`probe_sources.json` (the paced source probes with status / size / content-type) · `evidence/sample_top10nifty50_2026-11-04.csv`
· `evidence/ind_nifty50list.csv`, `evidence/ind_niftybanklist.csv` · `evidence/sample_ind_close_all_2026-11-04_head.csv` ·
`evidence/sample_db_index_contribution_today.json` (the live endpoint's output at 22:20) · `evidence/memb_2026-11-04.png`,
`evidence/movers_2026-11-04.png` (audit screenshots) · `nifty_drivers_prototype.png` (chart).
