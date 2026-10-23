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
   Supplement (added on resuming the stream after a container restart, after the 100 random cells and before any return statistic): the random draw holds few cells with a rare value (ratings, orders, insolvency), so the same recompute runs on 10 random cells (seed 108) from each of eight strata: `rating_20 > 0`, `orders_20 > 0`, `insolvency_60 = 1`, `mgmt_change_60 > 0`, `results_last_5 = 1`, `sess_since_results = 0`, finite `ear_vol_z`, `ann_count_20 >= 5` (`checks.pit_cells_stratified`).
3. Delete-the-future: the whole feature build re-run with every file and price after one month-end (2024-05-31, inside a results season) removed; rows up to that month-end must be unchanged.
4. Shift test: the build on files up to T0 (2020-02-14, inside a results season), then with the later bundles appended; rows <= T0 must be unchanged.
5. A/B join: the parquet through `ml.improve.ab.load_frame` (the lead's A/B path) and `ab.features_for("ae1_events")`; no model is trained here.
6. Last step only (`ml/events/ic.py`): descriptive per-date rank IC (Spearman) against `y_excess_20d`, per date with >= 50 names, mean and Newey-West t (lag 20), by calendar year: `ear_3d` among rows with a release in the last 60 sessions (`sess_since_results <= 59`, finite `ear_3d`), and every family-E column over all rows with a value. Rows: labelled, clean (`y_clean_20d`) rows dated before the holdout's first test date (the holdout stays untouched for the lead's single scoring). Descriptive only; the Q6 pass mark is the primary A/B mark.

## 7. Results

<!-- generated below from events.json by ml/events/report.py; do not edit by hand -->

### 7.1 Parse (`events.json` → `parse`)

2492 bundles found, 2492 with an announcement member, 2488 dates selected; 4,956,205 announcement records and 91,226 board-meeting list rows. Selection decisions:

- 2019-01-02: `data_raw/hist/pr/PR020118.zip` skipped (file name disagrees with member date; true date present in data_raw/hist/pr/PR020119.zip; identical bytes: True)
- 2021-10-01: `data_raw/hist/pr/PR011021.zip` skipped (duplicate of data_raw/pr/PR011021.zip; identical bytes: True)
- 2021-10-04: `data_raw/hist/pr/PR041021.zip` skipped (duplicate of data_raw/pr/PR041021.zip; identical bytes: True)
- 2024-06-04: `data_raw/pr/PR060424.zip` skipped (file name disagrees with member date; true date present in data_raw/pr/PR040624.zip; identical bytes: True)

Encodings: cp1252 2187, utf-8 301. Vocabulary: 570 categories, 11,701 known symbols (`events/vocabulary.json`).

| Year | Bundles | Records | Wide / narrow layout | Category from separator / dictionary / spliced / derived / none | Symbols | In bhavcopy | Board-meeting rows |
|---|---:|---:|---|---|---:|---:|---:|
| 2016 | 62 | 243,270 | 243,270 / 0 | 3 / 235,156 / 8,053 / 51 / 7 | 5,737 | 1,536 | 1,953 |
| 2017 | 248 | 837,960 | 837,960 / 0 | 15 / 793,496 / 44,180 / 231 / 38 | 6,820 | 1,790 | 8,374 |
| 2018 | 245 | 715,533 | 715,533 / 0 | 359,618 / 341,344 / 14,537 / 17 / 17 | 6,123 | 1,875 | 8,033 |
| 2019 | 245 | 787,837 | 787,837 / 0 | 561,980 / 225,857 / 0 / 0 / 0 | 5,547 | 1,895 | 8,727 |
| 2020 | 252 | 642,522 | 642,522 / 0 | 495,450 / 147,015 / 0 / 55 / 2 | 5,006 | 1,957 | 8,815 |
| 2021 | 248 | 483,236 | 483,236 / 0 | 377,216 / 105,935 / 0 / 84 / 1 | 4,147 | 2,074 | 8,822 |
| 2022 | 248 | 184,315 | 184,315 / 0 | 116,587 / 67,712 / 0 / 15 / 1 | 3,273 | 2,114 | 2,046 |
| 2023 | 246 | 232,848 | 232,848 / 0 | 167,149 / 65,603 / 1 / 78 / 17 | 2,861 | 2,251 | 9,102 |
| 2024 | 249 | 273,859 | 273,856 / 3 | 205,761 / 67,943 / 2 / 107 / 46 | 3,130 | 2,426 | 10,267 |
| 2025 | 249 | 244,134 | 171,001 / 73,133 | 167,521 / 76,537 / 0 / 57 / 19 | 3,491 | 2,677 | 13,720 |
| 2026 | 196 | 310,691 | 259 / 310,432 | 221,477 / 88,509 / 1 / 285 / 419 | 3,574 | 2,819 | 11,367 |

### 7.2 Category frequency by year and mapping (`classify.category_frequency_by_year_bhavcopy_symbols`, `classify.category_to_class_share_top`)

Records for bhavcopy symbols, 315 distinct categories; the 60 most frequent are shown (the JSON holds 120). Mapping = share of the category's records carrying each class.

| Category | Total | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Mapping |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Declaration of NAV | 290,089 | 1,858 | 6,652 | 6,041 | 8,285 | 13,803 | 21,355 | 28,795 | 34,176 | 43,882 | 61,078 | 64,164 | routine 1.00 |
| Updates | 130,970 | 1,700 | 8,628 | 14,212 | 20,693 | 20,185 | 14,966 | 2,610 | 14,340 | 15,173 | 7,972 | 10,491 | routine 0.17, results 0.02, orders 0.01 |
| Analysts/Institutional Investor Meet/Con. Call Updates | 113,598 | 1,627 | 7,699 | 8,739 | 8,880 | 8,324 | 11,665 | 2,350 | 15,909 | 14,675 | 14,290 | 19,440 | non-routine |
| Trading Window | 75,103 | 539 | 2,414 | 3,191 | 6,492 | 6,683 | 7,100 | 1,547 | 6,191 | 13,337 | 11,551 | 16,058 | routine 1.00 |
| Outcome of Board Meeting | 66,449 | 663 | 4,637 | 5,950 | 6,317 | 5,693 | 6,183 | 1,476 | 7,180 | 7,136 | 8,648 | 12,566 | results 0.77 |
| Shareholders meeting | 59,919 | 173 | 6,145 | 6,130 | 6,452 | 5,582 | 6,594 | 572 | 4,967 | 6,737 | 5,708 | 10,859 | non-routine |
| Copy of Newspaper Publication | 55,803 | 0 | 0 | 0 | 4 | 4,087 | 9,074 | 1,510 | 8,997 | 8,403 | 8,971 | 14,757 | routine 1.00 |
| Press Release | 46,101 | 1,020 | 4,512 | 5,166 | 5,112 | 4,629 | 5,003 | 1,070 | 4,113 | 4,040 | 4,623 | 6,813 | results 0.16, orders 0.03 |
| Loss of Share Certificates | 45,767 | 0 | 0 | 0 | 33 | 3,033 | 10,374 | 2,395 | 16,252 | 13,478 | 125 | 77 | routine 1.00 |
| Board Meeting Intimation | 31,858 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6,971 | 8,745 | 6,242 | 9,900 | non-routine |
| Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Shar | 27,609 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4,357 | 8,364 | 5,628 | 9,260 | mgmt_change 1.00 |
| Certificate under SEBI (Depositories and Participants) Regulations, 2018 | 26,475 | 0 | 0 | 0 | 11 | 1,106 | 4,198 | 1,251 | 3,321 | 3,740 | 4,165 | 8,683 | routine 1.00 |
| General Updates | 26,017 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1,530 | 9,405 | 15,082 | routine 0.02, results 0.02 |
| Disclosure under SEBI Takeover Regulations | 22,037 | 175 | 897 | 593 | 1,008 | 3,698 | 3,966 | 143 | 2,172 | 2,820 | 2,133 | 4,432 | non-routine |
| Investor Presentation | 21,314 | 300 | 1,393 | 1,833 | 1,965 | 1,921 | 2,500 | 610 | 2,653 | 2,154 | 2,437 | 3,548 | results 0.02 |
| Loss/Duplicate-Share Certificate | 21,236 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1,291 | 19,657 | 189 | 99 | routine 1.00 |
| Appointment | 13,843 | 15 | 547 | 1,082 | 1,275 | 1,258 | 1,430 | 283 | 1,321 | 1,592 | 2,046 | 2,994 | mgmt_change 0.91 |
| Notice Of Shareholders Meetings | 12,593 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2,349 | 3,626 | 2,257 | 4,361 | non-routine |
| Resignation | 11,113 | 18 | 454 | 884 | 1,147 | 934 | 917 | 161 | 1,123 | 1,180 | 1,274 | 3,021 | mgmt_change 1.00 |
| Alteration Of Capital and Fund Raising | 10,555 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1,597 | 3,289 | 2,222 | 3,447 | non-routine |
| Related Party Transactions | 10,433 | 0 | 0 | 0 | 2,809 | 2,926 | 2,677 | 30 | 1,645 | 281 | 41 | 24 | non-routine |
| Dividend | 10,206 | 91 | 1,241 | 1,309 | 1,304 | 928 | 964 | 155 | 1,180 | 1,011 | 778 | 1,245 | results 0.02 |
| Credit Rating | 9,972 | 142 | 750 | 889 | 1,145 | 1,292 | 1,275 | 195 | 1,034 | 1,003 | 842 | 1,405 | rating 1.00 |
| Change in Director(s) | 9,071 | 84 | 563 | 744 | 1,165 | 1,044 | 1,108 | 176 | 775 | 1,409 | 820 | 1,183 | mgmt_change 1.00 |
| ESOP/ESOS/ESPS | 8,795 | 0 | 260 | 348 | 331 | 696 | 1,552 | 288 | 1,261 | 1,259 | 1,127 | 1,673 | non-routine |
| Disc. under Reg.30 of SEBI (SAST) Reg.2011 | 8,704 | 7 | 3,203 | 2,767 | 2,692 | 27 | 5 | 0 | 3 | 0 | 0 | 0 | non-routine |
| Acquisition | 8,465 | 34 | 166 | 307 | 459 | 365 | 653 | 151 | 1,206 | 2,069 | 1,497 | 1,558 | non-routine |
| Record Date | 7,779 | 168 | 728 | 770 | 777 | 961 | 1,075 | 233 | 1,031 | 1,048 | 988 | 0 | non-routine |
| Daily Buy-Back of equity shares | 6,383 | 86 | 538 | 734 | 1,195 | 1,983 | 877 | 135 | 666 | 2 | 0 | 167 | routine 1.00 |
| Analyst/Investor Meet Para A | 6,341 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6,341 | non-routine |
| Allotment of Securities | 6,329 | 114 | 451 | 350 | 333 | 556 | 885 | 189 | 862 | 940 | 656 | 993 | non-routine |
| Change in Management | 5,784 | 1 | 1 | 17 | 30 | 48 | 64 | 6 | 478 | 1,492 | 1,342 | 2,305 | mgmt_change 1.00 |
| Book Closure | 5,588 | 7 | 246 | 455 | 288 | 1,355 | 1,436 | 16 | 899 | 883 | 3 | 0 | non-routine |
| Corporate Insolvency Resolution Process | 5,216 | 0 | 0 | 211 | 571 | 540 | 721 | 156 | 667 | 939 | 566 | 845 | insolvency 1.00 |
| Clarification | 5,174 | 299 | 1,063 | 850 | 1,016 | 700 | 941 | 134 | 101 | 68 | 2 | 0 | non-routine |
| Clarification - Financial Results | 4,807 | 0 | 452 | 834 | 725 | 559 | 426 | 6 | 392 | 310 | 330 | 773 | non-routine |
| Reply to Clarification- Financial results | 4,570 | 0 | 363 | 812 | 634 | 526 | 413 | 39 | 404 | 346 | 289 | 744 | non-routine |
| Reply to Clarification Sought | 4,528 | 299 | 955 | 784 | 810 | 584 | 847 | 94 | 88 | 67 | 0 | 0 | non-routine |
| Statement of deviation(s) or variation(s) under Reg. 32 | 3,998 | 31 | 174 | 329 | 264 | 307 | 373 | 127 | 589 | 820 | 430 | 554 | routine 1.00 |
| AGM/Book Closure | 3,896 | 25 | 1,319 | 1,147 | 1,381 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | non-routine |
| Allotment of ESOP/ESPS | 3,720 | 115 | 986 | 1,122 | 1,093 | 384 | 14 | 0 | 3 | 3 | 0 | 0 | non-routine |
| Cessation | 3,581 | 27 | 148 | 202 | 457 | 294 | 289 | 60 | 215 | 574 | 475 | 840 | mgmt_change 1.00 |
| Monitoring Agency Report | 2,896 | 3 | 20 | 53 | 63 | 44 | 100 | 45 | 246 | 493 | 722 | 1,107 | routine 1.00 |
| Change in Auditors | 2,871 | 7 | 326 | 137 | 179 | 166 | 259 | 13 | 205 | 371 | 470 | 738 | mgmt_change 1.00 |
| Bagging/Receiving of orders/contracts | 2,783 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 83 | 730 | 1,970 | orders 1.00 |
| Financial Results Updates | 2,705 | 31 | 690 | 374 | 304 | 520 | 622 | 164 | 0 | 0 | 0 | 0 | results 0.65 |
| Declaration of NAV ICICIB22   : | 2,033 | 0 | 0 | 165 | 243 | 209 | 247 | 244 | 238 | 243 | 249 | 195 | routine 1.00 |
| Dividend Updates | 1,947 | 7 | 85 | 95 | 103 | 289 | 502 | 66 | 390 | 410 | 0 | 0 | non-routine |
| Declaration of NAV BSLNIFTY   : | 1,939 | 0 | 0 | 142 | 242 | 247 | 246 | 238 | 204 | 207 | 218 | 195 | routine 1.00 |
| Awarding or Bagging of Orders/Contracts | 1,927 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 781 | 1,146 | orders 1.00 |
| Code of Conduct under SEBI(PIT) Reg., 2015 | 1,778 | 5 | 35 | 50 | 912 | 228 | 263 | 29 | 139 | 117 | 0 | 0 | routine 1.00 |
| News Clarification | 1,744 | 126 | 484 | 851 | 277 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | non-routine |
| Committee Meeting Updates | 1,737 | 0 | 151 | 275 | 172 | 248 | 174 | 16 | 159 | 193 | 110 | 239 | non-routine |
| Action(s) taken or orders passed | 1,674 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 163 | 679 | 832 | non-routine |
| Annual Secretarial Compliance Report | 1,595 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1,595 | 0 | 0 | 0 | routine 1.00 |
| Change in Company Secretary/Compliance Officer | 1,559 | 24 | 105 | 118 | 193 | 170 | 189 | 34 | 168 | 187 | 160 | 211 | mgmt_change 1.00 |
| Amendment to AOA/MOA | 1,455 | 0 | 68 | 146 | 123 | 117 | 136 | 24 | 152 | 195 | 211 | 283 | non-routine |
| Corrigendum | 1,432 | 13 | 121 | 145 | 147 | 131 | 160 | 17 | 160 | 177 | 128 | 233 | non-routine |
| Scheme of Arrangement | 1,407 | 27 | 104 | 129 | 194 | 126 | 165 | 39 | 201 | 133 | 124 | 165 | non-routine |
| Declaration of NAV ICICIMCAP  : | 1,339 | 0 | 0 | 165 | 243 | 209 | 247 | 244 | 231 | 0 | 0 | 0 | routine 1.00 |

| Class (bhavcopy symbols) | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| routine | 2,727 | 10,995 | 15,359 | 27,953 | 40,024 | 58,752 | 38,380 | 76,510 | 105,380 | 88,537 | 107,184 |
| results | 710 | 4,641 | 5,425 | 6,317 | 6,102 | 6,354 | 1,713 | 6,871 | 6,321 | 8,753 | 12,099 |
| rating | 153 | 781 | 914 | 1,195 | 1,326 | 1,298 | 198 | 1,055 | 1,123 | 1,313 | 2,208 |
| mgmt_change | 578 | 2,934 | 3,394 | 4,679 | 4,139 | 4,498 | 760 | 8,799 | 15,206 | 11,995 | 20,353 |
| orders | 83 | 334 | 402 | 317 | 281 | 395 | 83 | 404 | 563 | 1,902 | 3,714 |
| insolvency | 10 | 106 | 331 | 624 | 600 | 784 | 161 | 725 | 959 | 582 | 870 |
| non_routine | 9,386 | 52,839 | 60,460 | 67,940 | 65,095 | 71,903 | 11,792 | 84,628 | 100,828 | 94,430 | 153,191 |

| Results rule (all symbols) | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R1 | 93 | 629 | 356 | 336 | 593 | 682 | 179 | 154 | 77 | 259 | 176 |
| R2 | 185 | 958 | 1,275 | 1,495 | 1,495 | 1,382 | 370 | 1,665 | 1,444 | 6,267 | 9,526 |
| R3 | 460 | 3,235 | 4,034 | 4,709 | 4,236 | 4,527 | 1,191 | 5,521 | 5,440 | 3,360 | 3,448 |

### 7.3 Coverage (`checks.coverage`, `features_manifest.coverage`)

Coverage gaps (D1): 2022-02-22 to 2022-12-16 (203 sessions); 2023-09-20 to 2023-10-12 (16 sessions); 2024-01-09 to 2024-01-25 (13 sessions). Isolated uncovered sessions treated as days without announcements: 2018-01-02, 2018-07-10, 2023-10-16, 2023-10-17, 2025-06-10, 2025-09-19.

Covered sessions 2,251, uncovered 238 (of which in full runs of >= 3: 232); the smallest covered file has 53 company records, the largest uncovered file 6; sessions without records: 2018-01-02, 2024-01-20.
Universe rule recomputed on the price export vs the dataset's rows (D6): both 2,226,504, left_only 0, right_only 0.
Release sessions: 72,835; results observations by rule: R4 72,215, R3 40,161, R2 26,062, R1 3,534; release sessions by the rules observed on them: R4 50,524, R3+R4 11,239, R2+R4 6,115, R2+R3+R4 1,914, R2 1,248, R1 645, R1+R3+R4 413, R3 286.
Spacing between consecutive releases of a symbol (sessions): median 63; histogram edges [6, 11, 21, 41, 51, 56, 61, 66, 71, 91, 127, 1000000] counts [675, 966, 3179, 4761, 7590, 10219, 18049, 9272, 6938, 3312, 4254].

| Year | Bundles | Records (all) | Non-NAV | Non-routine | Symbols (non-NAV) | Matched to dataset tickers | Dataset rows | Rows with a release in the past 126 sessions | Of rows with a known value | sess_since_results NaN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2016 | 62 | 243,270 | 11,487 | 10,607 | 1,941 | 1,179 | 0 | n/a | n/a | n/a |
| 2017 | 248 | 837,960 | 64,102 | 59,632 | 3,809 | 1,379 | 50,437 | 98.7% | 98.7% | 0.0% |
| 2018 | 245 | 715,533 | 73,196 | 65,115 | 3,121 | 1,484 | 172,120 | 98.0% | 98.0% | 0.0% |
| 2019 | 245 | 787,837 | 89,941 | 72,414 | 2,767 | 1,524 | 128,253 | 98.5% | 98.5% | 0.0% |
| 2020 | 252 | 642,522 | 93,993 | 69,777 | 2,746 | 1,567 | 158,782 | 97.9% | 97.9% | 0.0% |
| 2021 | 248 | 483,236 | 112,411 | 77,014 | 3,175 | 1,667 | 238,480 | 97.1% | 97.1% | 0.0% |
| 2022 | 248 | 184,315 | 21,572 | 14,035 | 2,792 | 1,714 | 251,377 | 15.5% | 96.5% | 83.9% |
| 2023 | 246 | 232,848 | 131,535 | 90,045 | 2,449 | 1,834 | 277,552 | 73.8% | 99.1% | 25.5% |
| 2024 | 249 | 273,859 | 175,511 | 111,293 | 2,666 | 1,943 | 342,347 | 80.9% | 99.4% | 18.6% |
| 2025 | 249 | 244,134 | 138,948 | 108,072 | 2,982 | 2,105 | 329,243 | 98.8% | 98.8% | 0.0% |
| 2026 | 196 | 310,691 | 225,325 | 175,042 | 3,119 | 2,182 | 277,913 | 98.2% | 98.2% | 0.0% |

Quarterly results coverage (D2): share of names with at least one release session in the calendar quarter; liquid = `cs_rank_turnover` >= 0.67 on some row of the quarter.

| Quarter | Liquid names | With a release | From announcement records alone (R1-R3) | All dataset names | With a release | R1-R3 alone |
|---|---:|---:|---:|---:|---:|---:|
| 2017Q4 | 736 | 98.6% | 58.6% | 1006 | 98.4% | 59.2% |
| 2018Q1 | 727 | 95.9% | 58.2% | 1056 | 96.1% | 56.7% |
| 2018Q2 | 564 | 74.7% | 55.9% | 877 | 78.9% | 57.5% |
| 2018Q3 | 493 | 95.5% | 58.6% | 803 | 95.8% | 60.5% |
| 2018Q4 | 409 | 99.0% | 60.6% | 748 | 98.5% | 61.2% |
| 2019Q1 | 387 | 98.5% | 66.4% | 703 | 97.9% | 67.3% |
| 2019Q2 | 379 | 98.2% | 73.1% | 712 | 98.6% | 71.6% |
| 2019Q3 | 324 | 97.2% | 66.4% | 618 | 96.4% | 67.5% |
| 2019Q4 | 393 | 97.2% | 65.6% | 644 | 97.5% | 67.5% |
| 2020Q1 | 467 | 96.6% | 62.7% | 711 | 95.9% | 64.4% |
| 2020Q2 | 433 | 94.2% | 62.4% | 707 | 92.5% | 60.4% |
| 2020Q3 | 599 | 96.7% | 64.4% | 846 | 96.8% | 65.6% |
| 2020Q4 | 650 | 96.5% | 66.1% | 910 | 96.3% | 65.5% |
| 2021Q1 | 724 | 96.5% | 63.7% | 986 | 96.2% | 64.4% |
| 2021Q2 | 866 | 97.5% | 57.2% | 1142 | 96.7% | 56.9% |
| 2021Q3 | 930 | 96.6% | 67.5% | 1247 | 96.2% | 68.7% |
| 2021Q4 | 844 | 96.6% | 67.3% | 1193 | 95.9% | 66.7% |
| 2022Q1 | 871 | 97.4% | 68.1% | 1268 | 97.0% | 69.8% |
| 2022Q2 | 830 | 0.0% | 0.0% | 1207 | 0.0% | 0.0% |
| 2022Q3 | 833 | 0.0% | 0.0% | 1192 | 0.0% | 0.0% |
| 2022Q4 | 877 | 1.0% | 1.0% | 1228 | 0.8% | 0.8% |
| 2023Q1 | 833 | 95.8% | 60.7% | 1187 | 95.4% | 62.5% |
| 2023Q2 | 937 | 96.2% | 79.5% | 1243 | 96.0% | 78.6% |
| 2023Q3 | 1066 | 96.3% | 65.3% | 1369 | 96.1% | 64.8% |
| 2023Q4 | 1071 | 79.5% | 57.3% | 1442 | 81.5% | 57.8% |
| 2024Q1 | 1134 | 62.0% | 37.0% | 1549 | 64.7% | 37.8% |
| 2024Q2 | 1097 | 98.6% | 81.3% | 1501 | 98.3% | 80.5% |
| 2024Q3 | 1239 | 98.6% | 66.0% | 1597 | 98.4% | 66.2% |
| 2024Q4 | 1097 | 98.3% | 55.3% | 1559 | 98.0% | 55.4% |
| 2025Q1 | 968 | 98.2% | 48.5% | 1491 | 98.3% | 47.0% |
| 2025Q2 | 1080 | 98.2% | 67.5% | 1480 | 98.2% | 66.9% |
| 2025Q3 | 1148 | 99.0% | 74.0% | 1507 | 98.5% | 73.4% |
| 2025Q4 | 1158 | 98.9% | 98.5% | 1532 | 98.6% | 98.2% |
| 2026Q1 | 1109 | 99.4% | 98.8% | 1502 | 99.1% | 98.5% |
| 2026Q2 | 1239 | 98.4% | 98.0% | 1579 | 97.5% | 97.1% |
| 2026Q3 | 1344 | 97.2% | 97.2% | 1675 | 96.1% | 96.0% |
| 2026Q4 | 873 | 11.0% | 10.4% | 1579 | 6.8% | 6.5% |

### 7.4 The parquet (`features_manifest`)

`ml/data_ext/event_features_10y.parquet`: 2,226,504 rows, key ['date', 'ticker'], columns ['sess_since_results', 'results_last_5', 'results_last_20', 'ear_3d', 'ear_vol_z', 'ann_count_20', 'rating_20', 'mgmt_change_60', 'orders_20', 'insolvency_60']; row set: identical to ml/data_10y/model_dataset.parquet (same order); sha256 `4656098ce1ec54e9...`; 72,835 release sessions.

| Column | NaN share |
|---|---:|
| `sess_since_results` | 15.5% |
| `results_last_5` | 11.1% |
| `results_last_20` | 12.7% |
| `ear_3d` | 24.0% |
| `ear_vol_z` | 24.5% |
| `ann_count_20` | 13.6% |
| `rating_20` | 13.6% |
| `mgmt_change_60` | 20.2% |
| `orders_20` | 13.6% |
| `insolvency_60` | 20.1% |

### 7.5 Point-in-time checks (`checks`)

- **Rebuild:** a second full build equals the parquet (2,226,504 rows; unchanged: True).
- **Re-parse from the raw zips:** 2488 files, 5,047,431 records re-parsed vs 5,047,431 stored; files with a digest mismatch: 0; equal: True.
- **100 random cells recomputed from files dated <= t:** 100/100 cells equal on all ten columns (mismatches by column: sess_since_results 0, results_last_5 0, results_last_20 0, ear_3d 0, ear_vol_z 0, ann_count_20 0, rating_20 0, mgmt_change_60 0, orders_20 0, insolvency_60 0; non-NaN cells by column: sess_since_results 84, results_last_5 87, results_last_20 87, ear_3d 74, ear_vol_z 73, ann_count_20 85, rating_20 85, mgmt_change_60 79, orders_20 85, insolvency_60 79). independent loop implementation of EVENTS.md section 4 (checks.recompute_cell) on the raw zips re-parsed with the fixed vocabulary, restricted to files dated <= t and prices dated <= t; the classification rules re-run on that restricted set; tolerance rtol 1e-5.
- **Stratified supplement (10 random cells per stratum):** 80/80 cells equal on all ten columns; rating_20>0: 10/10; orders_20>0: 10/10; insolvency_60==1: 10/10; mgmt_change_60>0: 10/10; results_last_5==1: 10/10; sess_since_results==0: 10/10; ear_vol_z finite: 10/10; ann_count_20>=5: 10/10 (mismatches by column: sess_since_results 0, results_last_5 0, results_last_20 0, ear_3d 0, ear_vol_z 0, ann_count_20 0, rating_20 0, mgmt_change_60 0, orders_20 0, insolvency_60 0).
- **Delete-the-future (2024-05):** files after the month-end and prices after it removed (1897 files and 1899 price sessions kept); 1,418,427 rows <= month-end compared, of which 28,962 in the month; cells differing: sess_since_results 0, results_last_5 0, results_last_20 0, ear_3d 0, ear_vol_z 0, ann_count_20 0, rating_20 0, mgmt_change_60 0, orders_20 0, insolvency_60 0; unchanged: True.
- **Shift test (T0 = 2020-02-14):** build on the 834 bundles up to T0, then with every later bundle appended; 370,772 rows <= T0 compared; cells differing: sess_since_results 0, results_last_5 0, results_last_20 0, ear_3d 0, ear_vol_z 0, ann_count_20 0, rating_20 0, mgmt_change_60 0, orders_20 0, insolvency_60 0; unchanged: True.
- **A/B join:** ml.improve.ab.load_frame(ml/data_10y, extra=ml/data_ext/event_features_10y.parquet): merge on date, ticker, validate one_to_one, row count unchanged; 2,226,504 rows, all ten columns present: True; family E in `ml/improve/ab.py` equals the parquet's columns: True; `ae1_events` resolves to 62 features (control 52; added: `sess_since_results`, `results_last_5`, `results_last_20`, `ear_3d`, `ear_vol_z`, `ann_count_20`, `rating_20`, `mgmt_change_60`, `orders_20`, `insolvency_60`); non-NaN share: sess_since_results 0.845, results_last_5 0.889, results_last_20 0.873, ear_3d 0.760, ear_vol_z 0.755, ann_count_20 0.864, rating_20 0.864, mgmt_change_60 0.798, orders_20 0.864, insolvency_60 0.799.

### 7.6 Descriptive rank IC (last step; `ic`)

**DESCRIPTIVE - not a pass mark; the Q6 pass mark is the primary A/B mark of ml/IMPROVEMENT_PLAN_2.md.** Target y_excess_20d (20-session next-open excess return vs the universe median); labelled and clean rows dated before the holdout's first test date 2026-08-03; per date with >= 50 names; Newey-West lag 20.

`ear_3d` among rows with sess_since_results <= 59 and a finite ear_3d: mean rank IC +0.0418, NW t 7.93, 1929 dates, 75% of dates positive.

| Year | Mean IC | NW t | Dates | Share positive |
|---|---:|---:|---:|---:|
| 2017 | +0.0231 | 1.52 | 62 | 68% |
| 2018 | +0.0542 | 3.48 | 246 | 74% |
| 2019 | +0.0589 | 3.33 | 245 | 82% |
| 2020 | +0.0355 | 1.82 | 252 | 68% |
| 2021 | +0.0504 | 3.89 | 248 | 82% |
| 2022 | +0.0633 | 7.82 | 37 | 100% |
| 2023 | +0.0411 | 2.70 | 211 | 75% |
| 2024 | +0.0451 | 4.59 | 236 | 80% |
| 2025 | +0.0167 | 1.57 | 249 | 63% |
| 2026 | +0.0298 | 2.25 | 143 | 74% |

Every family-E column over all rows with a value:

| Column | Mean IC | NW t | Dates | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sess_since_results` | +0.0216 | 4.58 | 1932 | -0.008 | +0.067 | +0.008 | +0.032 | +0.017 | +0.000 | -0.003 | +0.011 | +0.031 | +0.011 |
| `results_last_5` | -0.0123 | -4.60 | 1788 | -0.013 | -0.022 | +0.006 | -0.031 | -0.021 | -0.013 | -0.004 | -0.002 | -0.005 | -0.017 |
| `results_last_20` | -0.0064 | -1.55 | 1902 | -0.011 | -0.023 | +0.018 | -0.026 | -0.023 | +0.043 | -0.006 | +0.001 | +0.012 | -0.009 |
| `ear_3d` | +0.0418 | 7.93 | 1929 | +0.023 | +0.054 | +0.059 | +0.035 | +0.050 | +0.063 | +0.041 | +0.045 | +0.017 | +0.030 |
| `ear_vol_z` | +0.0296 | 6.87 | 1929 | +0.009 | +0.061 | +0.019 | +0.045 | +0.027 | +0.038 | +0.007 | +0.033 | +0.021 | +0.021 |
| `ann_count_20` | +0.0132 | 2.66 | 1905 | -0.032 | +0.035 | +0.026 | +0.005 | +0.001 | +0.064 | -0.003 | +0.010 | +0.036 | -0.014 |
| `rating_20` | -0.0075 | -2.30 | 1905 | -0.009 | -0.004 | -0.040 | -0.009 | -0.003 | +0.021 | -0.006 | -0.014 | +0.011 | +0.006 |
| `mgmt_change_60` | -0.0086 | -1.94 | 1785 | -0.056 | -0.009 | -0.011 | -0.032 | -0.016 | +0.016 | +0.005 | +0.008 | +0.016 | -0.013 |
| `orders_20` | -0.0008 | -0.22 | 1905 | +0.031 | -0.009 | -0.001 | -0.012 | +0.007 | +0.010 | +0.020 | +0.013 | -0.021 | -0.012 |
| `insolvency_60` | -0.0073 | -2.19 | 1691 | -0.008 | +0.001 | -0.017 | -0.015 | -0.012 | -0.035 | +0.009 | +0.001 | +0.001 | -0.010 |

### 7.7 Rule patterns as fixed (`classify.rules`)

| Class | Rule | Where | Patterns (case-insensitive regular expressions) |
|---|---|---|---|
| routine | RT1 | category | `^Declaration of NAV`; `^Trading Window`; `^Copy of Newspaper Publication`; `^Loss of Share Certificates?$`; `^Loss/Duplicate-Share Certificate$`; `^Issue of Duplicate Share Certificate$`; `^Certificate under SEBI \(Depositories and Participants\) Regulations`; `^Code of Conduct under SEBI ?\(PIT\)`; `^Structural Digital Database$`; `^Annual Secretarial Compliance Report`; `^Quarterly Compliance Report on Corporate governance`; `^Registrar & Share Transfer Agent Update$`; `^E-mail ID for Investor's Grievance Redressal$`; `^Interest Rates Updates$`; `^Disclosure of Unitholding pattern`; `^Disclosure of all complaints including SCORES`; `^Statement of deviation\(s\) or variation\(s\) under Reg\. ?32`; `^Monitoring Agency Report$`; `^Daily Buy-Back of equity shares$` |
| routine | RT2 | text, when the category is generic (Updates / General Updates / Others / none) | `news\s*paper\|advertisement\|publication of\|published in`; `loss of (the )?share certificates?\|duplicate share certificates?\|issue of duplicate`; `regulation\s*74\s*\(\s*5\s*\)\|depositories and participants`; `trading window`; `regulation\s*(7\s*\(\s*3\s*\)\|40\s*\(\s*(9\|10)\s*\)\|13\s*\(\s*3\s*\))`; `reconciliation of share capital\|investor complaints\|investor grievance`; `(change\|changes) in (the )?name of (the )?(registrar\|rta\|share transfer agent)\|link intime\|mufg intime`; `structural digital database\|secretarial compliance report\|compliance certificate` |
| results | R1 | category, and text not matching the results exclusions | `^Financial Results? Updates$`; `^Results$`; `^Results/Others$`; `^Publish Audited Results$`; `^Consolidated Result Updates - IFRS$`; `^Limited Review Report$`; `^Integrated Filing- ?Financial$` |
| results | R2 | category in ^Outcome of Board Meeting / ^Updates$ / ^General Updates$ / ^Press Release / ^Investor Presentation$ / ^Dividend$ / ^Others$ / ^$; text matches RESULTS_TEXT and not the exclusions | `financial\s*results?\|financial\s+statements?\s*/\s*results?\|\bresults?\s+(of the company\s+)?for\s+the\s+(quarter\|half\|year\|period\|nine\|first\|second\|third\|fourth\|q[1-4])\|\b(q[1-4]\|quarterly\|annual\|half[- ]yearly)\s+(fy\s*\d+\s+)?results?\b\|\bearnings release\b` |
| results | R2x | results exclusions (intimation, newspaper, calls, clarification, re-submission, delay) | `to\s+(inter[\s-]*alia\s*,?\s*)?consider\|will\s+be\s+(held\|considered)\|to\s+be\s+held\|is\s+scheduled\|scheduled\s+(on\|to\|for)\|(to\|will)\s+announce\|announce\w*\s+(the\s+)?(date\|schedule)\|intimation\s+of\s+(the\s+)?(date\|board\|meeting)\|intimation\s+(to\|under\|regarding\|about\|pursuant)\|prior\s+intimation\|board\s+meeting\s+intimation\|notice\s+of\s+(the\s+)?(board\s+)?meeting\|prior\s+notice\|news\s*paper\|advertis\|publication\|published\|publishing\|con(ference)?\.?\s*call\|earnings\s+call\|transcript\|recording\|audio\|video\|webcast\|investor\s+meet\|analyst\|non[-\s]*submission\|delay\|reasons\s+for\|clarification\|relaxation\|applicability\|option\s+to\s+submit\|rectif\|discrepanc\|corrigendum\|machine[\s-]*readable\|searchable\|re-?submi\|\brevis(ed\|ion)\b\|trading\s+window` |
| results | R3 | category ^Outcome of Board Meeting (or a generic category whose text is an outcome of a board meeting), not R1/R2, matched to a results-purpose board meeting intimated earlier for the same symbol: meeting date within 3 days of the 'held on' date in the text, or within the 7 days up to the file date when the text has no date | `outcome\s+of\s+(the\s+)?board\s+meeting\|board\s+meeting\s+outcome` |
| results | R4 | a board meeting intimated for financial results (board-meeting list of the bundles, or a Board Meeting Intimation record): the first session on or after the meeting date, if the intimation was filed on or before that date and not superseded before it by another intimated date or a cancellation / postponement record | `^Board [Mm]eeting (Cancelled\|Postponed\|Adjourned\|Deferred\|Rescheduled)` |
| results | RD | release session: a results session with another within the previous 5 sessions is the same release |  |
| rating | CR1 | category | `^Credit Rating` |
| rating | CR2 | text, generic category, not ESG / large-corporate boilerplate | `credit\s+rating\|rating\s+agenc\|\b(crisil\|icra\|care ratings\|india ratings\|brickwork\|acuite\|infomerics)\b.{0,80}\brating` |
| mgmt_change | M1 | category | `^Resignation`; `^Cessation`; `^Change in Management`; `^Change in Director`; `^Change in Directors/ ?Key Managerial`; `^Change in Auditors?`; `^Appointment of Auditors?`; `^Change in Company Secretary`; `^Change in\s+Managing Director`; `^Appointment of (Director\|Chairman\|Managing Director\|Chief\|Company Secretary\|Compliance Officer\|Independent)`; `^Retirement$`; `^Demise$` |
| mgmt_change | M2 | category Appointment and text names a director / KMP-level officer | `\b(director\|managing director\|chief executive\|ceo\|chief financial\|cfo\|company secretary\|compliance officer\|key managerial\|kmp\|chairman\|chairperson\|whole[- ]time\|auditors?\|chief operating\|coo\|president)\b` |
| mgmt_change | M3 | text, generic category: resignation / cessation of a director / KMP-level officer | `\b(resign(ation\|ed\|s)?\|cessation\|ceased\s+to\s+be)\b` |
| orders | O1 | category | `(Bagging\|Receiving\|Awarding).{0,20}(order\|contract)` |
| orders | O2 | text, generic or press-release category, not court / regulator / tax orders | `\b(receiv\w*\|receipt\s+of\|bag(s\|ged\|ging)?\|secur(ed\|es\|ing)\|wins?\|winning\|won\|award\w*)\b[^.]{0,80}\b(orders?\|contracts?\|loa\|loi)\b\|letter\s+of\s+(award\|acceptance\|intent)\|\bl-?1\s+bidder\|lowest\s+bidder` |
| orders | O2x | orders exclusions | `court\|tribunal\|nclt\|nclat\|\bsebi\b\|\btax\b\|income[- ]tax\|\bgst\b\|assessment\|penalt\|demand\s+notice\|show[- ]cause\|arbitra\|order\s+passed\|regulatory\|interim\s+order\|stay\s+order\|adjudicat\|order[-\s]+in[-\s]+original\|commissioner\|directorate\|enforcement\|credit\s+rating` |
| insolvency | IN1 | category | `^Corporate Insolvency Resolution Process`; `^BIFR$` |
| insolvency | IN2 | text, generic category | `corporate\s+insolvency\s+resolution\|\bcirp\b\|insolvency\s+and\s+bankruptcy\s+code\|interim\s+resolution\s+professional\|resolution\s+professional\|admitted.{0,60}(section\s*(7\|9\|10)\|insolvency)\|nclt.{0,60}admit` |

## 8. Verdict against the plan (added by the lead after the A/B; numbers from `ml/results/improve/ab/10y_p2/compare.json` and `books.json`)

**Q6 primary mark: FAIL.** AE1 (control + family E, 62 features) minus control over 103 folds: Δ CV-mean AUC -0.0008, paired 20-session block-bootstrap 95% CI [-0.0035, +0.0017], folds won 51/103, Δ rank IC -0.0004 (Newey-West t -0.2). CV AUC: control 0.5455, AE1 0.5447.

The two Q6 books (the trials) are the volatility+size-neutral top decile and the neutral liquid-tercile top decile: AE1 +11.2%/yr, IR +2.46 [+1.71, +3.20] and +3.6%/yr, IR +0.55 [-0.16, +1.28]; control +10.5%/yr, IR +2.32 and +1.2%/yr, IR +0.21. They are not a pass mark.

Reading (independent verification, `ml/results/improve2/IMPROVEMENT_RESULTS.md`): the earnings-announcement-return drift is real in the data (rank IC of `ear_3d` among names with results in the last 60 sessions +0.042, Newey-West t 7.9, positive every year), and about 17% of it is already spanned by the control's score. The incremental gain a model can extract is about +0.002 AUC at best (a post-hoc blend, descriptive only), below the +0.003 bar. The source has three coverage gaps (2022-02..2022-12, 2023-09/10, 2024-01) whose folds carry most of the negative point estimate. FAIL means "below the bar", not "no information".
