# G-EDU — the gold education layer: report (26 Oct 2026)

Agent G-EDU of the SuryaDhana GOLD program. Brief: a zero-to-professional curriculum for the LEARN view, per-metric
tooltips, a glossary, and "how to read this panel" micro-copy for every gold panel, existing and proposed. Read-only on
the repo; outputs in this folder only. Written 03:30–06:30 IST on a trading Monday; no live service was touched beyond
two GET calls to ui-api endpoints that never reach the broker (`/api/mcx/overlay`, `/api/mcx/specs`).

## 0. Phase-2 addendum (26 Oct 2026, B5-LEARN-DOCS) — what changed after this report was written

The body below is the research report as written at 06:30; it is kept verbatim. The LEARN assets were then reworked
against `PLAN.md` (the build plan) and `SOURCES.md` (the synthesis), and the following supersedes the matching lines below:

- **Finding 1 (the 18 % premium) is resolved.** The duty is **15 % (BCD 10 % + AIDC 5 %) since 13 May 2026, Notification
  16/2026-Customs** (SOURCES.md F9; the owner confirms the primary at CBIC, PLAN O-3). 18.0 % = 0.995 × 1.15 × 1.031 − 1:
  purity × duty × a 3.1 % basis. CURRICULUM §0, §2.6, §5.8, Appendices A and C now say so; the "6 % since 24 Jul 2024" lines
  are gone (`validate_learn.py` check 6 refuses them).
- **Part 8 renamed** to the PLAN §a panel ids (Appendix B of the plan): every `8.x.y` heading names its `h.* / d.* / w.* /
  m.* / p.* / ph.* / mc.* / c.*` id or the page that keeps the panel (MCXG / WEI / BRF / CMDT / ECO); §8.0 is the map;
  **§8.4** is the health-verdict rule table (every clause of `h.verdict` with its threshold; it ends "describes, does not
  predict"). Evidence chips use the four badges of PLAN §f (`signal` / `context` / `arithmetic` / `heuristic`); the
  "consider half size" line is gone (SOURCES.md disagreement 14).
- **Appendix C** (evidence ledger) now defers to SOURCES.md §11 and `reports/gold_program/FINDINGS.md`; **Appendix E**
  (what is not free and where to click) and **Appendix F** (the Bloomberg function map → free panels) were added.
- **Counts:** glossary 129 → **151** terms (added per PLAN §e: GOLDTEN, AIDC, due date rate, EFP price vs volume,
  first notice / last trading day, registered / eligible / pledged, Au(T+D) direction, KGX rupee leg, point-in-time, the
  four badges, customs duty; "settlement by session" merged from the UI copy on 4 Nov); tooltips 93 → **260** (204 payload
  fields of the PLAN §d contract that a view renders — on 4 Nov 2026 (wave 1b) the 69 field keys B4B's views had added in
  `ui/lib/gold/tooltips.json` were merged here verbatim so G-EDU is the superset, and 20 keys no view references were
  retired and are listed in `build_glossary.py` `RETIRED_FIELD_KEYS` — plus 56 panel ids of PLAN §a, listed under
  `panels`; `validate_learn.py` check 9 fails on a field key no `ui/` source names, and `ui/components/__tests__/
  gold_views.check.ts` fails when the UI copy differs from this folder, so the two files are equal key for key). `build_glossary.py` generates both files; `validate_learn.py` checks cross-references, lengths,
  every PLAN panel id ↔ tooltip, the Part 8 ids, the duty wording and the labelling rules, and asserts that `CURRICULUM.md`
  equals the concatenation of `parts/*.md` (the parts are the source; `--write` rebuilds everything).
- **§2's "Verdict for the app" column is superseded** by `SOURCES.md` (140 entries, one verdict each): in particular the
  CME **FTP** files are PUBLISH-CORE/CONTEXT (G-CME found the server), the GLD XLSX endpoint is PUBLISH-CORE display-only
  with attribution (four agents verified it; the CSV→PDF path this agent saw is dead), the SGE daily table and benchmark
  JSON are fetchable once a day, and IBJA is PUBLISH-CORE display-only pending the owner's terms decision (O-1).
- Open questions 1 (duty), 2 (panel names) and 8 (ship with the chip) are closed; 3–7 are PLAN owner actions O-9, O-8,
  O-1, O-11 and O-2.

## 1. Verdict

**PUBLISH the LEARN layer; do not publish any new gold *number* without its tooltip and evidence chip.** The curriculum
(`CURRICULUM.md`), `glossary.json` (129 terms), `tooltips.json` (93 fields) and the panel micro-copy (CURRICULUM Part 8) are ready to ship as
text. The education layer is the one part of the gold program that is useful on day one regardless of which feeds the
other agents land, because it tells the owner what he is actually long when he buys an MCX lot: gold, the rupee, a duty
regime and the crowd's position.

Three honesty findings came out of writing it with live numbers, and they outrank the education content:

1. **The MCX premium over landed COMEX is 18.0% (app overlay, 26 Oct 2026 05:49 IST) and cannot be explained by the 6%
   duty this document knows (in force since 24 Jul 2024).** Either the duty was raised after June 2026 (a rupee at 94.93
   is exactly when India has done so before) or the local premium is extreme. The gold program must carry the customs
   duty as a **dated, sourced input** (CBIC notification + fortnightly tariff value), never a constant. Until it does,
   every "premium" panel is unreadable. (§2.6 of the curriculum.)
2. **The ₹300 chase limit is unsupported.** The accuracy log has 3 scored days: misses +₹1,090 / −₹3,518 / −₹2,880; the
   model's mean miss ₹2,496 vs naive ₹2,147; 0% within ₹300. Three days prove nothing either way, but the verdict panel
   should wear a HEURISTIC chip until ≥ 20 days say otherwise, and the 15 Oct row looks like the "settlement-before-last"
   baseline case the desk itself warns about: flag such rows.
3. **Position sizing arithmetic says GOLD and even GOLDM are oversized for a typical retail risk budget**: at 1% risk and
   a 1.5-ATR stop, one GOLDM lot needs ≈ ₹26 lakh of account, one GOLD lot ≈ ₹2.6 crore. The paper ticket should print
   `max_lots_at_risk_pct` next to `indicative_margin`; the two numbers disagree by an order of magnitude and that
   disagreement is the most useful thing the ticket can teach. (§7.6.)

## 2. Source verification (live, 26 Oct 2026, 03:40–05:55 IST; details in `verify_results.json`, `verify_pass2.json`)

52 probes, polite (1.5 s apart, browser-like UA; plain UA for FRED, which stalls browser UAs). 42 answered 200.

| Source | URL | Status / latency | What came back | Access | Verdict for the app |
|---|---|---|---|---|---|
| CFTC COT explanatory notes (legacy, disaggregated) | cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes, …/DisaggregatedExplanatoryNotes | 200 / 0.2–0.9 s | definitions: reporting levels, 70–90% of OI reported; the four disaggregated categories | FREE | LINK-ONLY (reference text; quoted in LEARN) |
| CFTC COT release schedule | …/ReleaseSchedule/index.htm | 200 / 0.2 s | page OK; dates rendered client-side (no 2026 dates in HTML) | FREE | LINK-ONLY; hard-code holiday shifts |
| CFTC legacy short format, COMEX | cftc.gov/dea/futures/deacmxsf.htm | 200 / 0.2 s | GOLD block as of 10/20/26: OI 402,279; NC 237,142/37,277/54,199; Comm 59,531/295,113; NR 51,407/15,690; changes, %OI, trader counts | FREE | PUBLISH-CORE (weekly; the text block is the teaching artefact) |
| CFTC disaggregated long format, "Other" (metals) | cftc.gov/dea/futures/other_lf.htm | 200 / 0.3 s | gold present (Other group) | FREE | PUBLISH-CORE |
| CFTC Socrata API, disaggregated futures-only | publicreporting.cftc.gov/resource/72hh-3qpy.json | 200 / 1.3 s | 186 fields; latest report_date 2026-10-20; GOLD row: PM 19,715/34,498; SD 17,737/238,536/22,079; MM 120,970/16,764/38,634; OR 116,172/20,513/15,565; changes; 288 traders; conc 20.4/37.8 | FREE (optional app token) | PUBLISH-CORE (ingest weekly Saturday 03:00 IST) |
| CFTC Socrata, disaggregated combined | …/kh3c-gbw2.json | 200 / 1.2 s | OI 532,443 (delta-adjusted options included) | FREE | PUBLISH-CONTEXT |
| CFTC Socrata, legacy futures-only | …/6dca-aqww.json | 200 / 1.2 s | 133 fields; matches the HTML block | FREE | PUBLISH-CORE |
| CFTC history zip (disaggregated 2026) | cftc.gov/files/dea/history/fut_disagg_txt_2026.zip | 200 (HEAD) / 0.2 s | 2.03 MB, modified 23 Oct 2026 | FREE | ingest once per year for history |
| CFTC Bank Participation Report | cftc.gov/MarketReports/BankParticipationReports | 200 / 0.8 s | "publishes monthly on the first Friday after 3:30 ET… first Tuesday's data" | FREE | PUBLISH-CONTEXT (monthly) |
| CME gold specs / options specs / FedWatch | cmegroup.com/… | **403** / 0.2 s | blocked for non-browser clients | FREE in browser | LINK-ONLY |
| CME warehouse stocks XLS | cmegroup.com/delivery_reports/Gold_Stocks.xls | **403** | blocked | FREE in browser | LINK-ONLY unless fetched via a browser-session job |
| LBMA precious metal prices | lbma.org.uk/prices-and-data/precious-metal-prices | 200 / 1.1 s | "data… moved to our MyLBMA Portal… need the relevant licence from IBA" | PAID (IBA licence) | LINK-ONLY; never scrape |
| LBMA trade data (LBMA-i) | …/lbma-trade-data | 200 / 1.6 s | weekly turnover shown in page text ("period ending 16 October 2026, Gold: $964…"); daily T+1 licensed via Nasdaq/Bloomberg/LSEG | FREE (weekly summary) | PUBLISH-CONTEXT (weekly) |
| LBMA London vault holdings | …/london-vault-holdings-data | 200 / 0.8 s | "end September 2026… 9,821 tonnes (+1.96% m/m), $1.3 trillion, ≈785,690 bars; silver 28,985 t" | FREE | PUBLISH-CONTEXT (monthly) |
| LBMA about Good Delivery | lbma.org.uk/good-delivery/about-good-delivery | 200 / 0.5 s | page OK (text extraction found no numbers; the rules PDF is separate) | FREE | LINK-ONLY |
| LBMA GD list URL guess | …/gold-good-delivery-list | **404** | wrong URL (my guess); not cited | — | — |
| WGC ETF holdings & flows | gold.org/goldhub/data/gold-etfs-holdings-and-flows | 200 / 0.5 s | "updated weekly and monthly… xlsx monthly… Gold ETF Flows: September 2026" | FREE-REGISTRATION (xlsx) | PUBLISH-CONTEXT |
| WGC central-bank reserves | …/gold-reserves-by-country | 200 / 0.4 s | updated 6 Oct 2026; IMF IFS based; dashboard data as of 30 Jun 2026 | FREE-REGISTRATION | PUBLISH-CONTEXT (monthly) |
| WGC Gold Demand Trends / gold prices | …/research/gold-demand-trends, …/data/gold-prices | 200 / 0.4 s | quarterly report page; price page | FREE-REGISTRATION | LINK-ONLY |
| FRED DFII10 / T10YIE / DGS10 / DTWEXBGS (CSV) | fred.stlouisfed.org/graph/fredgraph.csv?id=… | 200 / 0.5–1.0 s (plain UA) | DFII10 2.64 (2026-10-22); T10YIE 2.34 (10-23); DGS10 4.96 (10-22); DTWEXBGS 121.40 (10-16) | FREE (no key for CSV; API key `FRED_API_KEY` **not set** in .env) | PUBLISH-CORE (DFII10 already); add T10YIE at zero cost |
| US Treasury real yield curve CSV | home.treasury.gov/…/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve | 200 / 0.8 s | 10 YR 2.66 on 10/23/2026 (one day fresher than FRED) | FREE | PUBLISH-CORE (already) |
| SPDR GLD page / archive CSV | spdrgoldshares.com/usa/ ; …/GLD_US_archive_EN.csv | 200 / 0.5 s ; 200 but **PDF** (697 KB, `%PDF-1.5`) | page OK; the CSV endpoint now serves a PDF (confirms the project memory note) | FREE (page) | LINK-ONLY until a CSV/JSON endpoint is found; check terms |
| iShares IAU | ishares.com/us/products/239561/… | 200 / 1.2 s | 1.6 MB JS page | FREE | LINK-ONLY |
| SGE delayed quotes / benchmark | en.sge.com.cn/data_DelayedQuotes, …/data_BenchmarkPrice | 200 / 1.0 s | tables present but **all values 0.0 server-side** (JS-filled) | UNVERIFIED as feed | LINK-ONLY (open question: find the JSON the page calls, in a browser) |
| SHFE English | shfe.com.cn/eng/ | 200 / 7.0 s | slow; page OK | FREE | LINK-ONLY |
| MCX product / bhavcopy pages | mcxindia.com/… | **403** "Access Denied" | blocks non-browser clients (known) | FREE in browser | LINK-ONLY; MCX history must come via browser job or Breeze |
| IBJA rates | ibjarates.com | 200 / 0.5 s | "999 Purity 14163 (1 Gram) 995 Purity 14106… 916 12973… AM/PM: Rates will be uploaded soon" | FREE (terms unknown) | PUBLISH-CONTEXT once terms read (open question) |
| IBJA association site | ibja.co | 200 / 1.7 s | page OK | FREE | LINK-ONLY |
| RBI WSS | rbi.org.in/Scripts/WSSView.aspx | 200 / 0.4 s | page OK (tables are per-issue downloads) | FREE | PUBLISH-CONTEXT (weekly $ value of gold reserves) |
| FBIL | fbil.org.in | 200 / 0.3 s | landing page (1.5 KB; rates behind the site's own pages) | FREE | LINK-ONLY (already linked) |
| ICICI security master | directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip | 200 / 0.3 s | 3.0 MB zip, modified 23 Oct 2026 01:58 UTC | FREE | PUBLISH-CORE (already the app's MCX baseline) |
| DGCI&S Tradestat | tradestat.commerce.gov.in | 200 / 0.4 s | interactive site (no-back script) | FREE in browser | LINK-ONLY |
| AMFI | amfiindia.com | 200 / 0.6 s | landing | FREE | LINK-ONLY (monthly gold-ETF AUM) |
| Kitco gold charts / terms | kitco.com/charts/gold ; kitco.com/terms-of-use | 200 / 0.6 s | terms: "personal, non-commercial use only… copying, re-selling… redistributing… strictly prohibited" | FREE to view | **LINK-ONLY** (never embed or scrape; build the 24-h chart from the app's own bars) |
| Yahoo chart API (GC=F, GCZ26, INR=X, SI=F, ^GVZ, GLD, GOLDBEES.NS) | query1/query2.finance.yahoo.com/v8/finance/chart/… | **429** on every attempt (pass 1 and pass 2 after a 20 s pause) | rate-limited for this machine's IP (the app's own pollers share it); the app's cache still served GCZ26 $4,004.2 at 05:39 IST | FREE, unofficial, rate-limited | PUBLISH-CORE **only through the app's cached fetcher**; no second poller |
| ui-api `/api/mcx/overlay`, `/api/mcx/specs` (local GET) | 127.0.0.1:8010 | 200 | COMEX GCZ26 4,004.2; USD/INR 94.93; landed ₹1,22,211; fair ₹1,44,228; implied premium 18.02%; settlement ₹1,46,079 (22 Oct); specs + OI for 4 contracts | — | (the app's own numbers, used for worked examples) |
| SSRN (Erb–Harvey 2013; Baur–Lucey 2010) | papers.ssrn.com | **403** (Cloudflare "Just a moment") | not retrievable from this machine | FREE in browser | cited as standard references, marked not live-verified |
| Fed FEDS Notes index | federalreserve.gov/econres/notes/feds-notes/ | 200 / 0.7 s | index only; no specific note cited | FREE | not used |

Not verified at all (stated as such in the curriculum): CBIC current duty notification; ICICI's tender cut-off date for
MCX GOLD; MCX participant-wise OI (whether it exists); GOFO discontinuation page; CME 1-oz contract details; WGC annual
central-bank totals (from memory to June 2026).

## 3. Findings

**F1 — 18% implied premium (see §1.1).** Reproduced from the overlay: landed ₹1,22,211 → ×0.995 → ×1.06 = ₹1,28,896 vs
fair ₹1,44,228: an 11.9% residual over 6% duty. IBJA's 999 board (₹1,41,630/10 g) sits 15.9% over landed — the same
anomaly in the spot market, so it is not a Dec-contract artefact. Owner/G-INDIA action: fetch the current BCD + AIDC and
tariff value; store `duty_rate` with a date; recompute `implied_premium_pct` net of duty as `local_premium_pct`.

**F2 — Chase limit unsupported (see §1.2).** Keep the accuracy log on the page, add the HEURISTIC chip to the verdict,
flag stale-baseline rows, and re-decide the limit at 20 days. The curriculum's §8.1.1 copy says this verbatim.

**F3 — Yahoo rate-limits this machine (429).** Every direct chart call failed in both passes while the app's own cache
had fresh data. Any new gold panel must read Yahoo through `gold_preopen._yahoo_bars_cached` (stale-while-revalidate,
single-flight), never a second poller; COT, FRED, LBMA and WGC do not have this problem.

**F4 — Bot-blocked publishers: CME (403), MCX (403), SGE (JS-only).** These three hold the daily data the owner asked for
(COMEX OI/warehouse stocks, MCX bhavcopy OI, SGE premium). Options: a scheduled browser-session job (the project already
has a Playwright-based audit harness), the broker (Breeze historical works for MCX 1-minute bars; it can build daily OHLC
but not OI history unless the quote endpoint is fixed), or the CFTC's weekly total OI as the free fallback for COMEX.

**F5 — LBMA price data is licensed.** The LBMA Gold Price tables need an IBA licence (verified). The *fix* belongs in the
app as a time marker on the chart (16:00 / 20:30 IST on GMT), not as a scraped number.

**F6 — Kitco: link only.** Terms prohibit redistribution; the owner's "include like kitco.com/charts/gold" is met by
building the same 24-hour session-shaded chart from the app's own bars (CHRT already does candles for NSE).

**F7 — GLD CSV → PDF.** The `GLD_US_archive_EN.csv` endpoint now returns a PDF. The daily tonnes figure is on the page;
terms unread. Until a legal machine-readable source exists, WGC's weekly global flows are the ETF panel's backbone.

**F8 — COT is free, rich and fast.** Socrata JSON in 1.3 s with 186 fields, back to 2006 via yearly zips; the single best
free dataset in the program and the one the owner named first. A weekly ingest (Saturday 03:00 IST) into DuckDB
`gold_cot_disagg` (report_date, 25 fields for GOLD and MICRO GOLD) is the first gold table to build; a 160-week sample is
in `cot_gold_mm_history.csv` here.

**F9 — Repetition map (where the same gold number appears today).** COMEX gold: WEI row (GC=F), CMDT board (GC=F), Pre-Open
model (GCZ26), MCXG overlay (GCZ26) — four places, two symbols. USD/INR: WEI, Pre-Open, MCXG. Implied premium: Pre-Open
and MCXG. Real yield: Pre-Open only (good). Recommendation: one **GOLD health strip** (five numbers, §0) rendered as a
shared component on CMDT, MCXG and BRF, and the WEI/CMDT rows keep only their tooltip naming the symbol. Any new agent
panel that re-plots COMEX or USD/INR is a defect.

**F10 — No gold history anywhere.** Everything is fetched live; the owner's "weeks, days and months" cannot be shown
until series are stored. Minimum tables: `gold_cot_disagg` (weekly), `gold_mcx_daily` (contract, OHLC, settle, OI, volume
— from the broker or a browser job), `gold_macro_daily` (DFII10, T10YIE, DGS10, DTWEXBGS, USDINR close, COMEX settle,
GVZ), `gold_premium_daily` (landed, fair, implied premium, IBJA 995, duty rate), `gold_lbma_monthly` (vault tonnes, weekly
turnover). The periodicity switch is a view over these.

**F11 — The other agents' briefs were not in this prompt.** Part 8 writes micro-copy for the panels implied by the
owner's request (COT, chart, OTC, supply/demand, periodicity, who-closed, contract chooser, health check). Names will
need aligning with what the other agents ship; the copy is panel-shaped, so this is a rename, not a rewrite.

**F12 — GOLD lot size vs retail risk budget.** §7.6 arithmetic; the ticket addition (`max_lots_at_risk_pct`,
`hedge_usdinr_lots`, `atr14_rupees`) is a two-line change in `shared/mcx_specs.py` once a daily ATR exists.

**F13 — Tender cut-off unknown.** ICICI's square-off date for MCX GOLD/GOLDM before the tender period is not in the
repo; it decides when a swing position must be rolled. Owner action.

**F14 — US DST and UK GMT switches this fortnight.** UK moved to GMT on 25 Oct 2026 (LBMA AM/PM now 16:00/20:30 IST); US
moves on 1 Nov 2026 (MCX close 23:55 from 2 Nov; COT release Sat 02:00; FOMC 00:30; CPI 19:00). `shared/mcx_specs`
already handles the MCX close; the events calendar must carry both switches.

## 4. Deliverables (this folder)

| File | What |
|---|---|
| `CURRICULUM.md` | Parts 0–9 + appendices: health check, units/purity/products, venues (LBMA, COMEX, SGE, MCX) and the rupee price build, futures mechanics (lot/tick/margin/carry/roll/settlement/basis/EFP), players and structural positioning, drivers and regimes 2001–2025, reading COT / OI quadrants / warehouse / ETF / OTC / premiums / GSR / vol, advanced (GOFO/lease, options skew, term structure, cross-exchange, event playbooks, sizing, risk rules), panel micro-copy (16 existing + 14 proposed), daily/weekly/monthly routines, formulas cheat-sheet, IST clock, evidence ledger |
| `glossary.json` | 129 terms with `term`, `short` (tooltip), `long`, `see_also` (all references validated by `build_glossary.py`) |
| `tooltips.json` | 93 one-liners keyed by app payload fields (existing) and proposed panel fields |
| `cot_gold_mm_history.csv` | 160 weeks (Oct 2023 → 20 Oct 2026) of COMEX gold disaggregated positions (MM, PM, SD, OI, nets) from the CFTC API — the sample behind the COT-index worked example |
| `verify_sources.py`, `verify_pass2.py`, `verify_results.json`, `verify_pass2.json`, `verify_run.log` | the live verification, reproducible |
| `build_glossary.py` | generates the two JSON files; asserts tooltip length and cross-references |

## 5. How to ship it (proposal, no code changed)

- **LEARN page** (GO code `LRN` or a `?` chip on CMDT/MCXG): render `CURRICULUM.md` through the existing research
  document viewer (`routers/research.py` serves markdown from `reports/` read-only); add a CATALOG row
  `"reports/gold_program/G-EDU/CURRICULUM.md": ("Gold", "REFERENCE", "…")` so it also appears under RSCH.
- **Tooltips**: load `tooltips.json` once in `ui/lib/` and attach by field name via the terminal kit's `title` props on
  `Stat`/`Chip` and `Column.label`; the keys cover every gold field that exists today plus the proposed ones.
- **Glossary**: a side panel (search box over `glossary.json`; `see_also` as links) reachable from any tooltip's "?".
- **Evidence chips**: reuse `ResearchNote` / `SourceChip` with the three states this document uses (CORE arithmetic,
  CONTEXT, HEURISTIC); the verdict panel gets HEURISTIC now.
- **Health strip**: one component, five numbers (§0), mounted on CMDT, MCXG, BRF; the only place the premium and MM
  net are shown as numbers.

## 6. Open questions

1. What is the customs duty (BCD + AIDC) and tariff value in force on 26 Oct 2026? The 18% premium cannot be read until
   this is known. (CBIC; browser.)
2. Which panels are the other agents (COT, OTC, India, macro, visuals) actually shipping, and under what names? Part 8's
   copy is written against the owner's list and needs a rename pass.
3. ICICI's tender cut-off for MCX GOLD / GOLDM (and whether the account has delivery enabled).
4. Does MCX publish participant-wise open interest for bullion (SEBI mandated commodity exchanges to publish
   category-wise OI)? mcxindia.com blocks this machine; check in a browser. If yes, it is the MCX analogue of COT and
   belongs next to it.
5. IBJA (`ibjarates.com`) and SPDR (`spdrgoldshares.com`) redistribution terms — read before publishing their numbers.
6. SGE: the JSON endpoint behind `data_DelayedQuotes` (browser network tab) and SGE's data terms.
7. Is a scheduled browser-session fetch acceptable for CME warehouse stocks and the MCX bhavcopy (both 403 to plain
   clients)? If not, the COMEX daily OI panel falls back to the CFTC weekly total.
8. Should the COT→gold G-STUDY (§6.1 design) run before the COT panel ships, or ship the panel with the CONTEXT chip and
   run the study in parallel? (Recommendation: ship with the chip; the owner asked for the data explicitly.)

## 7. Owner actions

1. Read and decide on the three honesty findings (§1): dated duty input; HEURISTIC chip on the verdict; `max lots at
   risk` on the ticket.
2. Confirm ICICI's MCX tender cut-off and delivery status; add it to the specs table.
3. Approve the five DuckDB tables in F10 as the first gold ingest (COT weekly is free and can start this Saturday).
4. Decide the fetch policy for bot-blocked publishers (F4/F7): browser-session job vs link-only.
5. Set `FRED_API_KEY` in `.env` (free) if the macro panel grows beyond the CSV endpoint (not needed for DFII10/T10YIE).
6. Rename pass on Part 8 once the other agents' panel names are fixed.

## 8. Method and honesty notes

- Everything numeric in the worked examples is dated and came from a live fetch or the app's own endpoints during this
  session; nothing was typed from memory except historical regime figures (marked "approx.") and WGC annual totals.
- This agent's knowledge ends June 2026; 2026 market events after that are not characterised, and the curriculum says
  "read from the app" for them.
- Two academic references (Erb–Harvey 2013, Baur–Lucey 2010) and two COT-forecasting references (Sanders–Irwin–Merrin
  2009, Wang 2003) are cited as standard literature; SSRN blocked retrieval, so they are marked not live-verified.
- No POST/PUT/DELETE to any service, no restarts, no Telegram, no Breeze or ICICI credential path (the two local GETs
  are to endpoints that never import the broker client). No `.env` values printed; only key names were checked
  (`FRED_API_KEY`, `EIA_API_KEY`: both absent).
- Rate: 1.5 s between external requests; 20 s pause before the Yahoo retry; the 429s were respected, not retried further.
