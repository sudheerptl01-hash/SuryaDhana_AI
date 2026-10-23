# Q6: company events from the exchange's announcement files

**Stream:** Q6 of `ml/IMPROVEMENT_PLAN_2.md` (data and features; the lead runs the A/B `ae1_events`). **Code:** `ml/events/` (`parse`, `classify`, `features`, `checks`, `ic`, `report`). **Outputs:** `ml/data_ext/events_raw.parquet`, `ml/data_ext/event_features_10y.parquet` (+ `event_features_manifest.json`), `ml/results/improve2/events/events.json`. Every number in section 7 is quoted from `events.json`.

**Fixed on 2026-10-23, before any return statistic was computed:** sections 1 to 5 (sources, parser, classification rules, feature definitions, deviations). The rules were set from the category tables, sampled texts and the results weeks of a few liquid names, and from counts of records and of quarterly results coverage. No forward return, rank IC or book was looked at before section 7 was generated. The descriptive rank IC (section 7.6) is the last step and is labelled descriptive.

## 1. Sources

- Every PR bundle in `ml/data_raw/hist/pr/` (2016-10..2021-09) and `ml/data_raw/pr/` (2021-10..2026-10). The day's announcement list is the member `An<ddmmyy>.txt` / `an<ddmmyyyy>.txt`; the board-meeting list `Bm<date>.txt` / `bm<date>.txt` of the same bundle is used by results rule R4 (deviation D2).
- **The true date is the date in the member name.** Two bundle names are wrong: `PR020118.zip` holds 2019-01-02 and `PR060424.zip` holds 2024-06-04. Both true dates are also present in correctly named bundles (byte-identical), so both are skipped. Two dates are in both folders (2021-10-01, 2021-10-04; byte-identical), and the copy in `ml/data_raw/pr/` is kept. Every decision is logged in `events.json` → `parse.selection_decisions`. 2018-01-02 therefore has no file; the 2024-01-20 member (a Saturday session inside a gap) lists no records.
- Point in time: bundles are generated at about 16:10-16:55 IST on their date, after the 15:30 close (`parse.member_generated_after_next_open` lists the one exception, the 2026-06-15 member, generated on 2026-06-16; its texts cover announcements up to 2026-06-15, so it keeps its date). An announcement in the bundle of session t is usable at t, and entry is at t+1's open. Every bundle date is a session (`parse.files_on_non_session_dates` is empty); the rule "a non-session date maps to the next session" is implemented and never triggers.
- Prices: `ml/results/improve/cache/features_prices_export_10y.parquet` (adjusted closes, raw volume, unadjusted close, turnover). `nse_market.duckdb` is never opened.

## 2. Parser (`ml/events/parse.py`)

Formats, profiled across all years:

| Years | Line layout | Category |
|---|---|---|
| 2016-10 .. mid-2018 | `<Company>{2+ spaces}<SYMBOL> : <rest>` | spliced into the text: `rest = text[:k] + Category + text[k-1:]`, e.g. `InAnalysts/Institutional Investor Meet/Con. Call Updatesnox Wind Limited has informed ...` |
| mid-2018 .. 2025 | same | `<Category> <SYMBOL> : <text>` on most lines; `<Category>-XBRL <TEXT>` from 2023; `<Category> <text>` with no separator on the rest |
| 2026 | `<Company> <SYMBOL> : <rest>` (one space) | as 2018-2025 |

- A line starts a record when it matches the wide layout (symbol = an upper-case token containing a letter, then `:`), or the narrow layout with the symbol confirmed (repeated as `<SYMBOL> :` in the rest, or a symbol seen at least 3 times in the wide layout or in the bhavcopy). Other non-empty lines are continuations of the previous record (announcement texts contain line breaks). Files are decoded as UTF-8, else cp1252.
- Category: the explicit separator when present; otherwise the longest category of a dictionary at the start of the text; otherwise a dictionary category spliced in after a prefix of the company name or of a standard opener ("The Exchange ...") within the first 45 characters (leftmost, then longest); otherwise the company-name overlap of the spliced layout; otherwise empty. The dictionary is the explicit categories seen at least 3 times plus spliced-layout categories (learned from files dated before 2019) seen at least 5 times that look like a category.
- Unknown symbols are kept (`in_eod` marks symbols present in the EQ/BE bhavcopy); the features join on `symbol == ticker`.
- `events_raw.parquet`: one row per record (`source = "an"`) with `file_date`, `session_date`, `symbol`, `company`, `category_raw`, `text` (first 1,500 characters), parse method and layout, plus the board-meeting list rows (`source = "bm"`, with `bm_date`), plus the class flags of section 3.

## 3. Classification rules (`ml/events/classify.py`, fixed)

Each announcement record gets flags. A routine record carries no other class; the other classes may overlap. "Generic category" means `Updates`, `General Updates`, `Others` or no category. Patterns are case-insensitive; the exact regular expressions are in `classify.py` and in `events.json` → `classify.rules`.

| Class | Rule | Definition |
|---|---|---|
| routine | RT1 | category is Declaration of NAV; Trading Window; Copy of Newspaper Publication; Loss of Share Certificates; Loss/Duplicate-Share Certificate; Issue of Duplicate Share Certificate; Certificate under SEBI (Depositories and Participants) Regulations, 2018; and the similar boilerplate: Code of Conduct under SEBI (PIT); Structural Digital Database; Annual Secretarial Compliance Report; Quarterly Compliance Report on Corporate Governance; Registrar & Share Transfer Agent Update; E-mail ID for Investor's Grievance Redressal; Interest Rates Updates (debt instruments); Disclosure of Unitholding pattern; Disclosure of all complaints including SCORES; Statement of deviation(s) or variation(s) under Reg. 32; Monitoring Agency Report; Daily Buy-Back of equity shares |
| routine | RT2 | generic category whose text is a newspaper publication / advertisement, a lost or duplicate share certificate, a Regulation 74(5) depository certificate, a trading-window notice, a Regulation 7(3) / 40(9) / 40(10) / 13(3) compliance filing, share-capital reconciliation or investor complaints, a change of the registrar's name, the structural digital database or a secretarial compliance certificate |
| results | R1 | category Financial Results Updates, Results, Results/Others, Publish Audited Results, Consolidated Result Updates - IFRS, Limited Review Report, or Integrated Filing- Financial (this one only when its text names financial results); text not matching the exclusions R2x |
| results | R2 | category Outcome of Board Meeting, Updates, General Updates, Press Release, Investor Presentation, Dividend, Others or none, and the text names financial results (or "results for the quarter / half year / year / period", "Q1-Q4 results", "earnings release") and does not match R2x |
| results | R2x | exclusions: intimation that results will be considered, announced or of a meeting date ("to consider", "to be held", "scheduled", "to announce", "announces the date"), notices of board meetings, newspaper / advertisement / publication, calls, transcripts, recordings, analyst and investor meets, non-submission, delay, reasons, clarification, relaxation, applicability, option to submit, rectification, discrepancy, corrigendum, machine-readable or searchable copies, re-submission, revised, trading window |
| results | R3 | an Outcome of Board Meeting record (or a generic one whose text is an outcome of a board meeting) that is not R1/R2 and matches a board meeting intimated for financial results for the same symbol in a file dated on or before the outcome: the intimated meeting date is within 3 days of the "held on" date in the text, or within the 7 days up to the file date when the text has no date |
| results | R4 | a board meeting intimated for financial results (board-meeting list row whose purpose mentions results, or a Board Meeting Intimation record naming financial results and a "to be held on" date), placed at the first session on or after the meeting date, when the intimation was filed on or before the meeting date and was not superseded before that date by a later intimation naming another date (more than 3 days apart) or by a Board meeting Cancelled / Postponed / Adjourned / Deferred / Rescheduled record (deviation D2) |
| results | RD | release session: per symbol, a results session with another results session in the previous 5 sessions is the same release (the outcome, press release, presentation and integrated filing of one release collapse onto its first session) |
| rating | CR1, CR2 | category Credit Rating (incl. "- New / - Revision / - Others"); or generic category whose text names a credit rating or a rating agency's rating, not ESG ratings or the large-corporate-borrower boilerplate |
| mgmt_change | M1-M3 | category Resignation*, Cessation, Change in Management, Change in Director(s), Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent, Change in Auditors, Appointment of Auditors, Change in Company Secretary/Compliance Officer, Change in Managing Director, Appointment of Director / Chairman / Managing Director / Chief ... / Company Secretary / Compliance Officer / Independent ..., Retirement, Demise; category Appointment when the text names a director or a KMP-level officer (MD, CEO, CFO, COO, company secretary, compliance officer, KMP, chairman, whole-time director, auditor, president); generic category whose text is a resignation or cessation of such a person |
| orders | O1, O2 | category Bagging/Receiving of orders/contracts, Awarding or Bagging of Orders/Contracts, Awarding of order(s)/contract(s); or generic / press-release category whose text is a receipt, bagging, securing, win or award of orders or contracts, a letter of award / acceptance / intent, or an L-1 / lowest bidder; not court, tribunal, regulator, tax, Order-in-Original, commissioner, enforcement, arbitration or penalty orders (O2x) |
| insolvency | IN1, IN2 | category Corporate Insolvency Resolution Process or BIFR; or generic category whose text names the corporate insolvency resolution process, CIRP, the Insolvency and Bankruptcy Code, an (interim) resolution professional, or an NCLT admission |

## 4. Family E (`ml/events/features.py`; names exactly as in plan Q6)

Windows count sessions of the price calendar; "the last W sessions" is [t-W+1, t], t included. s is the most recent release session (rule RD) on or before t; d = t - s.

| Column | Definition |
|---|---|
| `sess_since_results` | min(d, 126); 126 when no release in the history |
| `results_last_5` | 1 if d <= 4, else 0 |
| `results_last_20` | 1 if d <= 19, else 0 |
| `ear_3d` | for 1 <= d <= 59: close[s+1]/close[s-1] - 1 minus the equal-weight universe's mean of the same ratio over its members on s (adjusted closes, calendar sessions; NaN when the stock has no close on s-1 or s+1); NaN when d = 0 or d >= 60 or no release |
| `ear_vol_z` | (V[s] - mean V[s-20..s-1]) / sd V[s-20..s-1], V = split-adjusted volume, at least 15 observations, ddof 1; NaN when `ear_3d` is NaN |
| `ann_count_20` | distinct non-routine announcements in the last 20 sessions (distinct session, category and first 300 characters of text) |
| `rating_20` | count: sessions in the last 20 with at least one rating announcement |
| `mgmt_change_60` | count: sessions in the last 60 with at least one management-change announcement |
| `orders_20` | count: sessions in the last 20 with at least one order announcement |
| `insolvency_60` | 0/1 flag: an insolvency announcement in the last 60 sessions |

The choice of counts (sessions with at least one announcement, so a filing listed twice on one day counts once) for rating, management change and orders, and a 0/1 flag for insolvency (its filings are long chains of procedural updates), was made here, before any IC. The parquet has exactly `date`, `ticker` and these ten columns, one row per row of `ml/data_10y/model_dataset.parquet`, in its order (date, ticker).

## 5. Deviations from the plan's wording (documented before any result)

- **D1. The source has coverage gaps.** Some bundles list no company announcements (mutual-fund NAV lines only): 2022-02-22 to 2022-12-16, 2023-09-20 to 2023-10-12 and 2024-01-09 to 2024-01-25, plus single days. A session is *uncovered* when it has no file or fewer than 20 non-NAV records for symbols that had traded by the file date (the smallest covered file and the largest uncovered one are in section 7.3: the two populations do not overlap). A run of at least 3 uncovered sessions is a *coverage gap*; it is known causally (at session t a run counts once it has reached 3 sessions by t, so no value depends on a later file). Isolated uncovered sessions (runs of 1-2) are treated as days without announcements and listed in the manifest. A value that a gap could change is NaN: a count or a zero flag whose window touches a gap; `sess_since_results` when a gap lies after the last observed release inside the look-back (or anywhere in the last 126 sessions when there is none); `ear_3d` / `ear_vol_z` when a gap lies after s. A positive flag, and a release observed after the last gap, are kept. Without this, "no announcement" during a gap would read as "no event". No other source of the same information exists on disk.
- **D2. Results releases are dated with the board-meeting list when the announcement list lacks the filing.** The plan's results announcement is the release of financial results, not the intimation of the meeting that will consider them. Before October 2025 the announcement list usually carries only "Outcome of Board Meeting held on <date>" without saying what was approved, and for many name-quarters it carries no results record at all (for example, Asian Paints' 2019-07-24 results have no record in the 2019-07 files). The board meeting at which the results are approved is the release (listed companies must disclose the results within 30 minutes of the meeting's close), and the bundles' own board-meeting list gives each meeting's date and purpose days in advance. Rules R3 (an outcome matched to a results-purpose meeting) and R4 (the session of a results-purpose meeting, with the supersession rules above) are the nearest faithful version; the intimation's own date is never used as a results date. `events.json` → `coverage.results_quarterly_liquid` reports, per calendar quarter, the share of liquid names with a release, from the announcement records alone (R1-R3) and with R4.
- **D3. One release, one session (rule RD).** A release is filed several times (outcome, press release, presentation, integrated filing, a re-filing after midnight). Results sessions within 5 sessions after another collapse onto the first, so that `sess_since_results` and `ear_3d` refer to the release rather than to the last re-filing. Each kept session depends only on earlier sessions.
- **D4. The 60-session window of `ear_3d`.** "The most recent results announcement within 60 sessions, NaN until t >= that session + 1" is read as: s = the most recent release; value when 1 <= t - s <= 59, NaN when t = s (even when an earlier release lies within 60 sessions).
- **D5. Volume.** The price export's volume is the raw print; `ear_vol_z` uses volume x close_unadj / close (split- and bonus-adjusted) so that a split inside the 20-session window does not create a jump.
- **D6. Equal-weight universe.** The dataset's universe rule (close_unadj >= 10, 20-session median turnover >= Rs 1 crore with at least 10 observations, ETFs excluded) recomputed on the price export; it equals the dataset's row set on every date 2017-10-03..2026-10-16 (section 7.3), and it extends the universe to 2016-10..2017-09 for releases before the dataset starts. Members on s with closes on s-1 and s+1 enter the mean.
- **D7. Extended routine list.** Besides the plan's five categories, the boilerplate listed in RT1/RT2 is routine.
- **D8. Fixed parser vocabulary.** The category dictionary and the list of known symbols that the parser uses to read the spliced 2016-2018 layout and to confirm record starts are learned once from the whole corpus (text only, no prices) and frozen in `ml/events/vocabulary.json`, with the same status as the rule table. With it fixed, each file's records depend on that file alone, which the re-parse check verifies; the point-in-time tests hold it fixed.

## 6. Checks (`ml/events/checks.py`; all written to `events.json`)

1. Coverage per year: bundles parsed, records, symbols matched to dataset tickers, share of dataset rows with a release in the past 126 sessions; quarterly results coverage of liquid names (R1-R3 alone and with R4).
2. Re-parse: every raw zip re-parsed from scratch with the fixed vocabulary; per-file digests must equal `events_raw.parquet`. Point in time: 100 random dataset cells (seed 108) recomputed by an independent loop implementation of section 4 from the re-parsed files dated <= t (classification and every rule re-run on that restricted set) and prices dated <= t, compared with the parquet.
3. Delete-the-future: the whole feature build re-run with every file and price after one month-end removed; rows up to that month-end must be unchanged.
4. Shift test: the build on files up to T0, then with the later bundles appended; rows <= T0 must be unchanged.
5. Last step only (`ml/events/ic.py`): descriptive per-date rank IC.

## 7. Results

<!-- generated below from events.json by ml/events/report.py; do not edit by hand -->
