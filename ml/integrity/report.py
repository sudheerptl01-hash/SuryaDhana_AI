#!/usr/bin/env python3
"""integrity.json + INTEGRITY.md for P1 (JSON first; the Markdown only quotes the JSON).

Inputs: ml/results/improve/integrity/{sessions, corporate_actions, etf, write_phase_dryrun,
write_phase, v1_vs_v2}.json.  Pass marks (ml/IMPROVEMENT_PLAN.md, P1):
  I1 after the fix no session has > 5% of tickers with a prev_close mismatch, except
     mismatches explained by parsed corporate actions (re-scan of the written store);
  I2 parsed split/bonus ratios agree with the observed ex-date ratio within +-15% for
     >= 95% of events (disagreements listed);
  I3 flag_split_20d fires on fewer rows in v2 than in v1 and y_clean_20d coverage rises;
  I4 zero ETFs remain in the v2 universe (checked against the daily etf lists).

Run: python3 -I ml/integrity/report.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.integrity.common import OUT, wjson  # noqa: E402


def _load(name: str) -> dict:
    p = OUT / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def pct(x, d=2):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def build() -> dict:
    ses, ca, etf = _load("sessions"), _load("corporate_actions"), _load("etf")
    dry, wp, v2 = _load("write_phase_dryrun"), _load("write_phase_real"), _load("v1_vs_v2")
    reh, reh2, hist = _load("write_phase_rehearsal"), _load("write_phase_rehearsal_rerun"), \
        _load("history_special_sessions")
    cal = ses.get("calendar_audit", {})
    cont_after = wp.get("continuity_after", {})
    idem = {}
    if reh and reh2:
        keys = ["equity_eod_rows", "equity_eod_dates", "eq_be_rows", "eq_be_dup_date_ticker",
                "equity_features_rows", "adj_factor_ne_1_rows"]
        idem = {"first_run_after": {k: reh["after"][k] for k in keys},
                "second_run_after": {k: reh2["after"][k] for k in keys},
                "second_run_rows_deleted": reh2["upsert"]["rows_deleted"],
                "second_run_overwrites_existing_keys": reh2["overwrites_existing_keys"],
                "second_run_continuity_max_share": reh2["continuity_after"]["max_share"],
                "second_run_equal_to_dry_run": (reh2.get("dry_run_equality") or {}).get("identical")}
        idem["identical"] = idem["first_run_after"] == idem["second_run_after"] and \
            not any(idem["second_run_rows_deleted"].values())
    i1_before = {"max_share": max((r["share"] for r in ses.get("top10_share_before", [])), default=None),
                 "flagged": sorted(ses.get("flagged_before", {}))}
    i1 = {"rule": "no session with > 5% of tickers whose prev_close != stored previous close "
                  "(EQ/BE rows, |diff| > 0.005), except mismatches explained by parsed corporate actions",
          "before": i1_before,
          "after_store_rescan": {"max_share": cont_after.get("max_share"), "flagged": cont_after.get("flagged"),
                                 "top5": cont_after.get("top5")},
          "after_preview": ses.get("preview_after", {}).get("max_share")}
    i1["mismatch_rows_after"] = {"total": cont_after.get("mismatch_rows_total"),
                                 "on_a_parsed_corporate_action_ex_date": cont_after.get(
                                     "mismatch_rows_on_a_parsed_ex_date")}
    i1["pass"] = bool(cont_after) and not cont_after.get("flagged") and cont_after.get("max_share", 1) <= 0.05
    i2 = dict(ca.get("I2", {}))
    i2["disagreements"] = ca.get("disagreements", [])
    i2["after_ex_date_shift"] = ca.get("after_ex_date_shift")
    i3 = v2.get("I3", {})
    i4 = v2.get("I4", {})
    redated = ses.get("redated_sessions", {})
    added = ses.get("sessions_to_add", {})
    out = {
        "stream": "P1 data integrity (ml/IMPROVEMENT_PLAN.md section 2, P1)",
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "seed": 108,
        "pass_fail": {"I1": i1["pass"], "I2": i2.get("pass"), "I3": i3.get("pass"), "I4": i4.get("pass")},
        "I1": i1, "I2": i2, "I3": i3, "I4": i4,
        "sessions": {
            "flagged_by_continuity_scan_before": ses.get("flagged_before"),
            "added": added,
            "added_match_lead_list": ses.get("sessions_to_add_match_lead_list"),
            "redated": redated,
            "redate_evidence": [a for a in cal.get("actions", []) if a.get("action", "").startswith("re-date")],
            "calendar_vs_continuity": ses.get("calendar_vs_continuity"),
            "march_2022": ses.get("march_2022"),
            "coverage_repair": ses.get("coverage"),
            "upsert_rows": ses.get("upsert_rows"), "delete_dates": ses.get("delete_dates"),
            "candidates_checked": ses.get("candidates")},
        "calendar": {k: cal.get(k) for k in ("days", "pr_present", "pr_absent", "pr_unknown",
                                             "stored_dates_without_pr_bundle", "pr_bundle_dates_not_stored",
                                             "weekend_sessions", "weekday_closures", "holiday_list_vs_closures",
                                             "special_sessions_in_window", "trading_days_vs_pr_calendar",
                                             "stored_without_pr_unresolved")},
        "corporate_actions": {k: ca.get(k) for k in ("bc_stats", "records_by_kind", "adjustable_events",
                                                     "after_ex_date_shift", "shifted", "superseded",
                                                     "known_events", "known_events_all_found", "feed_rows",
                                                     "feed_by_kind", "price_break_flags", "completeness")},
        "etf": etf,
        "write_phase": {"dry_run": dry, **{k: wp.get(k) for k in (
            "started", "finished", "duration_seconds", "backup", "staging", "before", "overwrites_existing_keys",
            "upsert", "tables", "build_features", "after", "nestleind", "known_events", "continuity_after",
            "dry_run_equality")},
            "rehearsal_seconds": reh.get("duration_seconds"), "idempotency_check_on_a_copy": idem},
        "history_special_sessions_pr_check": hist,
        "exports": (v2.get("exports") or {}),
        "v1_vs_v2": v2,
        "findings_for_the_lead": [
            "nse_historical_ingest.parse_pr_zip, UDiFF branch: column names are upper-cased and then looked up "
            "in mixed case (TckrSymb, SctySrs, ...), so the UDiFF enrichment always fails and ISIN stays empty for "
            "every UDiFF day (2024-07 onward); not changed (outside P1's edit scope). The three legacy-era added "
            "sessions and the three re-dated ones carry ISIN from the CM bhavcopy; every other stored row has none.",
            "The archive serves the preceding special or moved session's file on the closures 2021-11-05, "
            "2023-06-29 and 2024-01-22, and the ingest's duplicate-day guard cannot catch it because that session "
            "was never stored; the calendar now lists those closures and the sessions are in SPECIAL_SESSIONS.",
            "The archive's security-wise files omit BE/BZ rows on 2022-03-07 and a growing set of BE securities "
            "(weekly from 2023-06-19, daily 2023-07-24..2023-08-24); rebuilt from the CM bhavcopy.",
            "The archive file PR060424.zip holds the 2024-06-04 bundle (day and month swapped); bundles are "
            "validated by the date in their member names.",
            "From mid-2025 the bc files write dates as yyyy-mm-dd instead of dd/mm/yyyy; both are parsed.",
            "On split/bonus-adjusted equity_features the universe price floor must use the raw close: v2 passes "
            "universe_price_col='close_unadj' (an adjusted close would let a future split remove past rows: "
            "7,806 rows of 50 tickers from 2022-10-03 have an adjusted close below Rs 10 but a raw close at or above "
            "it). This is the one addition to the briefed build call.",
            "amihud_20 in v2 uses adjusted-close returns (the v1 prep used raw closes); deliv_value_share_20 uses "
            "raw same-day prints as before.",
            "The label study's ETF name rule misses ETFs the etf files list and flags operating companies "
            "(GOLDTECH, JETFREIGHT; at store level also GOLDENTOBC and the rights entitlement JETFRE-RE).",
            "Unadjustable price breaks (rights, demergers, capital reductions, schemes) and unvalidated "
            "splits/bonuses are listed in ml/data_ext/price_break_flags.csv for label masking; v2 does not mask "
            "them beyond y_clean_20d.",
            "Backup of the pre-write store (1.42 GB): <session scratchpad>/rehearsal/nse_market_backup_pre_p1.duckdb; "
            "it can be deleted once the lead is satisfied."],
        "timings_seconds": {"sessions": ses.get("seconds"), "corporate_actions": ca.get("seconds"),
                            "etf": etf.get("seconds"), "dry_run": dry.get("seconds"),
                            "write_phase_lock_window": wp.get("duration_seconds"),
                            "rehearsal": reh.get("duration_seconds"),
                            "v2_build": (v2.get("seconds") or {}).get("total")},
        "outputs": {
            "code": "ml/integrity/",
            "corporate_actions_feed": "ml/data_ext/corporate_actions_feed.csv",
            "corporate_actions_all": "ml/data_ext/corporate_actions_all.csv",
            "price_break_flags": "ml/data_ext/price_break_flags.csv",
            "etf_list": "ml/data_ext/etf_list.csv", "equity_master": "ml/data_ext/equity_master.csv",
            "session_staging": "ml/data_ext/staging/sessions_upsert.parquet + sessions_delete.json",
            "exports_v2": "ml/results/improve/cache/{eod_export_v2.parquet, features_prices_export_v2.parquet}",
            "write_script": "ml/integrity/write_phase.py (idempotent; --extra-staging for ml/data_hist/ rows)",
            "v2_dataset": "ml/data_5y_v2/{model_dataset.parquet, manifest.json, splits.json}",
            "reports": "ml/results/improve/integrity/{integrity.json, INTEGRITY.md, sessions.json, "
                       "corporate_actions.json, etf.json, write_phase_real.json, write_phase_rehearsal*.json, "
                       "write_phase_dryrun.json, v1_vs_v2.json, history_special_sessions.json}",
            "raw_downloads": "ml/data_raw/pr/ (PR bundles; sec/, cm/, mto/, master/ check files; _manifest.csv)"},
    }
    wjson(OUT / "integrity.json", out)
    return out


def md(j: dict) -> str:
    pf = j["pass_fail"]
    word = lambda b: "PASS" if b else ("FAIL" if b is not None else "not evaluated")  # noqa: E731
    s = j["sessions"]
    ca = j["corporate_actions"]
    v2 = j.get("v1_vs_v2", {})
    cmp_ = v2.get("comparison", {})
    L = []
    L.append("# P1 data integrity: results")
    L.append("")
    L.append(f"Source of every number: `ml/results/improve/integrity/integrity.json` (built {j['built_at']}). "
             "Pre-registration: `ml/IMPROVEMENT_PLAN.md`, P1. Integrity criteria only; no model was trained.")
    L.append("")
    L.append("## Pass marks")
    L.append("")
    L.append("| Mark | Criterion | Result | Verdict |")
    L.append("|---|---|---|---|")
    i1 = j["I1"]
    L.append(f"| I1 | no session > 5% prev_close mismatches after the fix | before: max {pct(i1['before']['max_share'])} "
             f"({len(i1['before']['flagged'])} sessions flagged); after (written store): max "
             f"{pct(i1['after_store_rescan']['max_share'])}, flagged {i1['after_store_rescan']['flagged']} "
             f"({i1['mismatch_rows_after']['total']} mismatching rows in all, "
             f"{i1['mismatch_rows_after']['on_a_parsed_corporate_action_ex_date']} of them on a parsed "
             f"corporate-action ex-date) | **{word(pf['I1'])}** |")
    i2 = j["I2"]
    L.append(f"| I2 | split/bonus ratio within ±15% of observed for ≥ 95% of events | {i2.get('agree')} of "
             f"{i2.get('events')} = {pct(i2.get('rate'))} (listed ex-dates, no shift) | **{word(pf['I2'])}** |")
    i3 = j["I3"]
    L.append(f"| I3 | flag_split_20d falls and y_clean_20d rises (v2 vs v1) | flag_split_20d "
             f"{pct(i3.get('flag_split_20d_v1'), 3)} → {pct(i3.get('flag_split_20d_v2'), 3)}; y_clean_20d "
             f"{pct(i3.get('y_clean_20d_v1'))} → {pct(i3.get('y_clean_20d_v2'))} | **{word(pf['I3'])}** |")
    i4 = j["I4"]
    L.append(f"| I4 | zero ETFs in the v2 universe (daily etf lists) | {i4.get('v2_tickers_in_etf_union')} tickers in "
             f"the etf-file union; {i4.get('v2_rows_whose_ticker_is_in_that_dates_etf_file')} rows listed in that "
             f"date's etf file | **{word(pf['I4'])}** |")
    L.append("")
    # sessions
    L.append("## 1. Sessions")
    L.append("")
    L.append("**Added (six sessions the ingest never requested).** Each file's own DATE1 column names the "
             "session and none is an echo of the previous stored session.")
    L.append("")
    L.append("| Session | Rows (all series) | EQ+BE rows | ISIN enrichment |")
    L.append("|---|---:|---:|---|")
    for d, v in sorted((s.get("added") or {}).items()):
        L.append(f"| {d} | {v['rows']:,} | {v['rows_eq_be']:,} | {v['enrichment_file']} ({v['isin_filled_pct']}% ISIN) |")
    L.append("")
    if s.get("redated"):
        L.append("**Re-dated (mis-dated sessions found by the calendar audit).** On these closures the archive "
                 "serves the preceding special or moved session's file. The ingest had skipped that session, so its "
                 "duplicate-day guard compared the file with an older day and stored it under the closure's date.")
        L.append("")
        L.append("| Stored under | True session | Rows | Evidence |")
        L.append("|---|---|---:|---|")
        for a in s.get("redate_evidence", []):
            L.append(f"| {a['stored_copy']['stored_date']} | {a['session']} | {a['rows']:,} | file "
                     f"`{a['file_used']}` carries DATE1 = {a['session']}; stored rows identical to it; no PR bundle "
                     f"for {a['stored_copy']['stored_date']} |")
        L.append("")
    m = s.get("march_2022") or {}
    if m:
        L.append("**2022-03-08 (10.7% mismatch): the store is wrong because the archive file is partial.** "
                 f"`sec_bhavdata_full_07032022.csv` holds {m['archive_sec_file_rows_by_series']['2022-03-07']} and no "
                 "BE or BZ rows, while 2022-03-08 holds "
                 f"{m['archive_sec_file_rows_by_series']['2022-03-08']}. The stored 2022-03-07 rows equal the file "
                 f"exactly. All {m['mismatch_rows_2022-03-08']} mismatches on 2022-03-08 are BE tickers whose stored "
                 f"previous row is 2022-03-04 ({m['mismatch_stored_prev_date']}). Fix: the missing rows "
                 f"({m['rows_rebuilt_2022-03-07']}) are rebuilt from the CM bhavcopy `cm07MAR2022bhav.csv.zip` with "
                 "the security-wise conventions (VWAP = value/qty, turnover in lakh at 2 dp, delivery empty "
                 "for BE/BZ as everywhere in the store). The construction reproduces 2022-03-08's complete file "
                 "exactly on BE/BZ (every column max |diff| = 0). The rebuilt closes equal the prev_close "
                 f"that 2022-03-08 reports for {m['rebuilt_BE_close_vs_0308_prev_close']['equal_within_0.005']} of "
                 f"{m['rebuilt_BE_close_vs_0308_prev_close']['tickers']} BE tickers.")
        L.append("")
    cov = s.get("coverage_repair") or {}
    if cov:
        ab, aa = cov.get("audit_before", {}), cov.get("audit_after_preview", {})
        L.append(f"**Coverage repair.** Rule (fixed before the repair): {cov.get('rule')}. Before: "
                 f"{ab.get('sessions_ge_rule')} sessions met the rule ({ab.get('missing_total'):,} traded securities "
                 f"missing over all sessions, {ab.get('missing_close_ge_10_total'):,} of them priced ≥ ₹10). "
                 f"Repaired: {cov.get('n_sessions')} sessions, {cov.get('rows_rebuilt'):,} BE/BZ rows "
                 f"({cov.get('not_rebuilt_rows')} EQ call-auction rows, absent from the security-wise file on every "
                 f"session, left out). After: "
                 f"{aa.get('sessions_ge_rule')} sessions meet the rule, max {aa.get('max_missing')} missing on any "
                 f"session ({aa.get('missing_close_ge_10_total')} priced ≥ ₹10). The residual is penny stocks "
                 "the security-wise file never lists.")
        L.append("")
    c = j.get("calendar") or {}
    if c:
        L.append(f"**Calendar audit** ({c.get('days')} calendar days 2021-10-01..2026-10-16; a PR bundle exists on "
                 f"{c.get('pr_present')} days and is absent on {c.get('pr_absent')}; unknown: {c.get('pr_unknown')}). "
                 f"Weekend sessions: {c.get('weekend_sessions')}. Holiday list vs closures: "
                 f"{c.get('holiday_list_vs_closures')}. After the fix, `trading_days()` vs the PR calendar: "
                 f"{c.get('trading_days_vs_pr_calendar')}.")
        L.append("")
    # CA
    L.append("## 2. Corporate actions")
    L.append("")
    ae = ca.get("adjustable_events") or {}
    L.append(f"bc files: {ca.get('bc_stats')}. Records by kind: {ca.get('records_by_kind')}.")
    L.append("")
    L.append(f"Split/bonus/consolidation (ticker, ex-date) groups: {ae.get('ticker_exdate_groups')}; superseded by a "
             f"revised ex-date {ae.get('superseded_revised_ex_date')}; outside the stored price history "
             f"{ae.get('no_price_data_or_outside_store')}; evaluated {i2.get('events')}. **I2: {i2.get('agree')} agree = "
             f"{pct(i2.get('rate'))}** (bonus orientation flips {ae.get('bonus_orientation_flips')} of "
             f"{ae.get('bonus_events_evaluated')} bonus events). The feed holds {ca.get('feed_rows')} validated "
             f"events {ca.get('feed_by_kind')}. With the ex-date shift (an action effected 1 to 3 sessions away "
             f"from the listed date, accepted only when the listed date disagrees and the other session agrees): "
             f"{(ca.get('after_ex_date_shift') or {})}.")
    L.append("")
    L.append("Known events: " + "; ".join(
        f"{k['ticker']} {k['ex_date']} ratio {k['ratio']} (expected {k['expected_ratio']}, observed "
        f"{None if k['observed_ratio'] is None else round(k['observed_ratio'], 4)}) "
        f"{'found' if k['ratio_matches'] else 'NOT FOUND'}" for k in ca.get("known_events") or []) + ".")
    L.append("")
    L.append("Disagreements (listed ex-date; observed = open(ex)/close(ex−1)):")
    L.append("")
    L.append("| Ticker | Ex-date | Purpose | Ratio | Observed | close(ex−1) | open(ex) | Resolved by shift | Same-day unadjustable |")
    L.append("|---|---|---|---:|---:|---:|---:|---|---|")
    for d in i2.get("disagreements", []):
        L.append(f"| {d['ticker']} | {d['ex_date']} | {d['purpose'].replace(' | ', ' + ')} | {d['ratio_standard']:.4f} | "
                 f"{d['observed_ratio']:.4f} | {d['close_prev']} | {d['open_ex']} | {d['resolved_by_shift']} | "
                 f"{d['same_day_unadjustable'] or '-'} |")
    L.append("")
    comp = ca.get("completeness") or {}
    L.append(f"Completeness: {comp.get('corp_ind_with_abs_ret_gt_22pct')} (ticker, date) rows carry a CORP_IND code "
             f"in the pd file and |ret_1d| > 22%; {comp.get('covered_by_feed')} are in the feed; "
             f"{comp.get('n_missing')} are not, by bc kind on that date: {comp.get('missing_by_bc_kind')} "
             f"({comp.get('n_missing_without_any_bc_record')} without any bc record). All are listed in the JSON. "
             f"Unadjustable price breaks written to `price_break_flags.csv`: {ca.get('price_break_flags')}.")
    L.append("")
    # ETF
    e = j.get("etf") or {}
    v1e = e.get("v1_dataset", {})
    L.append("## 3. ETFs and equity master")
    L.append("")
    L.append(f"Union of the etf files: **{e.get('etf_symbols_union')} symbols**. In the v1 dataset: "
             f"{v1e.get('etf_by_list')} ETF tickers by the list ({pct(v1e.get('etf_row_share_by_list'))} of rows) vs "
             f"{v1e.get('etf_by_regex')} by the label study's name rule; regex only (not in any etf file): "
             f"{v1e.get('regex_only')}; list only (missed by the regex): {v1e.get('list_only')}. Equity master "
             f"(EQUITY_L.csv): {e.get('equity_master_rows')} listed equities, ISIN prefixes "
             f"{e.get('equity_master_isin_prefix')}.")
    L.append("")
    # write phase
    w = j.get("write_phase") or {}
    L.append("## 4. Write phase (the one read-write window on nse_market.duckdb)")
    L.append("")
    if w.get("duration_seconds") is not None:
        b, a, u = w.get("before") or {}, w.get("after") or {}, w.get("upsert") or {}
        L.append(f"Lock `ml/results/improve/LOCK_duckdb_write` held {w.get('started')} → {w.get('finished')}: "
                 f"**{w.get('duration_seconds')} s** (build_features {(w.get('build_features') or {}).get('seconds')} s; "
                 f"the backup copy was taken before the lock with the store's size and mtime verified unchanged). "
                 f"A rehearsal of the same procedure on a copy took {w.get('rehearsal_seconds')} s.")
        L.append("")
        L.append("| | Before | After |")
        L.append("|---|---:|---:|")
        L.append(f"| equity_eod rows | {b.get('equity_eod_rows'):,} | {a.get('equity_eod_rows'):,} |")
        L.append(f"| sessions | {b.get('equity_eod_dates'):,} | {a.get('equity_eod_dates'):,} |")
        L.append(f"| equity_features rows | {b.get('equity_features_rows'):,} | {a.get('equity_features_rows'):,} |")
        L.append(f"| EQ/BE (date, ticker) pairs stored twice | – | {a.get('eq_be_dup_date_ticker')} |")
        L.append(f"| rows with a split/bonus adjustment factor ≠ 1 | 0 | {a.get('adj_factor_ne_1_rows'):,} |")
        L.append("")
        L.append(f"Deleted (mis-dated) {u.get('rows_deleted')}; upserted {u.get('rows'):,} rows on {u.get('dates')} dates "
                 f"(existing keys overwritten: {w.get('overwrites_existing_keys')}); row count as expected: "
                 f"{a.get('row_count_as_expected')}. Tables written: {w.get('tables')}. equity_features equals the "
                 f"in-memory dry run: {(w.get('dry_run_equality') or {}).get('identical')}.")
        L.append("")
        ke = w.get("known_events") or {}
        L.append("Known corporate actions, adjusted vs raw close-to-close move on the ex-date:")
        L.append("")
        L.append("| Ticker | Ex-date | Adjusted move | Raw move | Largest adjusted daily abs(log move) in the series | Continuous |")
        L.append("|---|---|---:|---:|---:|---|")
        for t in ("NESTLEIND", "IRCTC", "TATASTEEL", "RELIANCE"):
            r = ke.get(t) or {}
            for d, v in (r.get("ex_dates") or {}).items():
                if v:
                    L.append(f"| {t} | {d} | {100 * v['adj_ret_ex']:+.2f}% | {100 * v['raw_ret_ex']:+.2f}% | "
                             f"{r['max_abs_log_ret_adjusted']:.3f} | {r['continuous']} |")
        L.append("")
        idem = w.get("idempotency_check_on_a_copy") or {}
        if idem:
            L.append(f"Idempotency (the write run twice on a copy): second run deleted "
                     f"{idem.get('second_run_rows_deleted')}, overwrote {idem.get('second_run_overwrites_existing_keys'):,} "
                     f"existing keys in place, and left every count identical ({idem.get('identical')}); "
                     f"equity_features still equal to the dry run: {idem.get('second_run_equal_to_dry_run')}. "
                     "The script takes `--extra-staging` (equity_eod-schema parquet, e.g. the 2016-2021 rows of "
                     "`ml/data_hist/`) and `--ca-csv` for the 10-year rebuild.")
            L.append("")
    ex = j.get("exports") or {}
    if ex:
        L.append("**Exports for the other streams** (same columns and types as the v1 exports): " + "; ".join(
            f"`{v['path'].split('SuryaDhana_AI/')[-1]}` {v['rows']:,} rows" for k, v in ex.items() if isinstance(v, dict))
            + ".")
        L.append("")
    # v2
    L.append("## 5. v2 dataset (`ml/data_5y_v2/`)")
    L.append("")
    if cmp_:
        a, b = cmp_["v1"], cmp_["v2"]
        L.append("| | v1 | v2 |")
        L.append("|---|---:|---:|")
        for k in ("rows", "tickers", "sessions", "labeled_rows", "labeled_clean_rows", "label_beat_mkt_20d_mean",
                  "label_up_5d_mean", "y_clean_20d_share", "flag_split_20d_rate", "etf_tickers_by_list",
                  "etf_rows_by_list"):
            fa, fb = a.get(k), b.get(k)
            f = (lambda x: f"{x:,}") if isinstance(fa, int) else (lambda x: f"{x:.5f}")
            L.append(f"| {k} | {f(fa)} | {f(fb)} |")
        L.append("")
        L.append(f"Features: {v2.get('n_features')} (v1's 50 + deliv_value_share_20, amihud_20; identical order: "
                 f"{v2.get('features_equal_v1_plus_suff')}). Common (date, ticker) rows: {cmp_.get('common_rows'):,}; "
                 f"rows only in v1: {cmp_.get('rows_only_v1'):,} (of which ETF: {cmp_.get('rows_only_v1_that_are_etf'):,}); "
                 f"rows only in v2: {cmp_.get('rows_only_v2'):,}. Fold boundaries vs v1: "
                 f"{v2.get('fold_boundaries_vs_v1')}.")
        L.append("")
        L.append("Per-feature differences on common rows. Groups: A = tickers with an adjusted corporate action; "
                 "B = other tickers before the first added session (2023-11-12); C = other tickers from then on.")
        L.append("")
        L.append("| Feature | max abs diff | share differing | A | B | C |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for f_, r in cmp_.get("per_feature", {}).items():
            g = r["share_differing_by_group"]
            L.append(f"| {f_}{' (cs)' if r['cross_sectional'] else ''} | {r['max_abs_diff']:.4g} | "
                     f"{pct(r['share_rows_differing'])} | {pct(g.get('A_ticker_with_adjusted_ca'))} | "
                     f"{pct(g.get('B_other_before_first_added_session'))} | "
                     f"{pct(g.get('C_other_from_first_added_session'))} |")
        L.append("")
        dB = {k: f"{100 * v:.3f}%" for k, v in (cmp_.get("per_ticker_features_differing_in_group_B") or {}).items()}
        L.append(f"Per-ticker features identical in group B: {cmp_.get('per_ticker_features_identical_in_group_B')}; "
                 f"differing in group B (share of group-B rows; these are the BE tickers whose 2022-03-07 and "
                 f"2023-06..08 rows were rebuilt, and window features of rows near the re-dated sessions): {dB}. "
                 "Cross-sectional columns (cs) differ almost everywhere because the universe lost its ETFs; "
                 "amihud_20 is a per-date z-score, so any change on a date moves every row of that date.")
        L.append("")
    L.append("## 6. Findings for the lead")
    L.append("")
    for f_ in j.get("findings_for_the_lead", []):
        L.append(f"- {f_}")
    L.append("")
    hs = j.get("history_special_sessions_pr_check") or {}
    if hs:
        L.append("History-stream special sessions confirmed by their PR bundles (member names carry the date): "
                 + ", ".join(f"{d} ({v['weekday']})" for d, v in hs.items() if v.get("inner_date_ok")) + ".")
        L.append("")
    L.append("## 7. Timings (seconds)")
    L.append("")
    L.append(str(j.get("timings_seconds")))
    L.append("")
    L.append("## 8. Outputs")
    L.append("")
    for k, v in j["outputs"].items():
        L.append(f"- {k}: `{v}`")
    L.append("")
    return "\n".join(L)


def _scrub(path: Path) -> None:
    """Replace the session-scratchpad prefix in a report file by a neutral placeholder."""
    import re
    t = path.read_text()
    t2 = re.sub(r"/tmp/[^\s\"']*?/scratchpad", "<session scratchpad>", t)
    if t2 != t:
        path.write_text(t2)


def main() -> int:
    for n in ("write_phase_real", "write_phase_rehearsal", "write_phase_rehearsal_rerun", "write_phase_dryrun"):
        if (OUT / f"{n}.json").exists():
            _scrub(OUT / f"{n}.json")
    j = build()
    (OUT / "INTEGRITY.md").write_text(md(j))
    _scrub(OUT / "integrity.json")
    _scrub(OUT / "INTEGRITY.md")
    print(json.dumps(j["pass_fail"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
