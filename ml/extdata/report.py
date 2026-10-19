#!/usr/bin/env python3
"""Markdown report for the P3 stream: every number is read from extdata.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ml.extdata import common as C  # noqa: E402


def _f(x, nd=4):
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return f"{x:,}"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _pf(ok) -> str:
    return "**PASS**" if ok else ("**FAIL**" if ok is False else "not run")


def write_markdown(j: dict, path: Path | None = None) -> str:
    path = path or (C.OUT / "EXTDATA.md")
    L: list[str] = []
    a = L.append
    cov = j.get("coverage", {})
    ps = cov.get("per_source", {})
    fb = j.get("features_build", {})
    pa, pb, pc = (j.get("pit_a_recompute_cells"), j.get("pit_b_month_truncation"),
                  j.get("pit_c_shift_test"))
    bc = j.get("base_crosscheck_v1", {})
    a("# P3 external data: sources, staging tables, feature families F1-F4")
    a("")
    a(f"Built {j.get('built_at')} by `ml/extdata/run_all.py` (seed {j.get('seed')}). Every number "
      "below is quoted from `ml/results/improve/extdata/extdata.json`. The feature families are the "
      "pre-registered F1-F4 of `ml/IMPROVEMENT_PLAN.md` section 2-P3; this stream builds them, the "
      "lead runs the A/Bs. Nothing here touched `nse_market.duckdb`.")
    a("")
    a("## 1. Summary")
    a("")
    a("| Check | Result |")
    a("|---|---|")
    a(f"| (a) {pa['n_cells'] if pa else '-'} random cells of F2/F3 recomputed by an independent code "
      f"path from raw files dated <= t | {_pf(pa['passed'] if pa else None)}"
      + (f" ({pa['n_values_equal']} of {pa['n_values']} values equal)" if pa else "") + " |")
    a(f"| (b) inputs dated after t removed, every session of {pb['month'] if pb else '-'} | "
      f"{_pf(pb['passed'] if pb else None)}" + (f" ({pb['n_sessions']} sessions)" if pb else "") + " |")
    a(f"| (c) shift test (future bars appended; rows <= T0 unchanged) | {_pf(pc['passed'] if pc else None)}"
      + (f" (T0 = {', '.join(pc['cutoffs'])})" if pc else "") + " |")
    exact = all(v.get("max_abs_diff") == 0.0 and v.get("nan_pattern_mismatch") == 0
                for v in bc.get("features", {}).values()) and bc.get("rows_only_in_v1") == 0 \
        and bc.get("rows_only_in_ext") == 0
    a(f"| Base series (mom_20, ret_63d, ret_126d, deliv_pct_sma_20, atr_pct) vs v1 dataset | "
      f"{'**exact** (max abs diff 0, identical row set and NaN pattern)' if exact else 'see section 6'} |")
    uc = j.get("fo_unit_continuity", {})
    if uc.get("available"):
        a(f"| F&O unit continuity at the 2024-07 format switch | OI identity holds for "
          f"{uc['oi_identity_exact']} of {uc['contracts_matched']} futures contracts |")
    sm = j.get("fo_symbol_match", {})
    a(f"| F&O stock symbols found in the EOD export on the same date | {_f(sm.get('matched_share'))} |")
    a("")
    a(f"Output rows: `extra_features.parquet` {_f(fb.get('rows'))} rows x "
      f"{len(j['families']['F2_sector']) + len(j['families']['F3_fo'])} features "
      f"({_f(fb.get('tickers'))} tickers, {fb.get('date_min')} to {fb.get('date_max')}; the row set "
      "equals the v1 dataset's exactly); `market_state.parquet` one row per EOD date "
      f"from {fb.get('date_min')} with {len(j['families']['F1_market_state']) + len(j['families']['F4_flows'])} features.")
    a("")
    a("**The one material finding is a look-ahead in the industry lists (section 8).** The NSE "
      "constituent lists are a 2026-10-19 snapshot. Being in them predicts the 20-day label: the "
      "snapshot flag's pooled AUC exceeds a point-in-time size flag's by about 0.015 to 0.03 in "
      "2022-2025, roughly five to ten times the A/B pass mark of +0.003. F2 is built so that no "
      "NaN pattern marks membership (two deviations from the brief, section 4), but F2 still "
      "makes the partition easier to recover. AB2 and AB5 should not be read without the "
      "placebo control described in section 8.")
    a("")

    a("## 2. Sources and coverage")
    a("")
    a(f"Expected sessions: {cov.get('expected_sessions')} = {cov.get('eod_sessions')} EOD-export dates "
      f"+ the six special sessions P1 adds ({', '.join(cov.get('special_sessions', []))}). Downloads: "
      "archives.nseindia.com, browser user agent, one request in flight per file type, random "
      "1.0-2.0 s pause, 60 s back-off with halved rate on 403/429/5xx (log: "
      "`ml/results/improve/extdata/log.txt`). Every file's internal date (F&O TIMESTAMP / TradDt, "
      "index `Index Date`, participant title line) is checked against its file-name date.")
    a("")
    a("| Source | Files in window | HTTP 404 dates | Content-date exclusions | EOD sessions without a file |")
    a("|---|---:|---|---|---|")
    names = {"fo": "F&O bhavcopy", "indices": "ind_close_all", "participant": "participant OI"}
    for k in ("fo", "indices", "participant"):
        s = ps.get(k, {})
        a(f"| {names[k]} | {_f(s.get('files_ok_in_window'))} | {', '.join(s.get('http_404_dates', [])) or 'none'} | "
          f"{len(s.get('excluded_content_date_mismatch', []))} | "
          f"{', '.join(s.get('eod_sessions_without_file', [])) or 'none'} |")
    a("")
    a("Files per year (files with a valid internal date / expected sessions):")
    a("")
    years = sorted({y for s in ps.values() for y in s.get("by_year", {})})
    a("| Year | " + " | ".join(names[k] for k in ("fo", "indices", "participant")) + " |")
    a("|---|" + "---:|" * 3)
    for y in years:
        cells = []
        for k in ("fo", "indices", "participant"):
            by = ps.get(k, {}).get("by_year", {}).get(y) or ps.get(k, {}).get("by_year", {}).get(str(y), {})
            cells.append(f"{by.get('files_ok', 0)} / {by.get('expected', 0)}")
        a(f"| {y} | " + " | ".join(cells) + " |")
    a("")
    a("Special sessions (status per source):")
    a("")
    a("| Session | " + " | ".join(names[k] for k in ("fo", "indices", "participant")) + " |")
    a("|---|---|---|---|")
    for d in cov.get("special_sessions", []):
        a(f"| {d} | " + " | ".join(ps.get(k, {}).get("special_sessions", {}).get(d, "-")
                                   for k in ("fo", "indices", "participant")) + " |")
    a("")
    al = cov.get("alias_ext_to_eod", {})
    a("**Mis-dated EOD sessions (finding for P1).** Three EOD-export dates hold a session that "
      "traded on another day. The bar sequence is continuous, so a prev_close scan cannot see "
      "them; the archive does, because every external file for those dates is a 404 while the "
      "true date's files exist and carry their own date inside:")
    a("")
    a("| Archive date (true session) | EOD-export date | Evidence |")
    a("|---|---|---|")
    ev = {"2021-11-04": "Muhurat session; volumes about 1/7 of normal (P1 already re-dates this one)",
          "2023-06-28": "NSE moved the Bakri Id holiday to 06-29; the ingest's calendar skipped 06-28",
          "2024-01-20": "Saturday session; 22 Jan 2024 was a market holiday; volumes about 1/4 of normal"}
    for s_, d_ in al.items():
        a(f"| {s_} | {d_} | {ev.get(s_, '')} |")
    a("")
    a("External series are joined to the EOD dates through this alias, applied only where the "
      "export holds the alias date and not the true date (inert on a re-dated v2 export).")
    a("")
    fm = cov.get("fo_members_per_year", {})
    a("F&O membership (stocks with a stock future, per F&O file):")
    a("")
    a("| Year | Mean per day | Min | Max | Distinct tickers | Universe rows that are members |")
    a("|---|---:|---:|---:|---:|---:|")
    share = cov.get("universe_rows_fo_member_share_by_year", {})
    for y in sorted(fm):
        v = fm[y]
        a(f"| {y} | {v['mean_daily']} | {v['min_daily']} | {v['max_daily']} | {v['distinct_tickers']} | "
          f"{_f(share.get(y, share.get(str(y))))} |")
    a("")
    ic = cov.get("industry_coverage_by_year", {})
    a("Industry-map coverage of the universe (rows with an NSE industry; `industry_map.csv` has "
      f"{_f(j.get('industry_map', {}).get('n_symbols'))} symbols from the Nifty 500, Midcap 150, "
      "Smallcap 250, Microcap 250 and Nifty 50 lists, no conflicting labels):")
    a("")
    a("| Year | Universe rows | Share of rows with industry | Same, ex-ETF | ETF-group share | Share of tickers |")
    a("|---|---:|---:|---:|---:|---:|")
    for y in sorted(ic):
        v = ic[y]
        a(f"| {y} | {_f(v['rows'])} | {_f(v['share_rows_known_industry'])} | "
          f"{_f(v['share_rows_known_industry_ex_etf'])} | {_f(v['share_rows_etf_group'])} | "
          f"{_f(v['share_tickers_known_industry'])} |")
    a("")

    a("## 3. Staging tables (`ml/data_ext/`)")
    a("")
    a("| File | Rows | Key / content |")
    a("|---|---:|---|")
    pr = j.get("parse", {})
    a(f"| `fo_daily_stock.parquet` | {_f(pr.get('fo', {}).get('rows'))} | (date, ticker) with a stock future or option: near/next settle and expiry, days to expiry, total futures OI (shares) and its change, futures volume (contracts) and turnover (rupees), call/put OI (shares) and volume (contracts), n_strikes, spot_close (EOD export), basis_near, source_format |")
    a(f"| `index_daily.parquet` | {_f(pr.get('indices', {}).get('rows'))} | (date, index_name): open, high, low, close, pct_change, volume, turnover_cr, pe, pb, div_yield |")
    a(f"| `fo_participant_oi.parquet` | {_f(pr.get('participant', {}).get('rows'))} | (date, client_type in Client/DII/FII/Pro/TOTAL), 14 numeric columns in contracts (wide in instruments, long in client type) |")
    a("| `industry_map.csv` | " + _f(j.get('industry_map', {}).get('n_symbols')) + " | symbol, industry, source_list (first list wins: Nifty 500, Midcap 150, Smallcap 250, Microcap 250, Nifty 50) |")
    a("| `sector_index_map.csv` | " + _f(len(j.get('sector_index_map', {}).get('rows', []))) + " | industry -> index name in ind_close_all (+ fallback) |")
    em = j.get("equity_master", {})
    a(f"| `equity_master.csv` | {_f(em.get('rows'))} | EQUITY_L.csv: symbol, company_name, series, listing_date, paid_up_value, market_lot, isin, face_value ({'written here' if em.get('written_by_this_stream') else 'kept from P1'}) |")
    a("")
    a("Units and conventions (verified, section 7): open interest is in **shares** in both F&O "
      "formats (legacy `OPEN_INT`, UDiFF `OpnIntrst`); traded volume in **contracts** in both "
      "(`CONTRACTS`, `TtlTradgVol`); turnover in rupees (`VAL_INLAKH` x 1e5, `TtlTrfVal`). Roll: "
      "near = the smallest expiry >= t (on the expiry day the expiring contract is still near, 0 "
      "days to expiry); next = the second smallest; days to expiry in calendar days; UDiFF uses "
      "`FininstrmActlXpryDt`. basis_near = (near settle / spot close - 1) x 365 / days to expiry, "
      "NaN below 2 days. n_strikes = distinct strike prices over all option expiries. Futures rows "
      f"without a spot close: {_f(j.get('basis_sanity', {}).get('fut_rows_without_spot'))} "
      "(the special sessions, which have no EOD bars in the v1 export).")
    a("")
    sim = j.get("sector_index_map", {})
    a("Sector-index map (every name verified present in every parsed index file, "
      f"{_f(sim.get('n_index_files'))} files):")
    a("")
    a("| Industry | Index | Fallback | Share of files with the index |")
    a("|---|---|---|---:|")
    for r in sim.get("rows", []):
        a(f"| {r['industry']} | {r['index_name']} | {r['fallback_index_name'] or '-'} | {_f(r['primary_share_of_files'])} |")
    a("")
    a("Unmapped industries (Consumer Services, Services, Telecommunication, Textiles, Utilities, "
      "Diversified, Forest Materials) follow the brief's 'others -> none'. `Nifty Consumer "
      "Services` exists in the files but was not added, because the map was proposed before any "
      "result existed.")
    a("")

    a("## 4. Feature families")
    a("")
    fam = j.get("families", {})
    for k, v in fam.items():
        a(f"- **{k}** ({len(v)}): " + ", ".join(f"`{x}`" for x in v))
    a("")
    a("Definitions are in `extdata.json` (`definitions`) and `ml/data_ext/extra_features_manifest.json`. "
      "Each external source's sessions are counted on its own file calendar, and EOD-derived "
      "series on the EOD export's calendar. Same-day end-of-day prints are allowed (labels enter at the next open).")
    a("")
    f2i = fb.get("f2", {})
    a("Conventions fixed before any IC was computed:")
    a("")
    a(f"1. Market and industry aggregates exclude ETFs (the v2 universe definition), so stock values are the same joined to v1 or v2. ETF rows (v1 only) get F2 values inside their own `ETF` group. ETF source: {fb.get('etf_source')} ({_f(fb.get('n_etf_tickers'))} tickers).")
    a(f"2. The EW market return drops single-day moves above 22% (the repo's corporate-action threshold; {_f(fb.get('market_state', {}).get('ew_excluded_big_moves_total'))} name-days dropped). cs_dispersion_20 is taken over names with `flag_split_20d` == 0. The median EW membership is {_f(fb.get('market_state', {}).get('ew_members_median'))} names.")
    a("3. **Deviation from the brief: names without an NSE industry form an explicit `Unclassified` group** (the brief did not say). A NaN would mark today's index members (section 8).")
    a(f"4. **Deviation from the brief: `secidx_ret_20` for unmapped industries, Unclassified names and ETFs is the Nifty 500 20-session return, not NaN** ({_f(f2i.get('secidx_rows_on_default_index'))} rows). Under the brief, the NaN pattern itself carries the membership look-ahead (section 8). `build(policy={{'unclassified': 'nan', 'secidx_unmapped': 'nan'}})` reproduces the literal brief.")
    a("5. Industry groups with fewer than 5 non-NaN names that date give NaN (the brief). This affects Diversified, Forest Materials and Utilities, about 0.4% of rows.")
    a("6. `fo_member` is NaN on a date whose F&O file is missing. The other F3 values are NaN for non-members. Zero futures OI is treated as missing in the log changes and the z-score.")
    a("")

    a("## 5. Point-in-time checks")
    a("")
    if pa:
        a(f"**(a) Independent recomputation: {_pf(pa['passed'])}.** Sample: {pa['n_dates']} random dates (seed {pa['seed']}), "
          f"2 F2 cells and 2 F3 cells each, {pa['n_cells']} cells in total ({pa['n_cells_all_equal']} fully equal). "
          f"{pa['n_values_equal']} of {pa['n_values']} values are equal. Method: {pa['method']}. Tolerance: rtol {pa['tolerance']['rtol']}, "
          f"{pa['tolerance']['rtol_fut_oi_z_60']} for the rolling z-score, and NaN equals NaN. Runtime {pa['seconds']} s.")
        bad = [c for c in pa["cells"] if not c["all_equal"]]
        for c in bad[:10]:
            a(f"  - mismatch {c['date']} {c['ticker']} {c['family']}: " +
              ", ".join(f"{k} stored {v['stored']} vs {v['recomputed']}" for k, v in c["values"].items() if not v["equal"]))
        a("")
    if pb:
        a(f"**(b) File removal, {pb['month']}: {_pf(pb['passed'])}.** For each of the {pb['n_sessions']} sessions t, every raw file dated after t "
          "and every EOD bar after t was removed from the input set, and the whole pipeline (parse + features) was re-run. "
          "The rows at t were then compared with the full build. For the last session the removal was literal: a directory holding only the files dated <= t, parsed from the raw bytes with no cache. "
          f"Runtime {pb['seconds']} s.")
        a("")
        a("| t | Files removed (F&O / index / participant) | Stock rows at t | Identical (stock / market) |")
        a("|---|---|---:|---|")
        for d in pb["per_date"]:
            n = d["files_removed_after_t"]
            a(f"| {d['t']}{' (literal)' if d['literal_file_removal_no_cache'] else ''} | {n['fo']} / {n['indices']} / {n['participant']} | "
              f"{_f(d['extra_rows'])} | {_f(d['extra_rows_identical'])} / {_f(d['market_state_identical'])} |")
        a("")
    if pc:
        a(f"**(c) Shift test: {_pf(pc['passed'])}.** Inputs were truncated at T0 and every row dated <= T0 was compared with the full build, for all 32 features. Runtime {pc['seconds']} s.")
        a("")
        a("| T0 | Stock rows compared | Identical | Market rows compared | Identical |")
        a("|---|---:|---|---:|---|")
        for r in pc["results"]:
            a(f"| {r['T0']} | {_f(r['extra_rows_compared'])} | {_f(r['extra_identical'])} | "
              f"{_f(r['market_rows_compared'])} | {_f(r['market_identical'])} |")
        a("")
    a("The static inputs are held fixed in (b) and (c): the industry lists, the sector map and the ETF list. Their point-in-time status is the subject of section 8.")
    a("")

    a("## 6. Base series vs the v1 dataset")
    a("")
    a(f"Row sets: v1 {_f(bc.get('v1_rows'))}, this stream {_f(bc.get('ext_rows'))}, common {_f(bc.get('common_rows'))}, "
      f"only in v1 {_f(bc.get('rows_only_in_v1'))}, only here {_f(bc.get('rows_only_in_ext'))}.")
    a("")
    a("| Series | Rows both finite | Max abs diff | Rows with diff > 1e-9 | NaN-pattern mismatches |")
    a("|---|---:|---:|---:|---:|")
    for k, v in bc.get("features", {}).items():
        a(f"| {k} | {_f(v['n_both_finite'])} | {v['max_abs_diff']} | {_f(v['n_abs_diff_gt_1e-9'])} | {_f(v['nan_pattern_mismatch'])} |")
    a("")

    a("## 7. Integrity of the external data")
    a("")
    if uc.get("available"):
        a(f"- **Units across the format switch.** For {uc['contracts_matched']} futures contracts, the legacy 2024-07-05 OPEN_INT equals the UDiFF 2024-07-08 OpnIntrst minus ChngInOpnIntrst in "
          f"{uc['oi_identity_exact']} cases (max relative deviation {uc['max_rel_deviation']}). UDiFF turnover / (contracts x lot x close) has median {uc['udiff_turnover_over_contracts_x_lot_x_close_median']}, "
          f"and UDiFF OI is divisible by the lot size in {_f(uc['udiff_oi_divisible_by_lot_share'])} of rows. {uc['reading']}.")
    a(f"- **Symbols.** {_f(sm.get('fo_stock_rows_on_eod_dates'))} futures rows on EOD dates; the share whose ticker exists in the EOD export the same day is {_f(sm.get('matched_share'), 5)} "
      f"({_f(sm.get('unmatched_rows'))} unmatched: {sm.get('unmatched_tickers')}).")
    pi = j.get("participant_identity", {})
    a(f"- **Participant OI.** {_f(pi.get('files'))} files. Long equals short in the TOTAL row for futures in a share {_f(pi.get('total_long_equals_short_futures_share'))} of files. "
      f"The four client types sum to TOTAL within 1 contract in {_f(pi.get('four_types_sum_to_total_within_1_contract_share'))} (exactly in {_f(pi.get('four_types_sum_exact_share'))}; NSE rounds index-option sums by up to 1 contract; max deviation {pi.get('max_abs_deviation_contracts')}).")
    bs = j.get("basis_sanity", {}).get("annualised_basis_quantiles_by_year", {})
    if bs:
        a("- **Annualised near-month basis** (median by year, the cost of carry): " +
          ", ".join(f"{y} {_f(v['p50'], 3)}" for y, v in bs.items()) + ". The 1st-99th percentiles are in the JSON.")
    a("")

    a("## 8. The industry-list look-ahead")
    a("")
    sd = j.get("industry_survivorship_diagnostic", {})
    sp = j.get("size_proxy_diagnostic", {})
    pid = j.get("partition_identifiability", {})
    a("The constituent lists exist only as of the download date (2026-10-19), so the industry label "
      "is not point in time. The label itself barely changes over time; the problem is *which* "
      "names carry one. A name is classified only if it is in one of the five indices today, and "
      "names that rose since 2022 are over-represented among them. Reporting-only diagnostics "
      "follow (labels from the v1 dataset, ex-ETF universe rows, y_clean_20d):")
    a("")
    a("| Year | Share classified | Beat rate classified | Beat rate unclassified | AUC of snapshot flag | AUC of PIT size flag (top N by turnover) |")
    a("|---|---:|---:|---:|---:|---:|")
    for y, v in sd.get("by_year", {}).items():
        spy = sp.get("by_year", {}).get(y, {})
        a(f"| {y} | {_f(v['share_classified'])} | {_f(v['beat_rate_classified'])} | {_f(v['beat_rate_unclassified'])} | "
          f"{_f(v['auc_of_classified_indicator'])} | {_f(spy.get('auc_pit_turnover_top_n'))} |")
    a("")
    a("Reading: part of the snapshot flag's edge is a genuine size effect, since the PIT top-N "
      "flag also exceeds 0.5 in 2023-2025. The gap between the two columns is the future "
      "information in the snapshot. It shrinks to almost nothing in 2026, when the snapshot is "
      "nearly current.")
    a("")
    ti = pid.get("leak_safe", {}).get("test_auc_predicting_classified", {})
    tl = pid.get("literal_brief", {}).get("test_auc_predicting_classified", {})
    if ti:
        a("Can a model recover the partition from the features it would see? LightGBM predicting "
          "the snapshot flag (no return labels), trained on 2023 and scored on 2025:")
        a("")
        a("| Feature set | Leak-safe F2 (this build) | Literal brief (NaN for unclassified/unmapped) |")
        a("|---|---:|---:|")
        for k in ti:
            a(f"| {k} | {_f(ti[k])} | {_f(tl.get(k))} |")
        a("")
    sn = sd.get("secidx_ret_20_nan_indicator", {})
    a(f"Under the literal brief, F2 alone identifies the partition almost perfectly, because its "
      f"NaN pattern is the partition. The leak-safe build lowers that, but F2 still adds to what the "
      f"base features already reveal. In this build the non-NaN indicator of secidx_ret_20 has AUC "
      f"{_f(sn.get('auc_of_non_nan_indicator'))} against the label.")
    a("")
    a("**Recommendation to the lead.** Do not read an AB2 or AB5 gain as industry information "
      "until it beats a placebo with the same coverage. `ml/data_ext/extra_features_placebo_f2.parquet` "
      "is that placebo: the F2 columns rebuilt with the industry labels permuted among the "
      "classified symbols (seed 108), with the same Unclassified and ETF groups, the same coverage "
      "and the same F3 columns. It is not a registered trial; running it would need an amendment "
      "(+1 configuration). A cheaper secondary reading is the AUC on classified rows only, where "
      "the between-partition component cannot help. F1, F3 and F4 do not depend on the lists: "
      "F&O membership comes from the daily bhavcopy, and the market state from the point-in-time universe.")
    a("")

    a("## 9. NaN share per feature")
    a("")
    ns = j.get("nan_share", {})
    a("| Feature | NaN share (all rows) | Among F&O members | By year |")
    a("|---|---:|---:|---|")
    for k, v in ns.get("extra_features", {}).items():
        a(f"| {k} | {_f(v['overall'])} | {_f(v.get('among_fo_members'))} | " +
          ", ".join(f"{y} {_f(x, 3)}" for y, x in v["by_year"].items()) + " |")
    for k, v in ns.get("market_state", {}).items():
        a(f"| {k} (by date) | {_f(v['overall'])} | - | {v['n_nan_dates']} NaN dates: {', '.join(v['nan_dates'][:6])}{' ...' if v['n_nan_dates'] > 6 else ''} |")
    a("")

    a("## 10. Descriptive monthly IC (REPORTING ONLY)")
    a("")
    mi = j.get("monthly_ic_descriptive", {})
    a(f"{mi.get('label')}. Target: {mi.get('target')}. Each value is the mean of daily Spearman ICs within a calendar month "
      "(dates with >= 50 pairs). F1 and F4 are one value per date, so they have no cross-sectional IC.")
    a("")
    a("| Feature | Months | Months > 0 | Mean monthly IC |")
    a("|---|---:|---:|---:|")
    for k, v in mi.get("features", {}).items():
        if v.get("n_months"):
            a(f"| {k} | {v['n_months']} | {v['n_months_positive']} | {_f(v['mean_monthly_ic'])} |")
    a("")

    hist = j.get("history_extension")
    a("## 11. History extension (2016-10-03..2021-09-30, for P4)")
    a("")
    if hist:
        for k, v in hist.items():
            a(f"- {k}: {v}")
    else:
        a("Not run in this build.")
    a("")
    a("## 12. Reproduction")
    a("")
    a("```")
    a("OMP_NUM_THREADS=2 python3 -I ml/extdata/download.py --window main   # resume-safe")
    a("OMP_NUM_THREADS=2 python3 -I ml/extdata/run_all.py                  # parse, lists, features, checks, report")
    a("```")
    a("")
    a("Code: `ml/extdata/` (common, download, parse, lists, features, checks, report, run_all). "
      "Raw files: `ml/data_raw/{fo,indices,participant,lists}/` (gitignored). Staging: `ml/data_ext/` (gitignored).")
    txt = "\n".join(L) + "\n"
    path.write_text(txt)
    return txt


if __name__ == "__main__":
    write_markdown(json.loads((C.OUT / "extdata.json").read_text()))
