# C-DATA — data-correctness review of the GOLD page (release 20261104-230634)

Reviewed 4 Nov 2026 23:50 → 5 Nov 00:05 IST against http://127.0.0.1:8010 (GET only) and the data-service store on
:8001. Screenshots (1440×900, full page, every sub-view) and the DOM text of every `data-gold-panel`:
`/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/C-DATA/shots/`
(`<sub>_P.png`, `dom.json`); every payload fetched is under `…/scratchpad/C-DATA/api/`. The page was audited in its
default (beginner) layer; the P-layer clause table was read from `learn.health_rules`.

## Executive summary

**Verdict: HOLD (score 4/10).** The arithmetic that was re-derived by hand is right — the fair value chain
(4,077.5 × 94.63 × 10/31.1035 = ₹1,24,055 landed, × 1.15 = ₹1,42,663 duty-paid, basis +1.50 %), the COT managed-money
net (122,508 − 16,946 = 105,562; +1,356 w/w from 104,206; 10.56 Moz = 328 t = $43.0 bn), the DEC→FEB carry
(4,112.4/4,078.3 − 1 = +0.836 %, × 365/57 = +5.35 %/yr), GLD's changes (−2.85 t d/d, −3.99 t 5 d, −19.18 t over 30
stored points, −18.04 t 1 m, −32.9 t YTD), the trend tile (20 d −0.28 %, 200 d −9.55 %, 52-w drawdown −23.31 %), the
accuracy-log statistics, the decomposition table and every badge against the catalog. The honesty rules hold: the verdict
ends "describes, does not predict", there is no score, context tiles are neutral, supportive/headwind appears only on
the MACRO strip with the rule printed.

But nine findings put a wrong number, time, unit or contract under a label, and one structural gap blanks a dozen
panels:

1. **The DAILY charts and tape are shifted by 5.5 hours** — the store writes 1-minute bars as naive UTC, the UI reads them
   as IST (the tape says "18:05 IST" for a 23:35 IST bar; the session bands, the "Tue 03 Nov close 3,949.80" legend and the
   +3.26 % day change are all on the wrong clock).
2. **The health headline says GOLD-SPECIFIC when the stored DXY says DOLLAR-DRIVEN** (DXY −0.73 % w/w vs gold +0.67 %):
   the dollar gauge is permanently OFFLINE because `/db/gold/series` does not serve any Yahoo-bar- or ETF-backed series id.
3. That same gap blanks **GLD Δ in the WEEKLY table, the rupee and DXY-basket columns of the MONTHLY ladder, the KGX split
   (which prints "identity off — check the inputs"), five of six rows of "Gold in six currencies", USD/INR and ATR14 on
   MACRO** — while every one of those series sits in the store.
4. MACRO's **"DOLLAR INDEX (DXY)" tile shows 121.67, the FRED broad index (+0.28 % w/w, HEADWIND)**; the ICE DXY stored is
   101.445 and fell −0.73 % — opposite sign.
5. **Official-sector tables label ounces as "MOZ" and multiply by 31.1 to get "tonnes"** (USA 8,13,35,28,080 t); Brazil's
   row (5.5 bn "oz") is a scale defect in the stored IMF series.
6. **COT "released Fri 30 Oct 19:30 IST"** is the UTC instant printed as IST; the payload itself says Sat 31 Oct 01:00 IST.
7. **The Shanghai gauge change is $47.36/oz rendered as "+47.36 %"**.
8. **The COMEX spec card and roll calendar describe NOV-26** (first notice "5 d ago", last trade 25 Nov) under the DEC-26
   matched-month title.
9. **"next FOMC 2026-11-05 19:20"** is a Fed speech (Hammack); the next meeting on the same panel is 16 Dec.

Majors: the Shanghai hero compares SGE 4 Nov with LBMA 3 Nov (+$109 after a +3.5 % day, "7-hour gap" text), the India
ladder juxtaposes a live duty-paid price with a settlement-clock basis (+1.50 % next to numbers that give −1.72 %) and a
clock-error IBJA premium (−3.94 % vs the stored −0.71 %), the brief panel shows "bias — · confidence —" while the payload
carries neutral / 0.45, the BRF line never prints OK/WAIT because the health block looks up the MCX quote under a
different cache key, "all-history percentile" is a 160-report window, the fund-driver label "new shorts" describes a week
in which funds added 1,538 longs and 182 shorts, and the two CONTRACTS tables print different carry figures under the same
column heading. Details, both values and the code line for each, follow.

## 1. Re-derivations (all from stored rows, no publisher calls)

| What | Inputs (store) | Derived | On screen / payload | OK |
|---|---|---|---|---|
| Landed ₹/10 g | GCZ26 4,077.5 (23:40 IST) × INR=X 94.63 × 10 ÷ 31.1035 | 1,24,055 | `/health.fair.landed` 124,055; ph.ladder ₹1,24,037 (COMEX 4,076.9 at 23:41) | ✓ |
| Duty-paid | × 1.15 | 1,42,663 | 142,663 | ✓ |
| Basis % | settle 140,186 ÷ duty-paid at the 23:25–23:55 ref (3,942.8 × 94.74 → 138,111) − 1 | +1.50 % | +1.5 % everywhere | ✓ (clock caveat, F11) |
| Desk fair open | 140,186 + (4,078.7 − 3,942.8) × 35.55 + (94.63 − 94.74) × 1,480 | 1,44,849 | h.open ₹1,44,849, gap +₹4,663 (+3.33 %) | ✓ |
| COT MM net 27 Oct | 122,508 − 16,946 | 105,562 | 105,562 / +1,05,562 | ✓ |
| MM Δ w/w | 105,562 − (120,970 − 16,764) | +1,356 (+1.30 %) | +1,356, +1.3 % | ✓ |
| who did | chg_mm_long +1,538, chg_mm_short +182 | new 1,538 longs / new 182 shorts | same | ✓ |
| MM net in metal | 105,562 × 100 oz × 31.1035 g | 10.56 Moz · 328.3 t · $43.0 bn @ 4,074.6 | same | ✓ |
| Tue→Tue price | 4,074.6 / 4,142.6 − 1 | −1.64 % | −1.64 % | ✓ |
| DEC→FEB carry | 4,112.4 / 4,078.3 − 1; 57 d | +0.836 %, +5.35 %/yr | +0.84 %, +5.3 %/yr (HEALTH) / +5.4 %/yr (c.comex) | ✓ (rounding) |
| MCX DEC→FEB carry | 142,926 / 140,186 − 1; 63 d | +11.32 %/yr | +11.3 % | ✓ |
| GLD 30 stored points | 1,037.66 − 1,056.84 (23 Sep) | −19.18 t | −19.2 t | ✓ |
| GLD 1 m / YTD | − 1,055.70 (2 Oct) / − 1,070.56 (31 Dec) | −18.04 / −32.90 t | −18.0 / −32.9 t | ✓ |
| Trend | GC=F closes; 20 d avg 4,090.2; 200 d; 52-w high 5,318.4 | −0.28 % / −9.55 % / −23.31 % | same | ✓ |
| Real yield Δ W | 2.62 (2 Nov) − 2.66 (26 Oct) | −4 bp | −4 bp | ✓ |
| Shanghai Δ W | −1.55 − (−48.91) | +$47.36/oz | "+47.36 %" | ✗ unit (F7) |
| 1σ day | 25.82 ÷ √252 × 4,078.7; × 140,186 | 1.63 %, $66.3, ₹2,280 → ₹2,28,014/lot | same | ✓ |
| Accuracy log | 6 measured rows | mean 1,878 · median 1,360 · p90 3,518 · bias −743 · naive 1,467 | same | ✓ |
| Decomposition | gold_cot rows 27 Jan / 12 Nov 24 → 27 Oct | Δ long −20,813 / −81,153 … | same | ✓ |
| DXY W (for H2) | DX-Y.NYB 102.19 (28 Oct) → 101.445 (4 Nov) | −0.73 % → usd effect +0.73 ≥ 0.4 × 0.67 | gauge OFFLINE, headline GOLD-SPECIFIC | ✗ (F2) |

## 2. Findings

### Blockers

**F1 · DAILY d.24h / d.3day / d.tape — intraday timestamps are UTC rendered as IST (5.5 h shift).**
`/api/gold/bars?symbol=GC=F&interval=1m`: `bars[-1].ts = "2026-11-04T18:09:59"` (no offset) while the same payload's
`freshness.as_of = "2026-11-04T23:39:59+05:30"`; the tape prints "18:05 IST · 07:35 NY" for that bar. Cause:
`services/data-service/gold/ingest_yahoo.py:166` stores `ts` as naive UTC; `ui/lib/gold/sessions.ts:149-153` (`barMs`)
parses a naive string with `new Date(ts)` = browser-local, so `istMinutes`, `dayGroups` and the session bands all run 5.5 h
early. Consequences on screen: the legend "Tue 03 Nov close 3,949.80 ▲12.70 (+0.32 %)" and "Mon 02 Nov close 3,937.10"
disagree with the stored daily closes 3,940.4 / 3,969.6 (w.table shows −0.74 %); "Wed 04 Nov last ▲+3.26 %" vs +3.51 %
(w.table) and +3.40 % (strip). Screenshot `daily_P.png`. Fix: emit `ts` with `Z`/`+05:30` in `/bars` (gold.py:1914 route)
or parse naive strings as UTC in `barMs`.

**F2 · HEALTH h.verdict — "FIRM WEEK, GOLD-SPECIFIC" is produced without the dollar input; the stored DXY says DOLLAR-DRIVEN.**
Gauge `dollar` is `state: unavailable` (tile "— OFFLINE") because `fetch_series` asks `/db/gold/series` for `DXY_CLOSE`
(0 points, `published: true`) while `/db/gold/bars?symbol=DX-Y.NYB` holds 101.445 on 4 Nov and 102.19 on 28 Oct (−0.73 %
w/w). `routers/gold.py:1246-1290` sets `extras.usd_effect_pct` only from that series; `_driver_word` (gold.py:884-900)
then falls through to "GOLD-SPECIFIC". Rule H2 (usd share 0.4, same sign, |move| ≥ 0.5 %): +0.73 ≥ 0.27 → DOLLAR-DRIVEN.
API_CONTRACT §0 says an unavailable gauge adds no clause; here it decides the headline word (also echoed by WEI/BRF).
Evidence `health_W.json` verdict.clauses[0], `ds_bars_dxy.json`; screenshot `health_P.png`.

**F3 · Systemic — `/api/gold/series` serves no points for Yahoo-bar- and ETF-backed ids; a dozen panels are blank with the data in the store.**
`series_yahoo.json`: `COMEX_GC_FRONT, DXY_CLOSE, USDINR_CLOSE, GLD_TONNES, GVZ_CLOSE, WB_GOLD_MONTHLY_AVG` → `n: 0,
published: true, freshness.state: unavailable`. `services/data-service/gold/reads.py:series()` reads only `gold_series`
via `pit.asof_series`; the Yahoo closes live in `gold_daily_bars` (`SYMBOL_BY_SERIES` is used only by `reads.bars`) and GLD in
`gold_etf_holdings`. Panels affected tonight: h.gauges DOLLAR (OFFLINE); w.table "GLD Δ t" all "—" (GLD −1.14 t on 2 Nov,
−2.85 t on 3 Nov stored); m.ladder "LANDED ₹/10 G" and "IN THE DXY BASKET" all "—"; mc.kgx pure/USD effect "—" with the
panel's own red text "identity off by more than 0.02 pp — check the inputs" and "rebased 1-y line appears once
COMEX_GC_FRONT and DXY_CLOSE have daily history"; mc.ccy INR/EUR/JPY/GBP/CNY "—"; mc.drivers USD/INR "—"; mc.move ATR14 ₹
"—"; mc.context gsr null; the MACRO scatter. Fix in data-service: route catalog ids with a Yahoo symbol / ETF fund through
their tables inside `reads.series` (or in ui-api `fetch_series`).

**F4 · MACRO mc.drivers — "DOLLAR INDEX (DXY) 121.67 · 1w +0.28 % · HEADWIND" is FRED DTWEXBGS, not DXY.**
`macro_W.json` driver `dxy`: `value 121.6656, series_id FRED_DTWEXBGS, report_date 2026-10-30, d1w +0.285, tag headwind`.
`gold.py:3422` declares the row `("dxy", "Dollar index (DXY)", "DXY_CLOSE", "FRED_DTWEXBGS", …)` and falls back to the broad
index (`gold.py:3739`) when F3 empties `DXY_CLOSE`. The ICE DXY stored is 101.445 and fell −0.73 % on the week: the number,
the sign of the change and the tag are wrong for the label. Screenshot `macro_P.png`.

**F5 · MONTHLY m.official / PHYSICAL ph.official — ounces labelled "MOZ", tonnes wrong by 10⁶, Brazil off-scale.**
`flows.json official[]`: USA `oz_mn 261,499,000, tonnes 8,133,528,079.7`; CHN `77,470,000 / 2,409,586,347.7`; BRA
`5,544,278,723 / 172,446,344,633.5`. Catalog unit for every `IMF_GOLD_OZ_*` is `oz`; `gold.py:3253-3254` puts the raw value
under `oz_mn` and computes `tonnes = value × TONNES_PER_MOZ`. Screen: "USA 26,14,99,000.00 MOZ · 8,13,35,28,080 T";
"PBOC LATEST 7,74,70,000.00 Moz". Correct: USA 261.5 Moz = 8,133 t; CHN 77.47 Moz = 2,410 t. BRA's stored row
(5.54 bn "oz" ≈ 172 kt) is a scale defect in the ingest of `IMF_GOLD_OZ_BRA` (Brazil holds ≈ 130 t) — the Δ 12 m
`5,539,612,261` confirms the jump. Screenshots `monthly_P.png`, `physical_P.png`.

**F6 · POSITIONING p.hero — "released Fri 30 Oct 19:30 IST" is the UTC instant printed as IST.**
`gold_cot.release_at = "2026-10-30T19:30:00"` (naive UTC; Fri 15:30 ET). `cot.json latest.release_ist = "Sat 31 Oct 01:00 IST"`
is right; `ui/components/gold/PositioningView.tsx:113` prints `istLabel(c.latest.release_at, true)` instead. The HEALTH
positioning tile's lag chip uses the same field (`release_at`) for its age. Screenshot `positioning_P.png`.

**F7 · HEALTH h.gauges SHANGHAI PREMIUM — "▲+47.36 % W" is $47.36/oz.**
`health_W.json` gauge `shanghai`: `value −1.55, unit "$/oz", change 47.36` (= −1.55 − (−48.91) on 27 Oct, in $/oz).
`HealthView.tsx:55-61 gaugeChange()` has no `$/oz` branch and falls to `fmtSignedPctSp`. The TREND tile sends a % change
under the same unit, so the server's `change` semantics differ per gauge; add a `change_unit` or branch on `key`.

**F8 · CONTRACTS c.spec + c.roll — the COMEX DES card and the roll calendar describe NOV-26 under the DEC-26 matched month.**
`contracts_comex.json comex_spec`: `mmy 202611, first_notice 2026-10-30, last_trade 2026-11-25, ref_price 4051.3` →
screen "FIRST NOTICE Fri 30 Oct · 5 d ago · LAST TRADE Wed 25 Nov"; c.roll "Wed 25 Nov COMEX GC last trade · in 21 d".
The page's matched month is GCZ26 (DEC-26: FND 30 Nov, LTD 29 Dec). `gold.py:2922-2929` picks the first PRF row with
`last_trd ≥ today` instead of the row whose `mat_date` matches `comex_matched`. Also `margin_history` is 36 rows all dated
2026-11-04 with `25.0` entries interleaved (per-contract rows, not a history). Screenshot `contracts_P.png`.

**F9 · MACRO mc.fed — "next FOMC 2026-11-05 19:20 IN SESSION" is "FOMC Member Hammack Speaks".**
`macro_W.json fed.next_fomc_ist = "2026-11-05 19:20"`; the calendar row at that time is a speech (`kind` contains "FOMC");
the meetings list on the same panel starts Wed 16 Dec. `gold.py:3660-3677` selects the first event whose kind contains
"FOMC". Wrong date under the label; `after_mcx_close` is derived from it too.

### Majors

**F10 · PHYSICAL ph.shanghai — hero premium +$109.0 (2.77 %) pairs SGE Wed 04 Nov with LBMA PM Tue 03 Nov.**
`premiums.json shanghai`: `sge_pm_cny_g 865.47 (ts_sge 2026-11-04), london_pm_usd 3,936.65 (ts_ref 2026-11-03)`; gold
rose +3.5 % on 4 Nov, so the "premium" is mostly the rally; the panel text still says "a 7-hour gap to the LBMA PM".
`gold.py:3136-3141` takes the latest SGE and the latest LBMA independently. The stored same-day series
(`SHANGHAI_PREMIUM_USD` 3 Nov = −1.55) is what HEALTH shows → the same metric reads +109.0 and −1.55 on two sub-views.
Fix: pair on `report_date`, or show the SGE-vs-COMEX-at-14:15-Beijing leg when LBMA lags.

**F11 · PHYSICAL ph.ladder and CONTRACTS c.mcx footer — settlement-clock basis and a clock-error IBJA premium beside live numbers.**
ph.ladder: duty-paid ₹1,42,642 (23:41 IST) → MCX settle ₹1,40,186 "MCX basis +1.50 %": the two printed numbers give
−1.72 %; +1.50 % is settle ÷ duty-paid at the 3 Nov 23:25–23:55 reference (138,111, `fair.json model`). c.mcx prints
"basis vs duty-paid landed +1.50 % · duty-paid ₹1,42,695" with the same contradiction. "IBJA premium vs duty-paid −3.94 %"
= IBJA 3 Nov PM fix ÷ tonight's duty-paid × 999/995 — the stored same-day `INDIA_PREMIUM_PCT` 3 Nov is −0.71 %, which the
HEALTH gauge carries (`ibja_premium_pct −0.71`). The panel's own clock note admits this is clock error; the fix is to
compute the ladder at one clock (the settlement reference for settle/IBJA, the live one for the live pair) and label which.
Related: the HEALTH gauge `india_basis` cites `MCX_BASIS_PCT` dated 2026-11-03 with value 1.50 while the stored row for
that date is 1.58 (`ds_series_health.json`; drawn as 1.58 on ph.india) — same series id and date, two values.

**F12 · HEALTH h.brief — "bias — · confidence —" while the payload has them.**
`brief.json`: `available true, bias "neutral", confidence 0.45, label "automated brief, confidence 0.45"`, and
`doc.synthesis.{bias, confidence}`. `HealthView.tsx:184-186` reads `doc.bias` / `doc.confidence` (top level of `doc`),
which do not exist. Overview `brief` carries the same values.

**F13 · HEALTH h.open vs BRF/WEI lines — the desk shows "DON'T CHASE — WAIT" on MCX ₹1,43,249 while `health.fair.mcx_live` is null and `brf_line` prints no verdict.**
`health_W.json fair`: `mcx_live null, desk_verdict_state NEED_PRICE` (re-fetched at 00:01: `AWAITING_OPEN`); `fair.json`
and `overview.quote`: ICICI Breeze LTP 143,250 at 23:50, verdict WAIT. Cause: `fair_block` reads the quote cache under
`f"quote:{code}:{expiry or 'front'}"` with `expiry=None` (`gold.py:704`) while the overview requests the quote with the
selected expiry (`gold.py:4243` → `mcx.py:393` key `quote:GOLD:2026-12-04`). Two desk states on one page.

**F14 · POSITIONING p.crowd "ALL-HISTORY PERCENTILE 26" / p.hero "14th pct of history" — a 160-report window labelled as history.**
`cot.json crowd.percentile_all 26.2, n_reports 160`; `open_interest.pct_rank 13.8`. data-service's own summary over the
full store (1986→): `percentile_all 50.0`, `pct_rank 19.5` (`ds_cot.json`). Either rename ("3-y") or compute on the full
panel.

**F15 · HEALTH H3 / POSITIONING p.hero / WEEKLY w.whodid — fund-driver label "new shorts" for a week of +1,538 longs, +182 shorts.**
`cot_metrics.py:63-65`: on a down week with `dl ≥ 0`, any `ds > 0` returns "new shorts" regardless of size. The word is in
the verdict sentence ("funds net 105,562 (+1.3 % w/w, new shorts)"), the hero and WEEKLY. The G-STUDY rule is kept
verbatim by contract (§7.3), but as printed it misdescribes the week; at minimum the hero should carry the magnitudes
beside the word (it does) and the verdict should not. Flagged for the rule's owner.

**F16 · CONTRACTS c.selector "GOLD EXPIRIES · OI LADDER" vs c.mcx chain — the same "CARRY % P.A." heading, two conventions.**
Ladder: DEC-26 +11.3 %, FEB-27 +6.1 %, APR-27 +9.6 %, JUN-27 +8.4 %, AUG-27 +10.3 % (carry to the NEXT month, printed on
the earlier row: `contracts_mcx.json expiries[].carry_pct`). Chain: FEB-27 +11.3 %, APR-27 +8.8 %, JUN-27 +9.2 %,
AUG-27 +9.1 % (vs the front, `curve_mcx.json annualised_carry_pct`). Both arithmetically right; on one page the FEB-27 row
reads +6.1 % and +11.3 % under the same label (PLAN §f.6).

**F17 · POSITIONING p.asia — three "no verdict — not published" rows for ids that are not in the catalog, while SHFE OI is stored.**
Panel asks `SGE_AUTD_OI, SGE_AUTD_DIRECTION, SHFE_AU_FRONT_OI` (`PositioningView.tsx:54`); none has a catalog row
(`catalog.json` has `SHFE_DAILY`, `SGE_DAILY`, `SGE_DELIVERY_RATIO`), and `gold_asia_daily` holds SHFE au2612 OI 184,422
(−927) on 30 Oct. The gate works; the ids are wrong, so the brief's "who is long/short in Shanghai" is empty by mistake,
not by verdict.

### Minors

- **M1 · h.gauges REAL YIELD** tile shows no Δ (`change: null`, only `change_bp −4` in extras) while the verdict quotes
  "real yield −4 bp"; INDIA BASIS and CURVE/ROLL tiles likewise carry no window change.
- **M2 · en-IN grouping vs en-US on one page**: "+1,05,562" (strip, tiles, learn table "1,05,562") vs "105,562" (verdict,
  clause text); OI "3,96,810" vs CFTC's 396,810.
- **M3 · h.verdict lag chip says STALE** (`health_P.png`) while `freshness.state = "delayed"` (COT 4.95 d, max_age 9).
- **M4 · n = 1 statistics**: p.daily.comex "VOLUME VS 20-D AVG 1.00×", ph.otc "20-d avg 3,141" (one CME day stored); d.quadrant
  COMEX "Tue 03 Nov: flat · ΔOI —" prints a quadrant word with ΔOI unknown. Expected to self-heal after the CME backfill, but
  the word/ratio should be "—" until then.
- **M5 · ph.otc "$964.2 bn/day"**: catalog unit is "USD bn" for "weekly turnover, gold (12-wk MA)"; "/day" is a UI suffix.
- **M6 · GPR monthly percentile**: MACRO `gpr_pct_m 85` vs MONTHLY m.liquidity "43th pct" for the same 150.52 (and "93th/43th").
- **M7 · h.events / mc.calendar** list events already past today (Wed 04 Nov 03:00 API bulletin at 23:53) under "next 7 days".
- **M8 · w.table COMEX VOL 1,72,512 on both Mon 02 and Tue 03 Nov** — the stored `gold_daily_bars` rows carry the same
  volume (Yahoo artefact); worth a dedupe check in the daily ingest.
- **M9 · w.whodid "released Fri 30 Oct" (ET date) beside "next Sat 07 Nov 02:00 IST"** — mixed conventions in one line.
- **M10 · ph.ladder MCX step timestamp "—"** (`ts` is the label "Tue 03 Nov settlement", not a date).
- **M11 · premiums.india.history** carries basis 1.262 forward to 02 Nov (no stored row that day) and plots it.
- **M12 · ds vs ui decomposition anchors**: data-service "since the high" uses the Tuesday-price high (10 Mar, Δ MM net
  +7,163); ui-api uses the daily-close high (27 Jan, −12,597). The page is self-consistent; the Saturday digest will disagree.
- **M13 · c.comex "+5.4 %/yr" vs HEALTH "+5.3 %/yr"** for the same 5.354 (one rounds the stored 5.354, the other `:+.1f` of 5.35).
- **M14 · mc.health** prints raw keys ("beta_real_yield_per_100bp −1,440.00") without units.
- **M15 · trend tile "Wed 04 Nov $4,078.70"** is today's partial Globex day stored as a daily bar (COMEX day closes 03:30 IST);
  w.table lists it under "CLOSE".

## 3. "Not stored yet" / "no verdict" inventory tonight

| Panel | Text | Expected? |
|---|---|---|
| d.sge | NO VERDICT — NOT PUBLISHED · SGE 5-minute bars stored from the day the asia job starts | expected (no SGE intraday yet) — but the message is a "not stored yet", not a verdict gate |
| p.asia ×3 | no verdict — not published (SGE_AUTD_OI, SGE_AUTD_DIRECTION, SHFE_AU_FRONT_OI) | **bug** (F17: ids not in the catalog; SHFE OI is stored) |
| p.mcx.category | LINK-ONLY, dormant until O-8 | expected |
| ph.comex.stocks | LINK-ONLY until O-2 | expected |
| p.daily.comex Δ —, roll ratio —, w.table COMEX OI Δ — | one CME day stored | expected (backfill tomorrow; C7/O-2 for per-month OI) |
| m.physical INDIA GOLD IMPORTS —, SWISS EXPORTS TO INDIA — | catalog rows exist (PUBLISH-CONTEXT) but `/db/gold/series` has no points | **not stored yet** — not listed in the brief's pending items; owner question |
| h.gauges DOLLAR — OFFLINE | DX-Y.NYB stored | **bug** (F2/F3) |
| mc.kgx, mc.ccy, m.ladder ₹/DXY columns, mc.drivers USD/INR, mc.move ATR14 | stored | **bug** (F3) |
| h.brief bias — · confidence — | stored | **bug** (F12) |
| mc.fed zq [] | ZQ_FRONT not stored | expected (not in the brief) |
| c.mcx margins for JUN-27+ "indicative constant" | Zerodha file lists three months | expected, labelled |
| strip "— settle —" and "NO DATA" | bulletin settlement (O-2), gold-api cross-check null | expected, labelled |
| WGC weekly flows / balance sheet / India ETF tonnes, LBMA PM | rows ARE stored (to 23 Oct; balance 70 rows) and shown "PROVISIONAL until O-1" | contrary to the brief's "empty until O-1"; displayed with attribution — owner to confirm O-1 covers display |

## 4. What works (verified)

- Fair value, landed, duty-paid, basis, desk gap, per-lot arithmetic, chase-limit conversions — all re-derived exactly.
- COT: net, Δ, who-did, Moz/t/$bn, Tue→Tue price, trader counts, concentration, micro gold, decomposition vs raw rows,
  next release "Sat 07 Nov 02:00 IST" (holiday-aware, post-DST).
- Carry DEC→FEB (both exchanges), ETF d/d, 5 d, 30-point, 1 m, YTD; trend stats; real-yield Δ; 1σ sizing; accuracy log.
- Every badge on screen equals the catalog verdict's badge; `signal` appears nowhere; no composite; verdict suffix present;
  context tiles neutral (arrows only); supportive/headwind only on MACRO with the rule printed; sources and dates on every tile.
- No console errors, no 4xx/5xx API responses during the 18 page loads.

## 5. Questions for the owner

1. INDIA_GOLD_IMPORTS_USD_BN and SWISS_GOLD_EXPORT_IN_KG have PUBLISH-CONTEXT catalog rows but no stored points — is the
   ingest scheduled, or should the m.physical tiles say "not stored yet"?
2. WGC weekly flows, the balance sheet and the LBMA PM are stored and displayed "PROVISIONAL until O-1"; the brief says they
   are empty until O-1 — which is the intended state tonight?
3. The fund-driver rule (F15) is the G-STUDY §5.2 wording; do you want magnitude-aware wording, or the word dropped from
   the verdict sentence?
4. The health "india basis" shows the desk's settlement-reference basis (1.50 %) under the series id MCX_BASIS_PCT whose
   stored row is 1.58 % (daily-close reference). Which reference is the series?
