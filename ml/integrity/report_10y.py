#!/usr/bin/env python3
"""integrity_10y.json + INTEGRITY_10Y.md for the ten-year extension (JSON first; the Markdown quotes it).

Inputs (ml/results/improve/integrity/): corporate_actions_10y.json, etf_10y.json,
write_phase_hist.json, v2_vs_10y.json.  Marks re-applied to the extended window, with the
pre-registered rules of ml/IMPROVEMENT_PLAN.md (P1):
  I1 no session of the whole 2016-10..2026-10 store has > 5% of tickers with a prev_close mismatch;
  I2 split/bonus ratios agree with the observed ex-date ratio within +-15% for >= 95% of events,
     reported for 2016-10..2021-09 and for the whole feed.

Run: python3 -I ml/integrity/report_10y.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.integrity.common import OUT, wjson  # noqa: E402

SPLIT = "2021-10-01"


def _load(name: str) -> dict:
    p = OUT / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def pct(x, d=2):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def build() -> dict:
    ca, etf, wp, ds = _load("corporate_actions_10y"), _load("etf_10y"), _load("write_phase_hist"), _load("v2_vs_10y")
    cont = wp.get("continuity_after", {})
    win = ca.get("I2_by_window", {})
    hist_key = next((k for k in win if "<" in k), None)
    new_key = next((k for k in win if ">=" in k), None)
    i1 = {"rule": "no session of the whole store with > 5% of EQ/BE tickers whose prev_close != stored previous "
                  "close (|diff| > 0.005)",
          "max_share": cont.get("max_share"), "flagged": cont.get("flagged"), "top5": cont.get("top5"),
          "mismatch_rows_total": cont.get("mismatch_rows_total"),
          "mismatch_rows_on_a_parsed_ex_date": cont.get("mismatch_rows_on_a_parsed_ex_date")}
    i1["pass"] = bool(cont) and not cont.get("flagged") and (cont.get("max_share") or 1) <= 0.05
    i2 = {"rule": (ca.get("I2") or {}).get("rule"),
          "window_2016_10_to_2021_09": win.get(hist_key), "window_2021_10_to_2026_10": win.get(new_key),
          "whole_feed": ca.get("I2"), "by_ratio_strength": ca.get("I2_by_ratio_strength"),
          "after_ex_date_shift": ca.get("after_ex_date_shift")}
    i2["pass_2016_2021"] = bool((win.get(hist_key) or {}).get("pass"))
    i2["pass_whole"] = bool((ca.get("I2") or {}).get("pass"))
    dis = [d for d in ca.get("disagreements", []) if d["ex_date"] < SPLIT]
    after = wp.get("after", {})
    out = {
        "stream": "P1 data integrity, ten-year extension (2016-10..2026-10, with the P4 history rows)",
        "built_at": datetime.now().isoformat(timespec="seconds"), "seed": 108,
        "pass_fail": {"I1_10y": i1["pass"], "I2_2016_2021": i2["pass_2016_2021"], "I2_whole_feed": i2["pass_whole"]},
        "I1": i1, "I2": i2, "disagreements_2016_2021": dis,
        "corporate_actions": {k: ca.get(k) for k in ("bc_stats", "bundle_dirs", "records_by_kind", "adjustable_events",
                                                     "feed_rows", "feed_rows_by_window", "feed_by_kind",
                                                     "price_break_flags", "known_events", "shifted", "superseded",
                                                     "completeness")},
        "etf": etf,
        "write_phase": {k: wp.get(k) for k in ("started", "finished", "duration_seconds", "backup", "staging", "before",
                                                "overwrites_existing_keys", "upsert", "tables", "build_features",
                                                "after", "known_events", "features_from_boundary_vs_v2_export",
                                                "continuity_after")},
        "rows_from_2021_10_unchanged": after.get("rows_from_boundary_unchanged"),
        "history_calendar": after.get("history_calendar"),
        "dataset_10y": ds,
        "outputs": {"feed": "ml/data_ext/corporate_actions_feed_10y.csv",
                    "all_records": "ml/data_ext/corporate_actions_all_10y.csv",
                    "price_break_flags": "ml/data_ext/price_break_flags_10y.csv",
                    "etf_list": "ml/data_ext/etf_list_10y.csv",
                    "exports": "ml/results/improve/cache/{eod_export_10y.parquet, features_prices_export_10y.parquet}",
                    "dataset": "ml/data_10y/{model_dataset.parquet, manifest.json, splits.json}",
                    "reports": "ml/results/improve/integrity/{integrity_10y.json, INTEGRITY_10Y.md, "
                               "corporate_actions_10y.json, etf_10y.json, write_phase_hist.json, v2_vs_10y.json}"}}
    fill = _load("hist_fill")
    out["findings"] = [
        "The history stream's first final assembly lacked 2019-10-11, 2019-10-14 and 2019-10-15 (its parser dropped a "
        "day when the bc member had an over-long CSV row); it re-parsed them before setting final. P1's independent "
        f"CM + MTO construction (ml/integrity/hist_fill.py) reproduces P4's final rows exactly on the three re-parsed "
        f"days and their six neighbours ({fill.get('crosscheck_identical')}).",
        "A second archive mis-file: PR020118.zip holds the 2019-01-02 bundle (2018-01-02 is a session; its rows come "
        "from its CM file).",
        "Calendar: the 70 weekday closures of 2016-10..2021-09 were added to NSE_TRADING_HOLIDAYS; trading_days() now "
        "equals the stored sessions over the whole store (2016-10-03..2026-10-16), and --check-sessions reports 0 "
        "missing and 0 extra sessions.",
        "2016-2019 bc spellings now parsed: 'BON 1:3', 'BONUS2:1', 'BONUS 1.5:1', 'CONSOLIDATION-RE1 TO RS10', "
        "'INT RS 5/-', 'RET CAP' (capital reduction), 'SCH OF AGMT', 'BON 1 DVR : 4 EQ' (a bonus in another security: "
        "flagged, not adjusted); two different same-kind listings on one ex-date are treated as alternatives.",
        "Rows of the 118 non-equity series in the history parquet (bonds, gold bonds, funds, ...) were not loaded: the "
        "store keeps EQ/BE/BZ/SM/ST, as the ingest does.",
        "Backups of the store before each write are in the session scratchpad (rehearsal/nse_market_backup_pre_p1.duckdb, "
        "rehearsal/nse_market_backup_pre_hist.duckdb)."]
    wjson(OUT / "integrity_10y.json", out)
    return out


def md(j: dict) -> str:
    word = lambda b: "PASS" if b else "FAIL"  # noqa: E731
    i1, i2 = j["I1"], j["I2"]
    w = j["write_phase"]
    a = w.get("after") or {}
    b = w.get("before") or {}
    ds = j.get("dataset_10y") or {}
    L = ["# P1 data integrity: ten-year extension (2016-10..2026-10)", "",
         f"Source of every number: `ml/results/improve/integrity/integrity_10y.json` (built {j['built_at']}). "
         "History rows: stream P4 (`ml/data_hist/equity_eod_2016_2021.parquet`, CM bhavcopy + MTO delivery). "
         "Rules: `ml/IMPROVEMENT_PLAN.md`, P1 (I1, I2). No model was trained.", "",
         "## Pass marks on the extended window", "",
         "| Mark | Criterion | Result | Verdict |", "|---|---|---|---|"]
    L.append(f"| I1 (10 years) | no session > 5% prev_close mismatches | max {pct(i1.get('max_share'))}, flagged "
             f"{i1.get('flagged')} ({i1.get('mismatch_rows_total')} mismatching rows, "
             f"{i1.get('mismatch_rows_on_a_parsed_ex_date')} on a parsed ex-date) | **{word(j['pass_fail']['I1_10y'])}** |")
    h = i2.get("window_2016_10_to_2021_09") or {}
    n = i2.get("window_2021_10_to_2026_10") or {}
    wh = i2.get("whole_feed") or {}
    L.append(f"| I2 (2016-10..2021-09) | split/bonus within ±15% of observed, ≥ 95% | {h.get('agree')} of {h.get('events')} "
             f"= {pct(h.get('rate'))} | **{word(j['pass_fail']['I2_2016_2021'])}** |")
    L.append(f"| I2 (whole feed) | same | {wh.get('agree')} of {wh.get('events')} = {pct(wh.get('rate'))} "
             f"(2021-10..2026-10: {n.get('agree')} of {n.get('events')} = {pct(n.get('rate'))}) | "
             f"**{word(j['pass_fail']['I2_whole_feed'])}** |")
    L += ["", "## 1. Corporate actions 2016-10..2026-10", ""]
    c = j["corporate_actions"]
    ae = c.get("adjustable_events") or {}
    L.append(f"PR bundles from {c.get('bundle_dirs')}: {c.get('bc_stats')}. Split/bonus/consolidation (ticker, ex-date) "
             f"groups {ae.get('ticker_exdate_groups')}, evaluated {ae.get('evaluated')}; alternative listings resolved "
             f"{ae.get('groups_with_alternative_listings')}; superseded by a revised ex-date "
             f"{ae.get('superseded_revised_ex_date')}. Feed: {c.get('feed_rows')} validated events "
             f"{c.get('feed_rows_by_window')} by kind {c.get('feed_by_kind')}. Price-break flags: {c.get('price_break_flags')}.")
    L.append("")
    L.append("Disagreements with ex-dates in 2016-10..2021-09 (listed ex-date; observed = open(ex)/close(ex−1)):")
    L.append("")
    L.append("| Ticker | Ex-date | Purpose | Ratio | Observed | close(ex−1) | open(ex) | Resolved by shift | Same-day unadjustable |")
    L.append("|---|---|---|---:|---:|---:|---:|---|---|")
    for d in j.get("disagreements_2016_2021", []):
        obs = "n/a" if d.get("observed_ratio") is None else f"{d['observed_ratio']:.4f}"
        L.append(f"| {d['ticker']} | {d['ex_date']} | {d['purpose'].replace(' | ', ' + ')} | {d['ratio_standard']:.4f} | "
                 f"{obs} | {d['close_prev']} | {d['open_ex']} | {d['resolved_by_shift']} | {d['same_day_unadjustable'] or '-'} |")
    comp = c.get("completeness") or {}
    L += ["", f"Completeness over both windows: {comp.get('corp_ind_with_abs_ret_gt_22pct')} (ticker, date) rows with a "
              f"CORP_IND code and |ret_1d| > 22%; {comp.get('covered_by_feed')} in the feed; {comp.get('n_missing')} not, "
              f"by bc kind: {comp.get('missing_by_bc_kind')}.", ""]
    e = j.get("etf") or {}
    L.append(f"ETF list 10y: {e.get('symbols_union')} symbols ({e.get('symbols_2021_10_onward')} from 2021-10 on, "
             f"{e.get('symbols_2016_2021')} in 2016-2021, {e.get('only_2016_2021')} only in 2016-2021).")
    L += ["", "## 2. Write phase (10-year load)", ""]
    if w.get("duration_seconds") is not None:
        st = w.get("staging") or {}
        L.append(f"Lock held {w.get('started')} → {w.get('finished')}: **{w.get('duration_seconds')} s** "
                 f"(build_features {(w.get('build_features') or {}).get('seconds')} s). Staging: {st.get('p1_rows'):,} P1 rows "
                 f"(re-applied, unchanged) + {st.get('extra_rows'):,} history rows ({st.get('extra_file_stats')}).")
        L += ["", "| | Before | After |", "|---|---:|---:|",
              f"| equity_eod rows | {b.get('equity_eod_rows'):,} | {a.get('equity_eod_rows'):,} |",
              f"| sessions | {b.get('equity_eod_dates'):,} | {a.get('equity_eod_dates'):,} |",
              f"| equity_features rows | {b.get('equity_features_rows'):,} | {a.get('equity_features_rows'):,} |",
              f"| EQ/BE (date, ticker) pairs stored twice | – | {a.get('eq_be_dup_date_ticker')} |",
              f"| rows with an adjustment factor ≠ 1 | – | {a.get('adj_factor_ne_1_rows'):,} |", ""]
        ru = j.get("rows_from_2021_10_unchanged") or {}
        L.append(f"equity_eod rows dated from {ru.get('boundary')} unchanged by the load: **{ru.get('identical')}** "
                 f"(count, sums of close/volume/turnover/prev_close, sessions, tickers: {ru.get('after')}).")
        fv = w.get("features_from_boundary_vs_v2_export") or {}
        L.append(f"equity_features from 2021-10-01 vs the v2 export: raw columns identical {fv.get('raw_columns_identical')}; "
                 f"rows whose adjustment factor changed {fv.get('adjustment_factor_differs_rows')} "
                 f"(tickers {fv.get('adjustment_factor_differs_tickers')}); rows only in one {fv.get('rows_only_in_one')}.")
        hc = j.get("history_calendar") or {}
        mf = hc.get("misfiled_bundles") or {}
        L += ["", f"Sessions before 2021-10-01 vs the history PR calendar (bundle present, member names carrying its date): "
                  f"identical **{hc.get('identical')}**; stored but no bundle {hc.get('stored_not_in_pr_calendar')}; bundle but "
                  f"not stored {hc.get('pr_calendar_not_stored')}. Archive bundles holding another day (their own date "
                  f"is decided by its CM file instead): {mf}. Special sessions stored: {hc.get('special_sessions_stored')}.",
              ""]
        L.append("| Year | Stored sessions | PR calendar |")
        L.append("|---|---:|---:|")
        for y, v in (hc.get("sessions_by_year") or {}).items():
            L.append(f"| {y} | {v['stored']} | {v['pr_calendar']} |")
        ke = w.get("known_events") or {}
        L += ["", "Known corporate actions, adjusted vs raw close-to-close move on the ex-date:", "",
              "| Ticker | Ex-date | Adjusted move | Raw move | Largest adjusted daily abs(log move) | Continuous |",
              "|---|---|---:|---:|---:|---|"]
        for t, r in ke.items():
            if not isinstance(r, dict):
                continue
            for d, v in (r.get("ex_dates") or {}).items():
                if v:
                    L.append(f"| {t} | {d} | {100 * v['adj_ret_ex']:+.2f}% | {100 * v['raw_ret_ex']:+.2f}% | "
                             f"{r['max_abs_log_ret_adjusted']:.3f} | {r['continuous']} |")
        L.append("")
    L += ["## 3. Ten-year dataset (`ml/data_10y/`)", ""]
    if ds:
        d = ds["dataset"]
        L.append(f"{d['rows']:,} rows, {d['tickers']:,} tickers, {d['sessions']:,} sessions, {d['date_min']} to "
                 f"{d['date_max']}; {ds['n_features']} features (same names and order as v2: {ds['features_equal_v2']}) "
                 f"plus exit_date; {ds['folds']} monthly folds, embargo {ds['embargo_sessions']} sessions, holdout "
                 f"{ds['holdout']['test_start']}..{ds['holdout']['test_end']} (equal to v2: {ds['holdout_equal_v2']}). "
                 f"Label balance beat_mkt_20d {d['label_beat_mkt_20d_mean']:.4f}, up_5d {d['label_up_5d_mean']:.4f}; "
                 f"y_clean_20d share {pct(d['y_clean_20d_share'])}; flag_split_20d rate {pct(d['flag_split_20d_rate'], 3)}.")
        ff = ds["first_fold"]
        L.append("")
        L.append(f"First fold {ff['fold']['name']}: train_end {ff['fold']['train_end']}, {ff['train_rows']:,} rows "
                 f"({ff['train_labeled_clean_rows']:,} labeled and clean, {ff['train_sessions']} sessions). The v2 folds "
                 f"inside the 10-year list: {ds['v2_folds_identical_inside_10y']}. ETF check: "
                 f"{ds['etf']}.")
        cm = ds["comparison_v2_vs_10y"]
        L += ["", f"**v2 vs 10y on the common rows (date ≥ 2022-10-03):** {cm['common_rows']:,} common rows "
                  f"({cm['common_rows_before_2023_10_02']:,} before 2023-10-02); rows only in v2 {cm['rows_only_v2']}, "
                  f"only in 10y {cm['rows_only_10y']}. Identical features: {cm['identical_features']}.", "",
              "| Feature | share differing | before 2023-10-02 | from 2023-10-02 | max abs diff from 2023-10-02 | v2 NaN filled in 10y |",
              "|---|---:|---:|---:|---:|---:|"]
        for f_, r in cm["per_feature"].items():
            if r["share_differing"] == 0:
                continue
            L.append(f"| {f_} | {pct(r['share_differing'])} | {pct(r['share_differing_before_2023_10_02'])} | "
                     f"{pct(r['share_differing_from_2023_10_02'])} | {r['max_abs_diff_from_2023_10_02']:.3g} | "
                     f"{r['v2_nan_filled_in_10y']:,} |")
        L.append("")
        L.append("Why the differing columns differ: the store now starts in 2016-10 instead of 2021-10, so (i) long "
                 "windows that v2 could not fill for names with little history (ret_252d, mom_12_1, ret_126d, ret_63d, "
                 "dist_200dma) now have values; (ii) the exponentially weighted features (rsi_14, macd_norm, atr_pct) "
                 "start five years earlier, a difference that has decayed to the 1e-4 level by 2023-10; (iii) "
                 "cs_rank_ret_126 ranks over the filled ret_126d values; (iv) no adjustment factor differs from 2021-10 "
                 "on (the merged feed equals the v2 feed there, and the write phase found 0 rows with a changed factor).")
        L.append("")
    L += ["## 4. Findings", ""] + [f"- {f_}" for f_ in j.get("findings", [])] + [""]
    L += ["## 5. Outputs", ""] + [f"- {k}: `{v}`" for k, v in j["outputs"].items()] + [""]
    text = "\n".join(L).replace(str(Path(__file__).resolve().parents[2]) + "/", "")
    return re.sub(r"/tmp/[^\s\"']*?/scratchpad", "<session scratchpad>", text)


def main() -> int:
    j = build()
    (OUT / "INTEGRITY_10Y.md").write_text(md(j))
    t = (OUT / "integrity_10y.json").read_text()
    (OUT / "integrity_10y.json").write_text(re.sub(r"/tmp/[^\s\"']*?/scratchpad", "<session scratchpad>", t))
    print(json.dumps(j["pass_fail"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
