#!/usr/bin/env python3
"""Merge the stream's JSON parts into ml/results/improve2/events/events.json and regenerate EVENTS.md section 7.

Sections 1-6 of EVENTS.md (written before any result) are kept verbatim up to the marker line; everything below the
marker is generated here from events.json, so every number in section 7 is quoted from it.

Usage: python3 -m ml.events.report
"""
from __future__ import annotations

import json
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
DIR = ML / "results" / "improve2" / "events"
MD = DIR / "EVENTS.md"
MARK = "<!-- generated below from events.json by ml/events/report.py; do not edit by hand -->"
FEATURES = ["sess_since_results", "results_last_5", "results_last_20", "ear_3d", "ear_vol_z", "ann_count_20",
            "rating_20", "mgmt_change_60", "orders_20", "insolvency_60"]


def _load(name: str):
    p = DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def merge() -> dict:
    ev = {"stream": "Q6 company events (ml/IMPROVEMENT_PLAN_2.md)", "seed": 108,
          "parse": _load("parse.json"), "classify": _load("classify.json"),
          "features_manifest": json.loads((ML / "data_ext" / "event_features_manifest.json").read_text()),
          "checks": _load("checks.json"), "ic": _load("ic.json")}
    (DIR / "events.json").write_text(json.dumps(ev, indent=1))
    return ev


def f(x, fmt=".3f", none="n/a"):
    if x is None:
        return none
    return format(x, fmt)


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def render(ev: dict) -> str:
    L: list[str] = []
    pj, cj, man, ck, ic = ev["parse"], ev["classify"], ev["features_manifest"], ev["checks"] or {}, ev["ic"]
    # 7.1 parse
    L += ["### 7.1 Parse (`events.json` → `parse`)", "",
          f"{pj['bundles_found']} bundles found, {pj['bundles_with_member']} with an announcement member, "
          f"{pj['dates_selected']} dates selected; {pj['records']:,} announcement records and "
          f"{pj['board_meeting_list_rows']:,} board-meeting list rows. Selection decisions:", ""]
    for d in pj["selection_decisions"]:
        L.append(f"- {d['member_date']}: `{d['bundle']}` {d['action']} ({d['reason']}; identical bytes: {d.get('identical_bytes')})")
    L += ["", f"Encodings: " + ", ".join(f"{k} {v}" for k, v in pj["encodings"].items())
          + f". Vocabulary: {pj['dictionary_categories']} categories, {pj['known_symbols']:,} known symbols (`{pj.get('vocabulary')}`).", "",
          "| Year | Bundles | Records | Wide / narrow layout | Category from separator / dictionary / spliced / derived / none | Symbols | In bhavcopy | Board-meeting rows |",
          "|---|---:|---:|---|---|---:|---:|---:|"]
    for y, r in sorted(pj["by_year"].items()):
        cm = r["cat_method"]
        sep = cm.get("cat_sym", 0) + cm.get("xbrl", 0)
        spl = cm.get("dict_spliced", 0) + cm.get("dict_spliced_loose", 0)
        L.append(f"| {y} | {r['bundles_parsed']} | {r['records']:,} | {r['layout_wide']:,} / {r['layout_narrow']:,} | "
                 f"{sep:,} / {cm.get('dict_prefix', 0):,} / {spl:,} / {cm.get('derived', 0):,} / {cm.get('none', 0):,} | "
                 f"{r['symbols']:,} | {r['symbols_in_bhavcopy']:,} | {r['board_meeting_list_rows']:,} |")
    # 7.2 categories
    cf = cj["category_frequency_by_year_bhavcopy_symbols"]
    yrs = cf["years"]
    L += ["", "### 7.2 Category frequency by year and mapping (`classify.category_frequency_by_year_bhavcopy_symbols`, `classify.category_to_class_share_top`)", "",
          f"Records for bhavcopy symbols, {cf['n_categories']} distinct categories; the 60 most frequent are shown "
          "(the JSON holds 120). Mapping = share of the category's records carrying each class.", "",
          "| Category | Total | " + " | ".join(str(y) for y in yrs) + " | Mapping |", "|---|---:|" + "---:|" * len(yrs) + "---|"]
    mp = cj["category_to_class_share_top"]
    for r in cf["top"][:60]:
        c = r["category"] or "(none)"
        m = mp.get(r["category"], {})
        ms = ", ".join(f"{k} {v:.2f}" for k, v in m.items() if k != "non_routine" and v >= 0.01) or ("non-routine" if m.get("non_routine") else "")
        if m.get("non_routine", 0) >= 0.99 and not any(k for k in m if k not in ("non_routine",)):
            ms = "non-routine"
        L.append(f"| {c[:80]} | {r['total']:,} | " + " | ".join(f"{r['by_year'].get(str(y), 0):,}" for y in yrs) + f" | {ms} |")
    L += ["", "| Class (bhavcopy symbols) | " + " | ".join(str(y) for y in yrs) + " |", "|---|" + "---:|" * len(yrs)]
    for c, v in cj["class_counts_by_year_bhavcopy_symbols"].items():
        L.append(f"| {c} | " + " | ".join(f"{v.get(str(y), 0):,}" for y in yrs) + " |")
    L += ["", "| Results rule (all symbols) | " + " | ".join(str(y) for y in yrs) + " |", "|---|" + "---:|" * len(yrs)]
    for c, v in cj["results_rule_counts_by_year"].items():
        L.append(f"| {c} | " + " | ".join(f"{v.get(str(y), 0):,}" for y in yrs) + " |")
    # 7.3 coverage
    cov = ck.get("coverage")
    L += ["", "### 7.3 Coverage (`checks.coverage`, `features_manifest.coverage`)", ""]
    g = man["coverage"]
    L += ["Coverage gaps (D1): " + "; ".join(f"{x['from']} to {x['to']} ({x['sessions']} sessions)" for x in g["gaps"])
          + ". Isolated uncovered sessions treated as days without announcements: " + ", ".join(g["isolated_uncovered_sessions_treated_as_empty"]) + "."]
    if cov:
        fl = cov["files"]
        L += ["", f"Covered sessions {fl['covered_sessions']:,}, uncovered {fl['uncovered_sessions']} (of which in full runs of >= 3: "
              f"{fl['gap_sessions_full_runs']}); the smallest covered file has {fl['min_company_records_covered']} company records, "
              f"the largest uncovered file {fl['max_company_records_uncovered_with_file']}; sessions without records: "
              + ", ".join(fl["sessions_without_records"]) + ".",
              f"Universe rule recomputed on the price export vs the dataset's rows (D6): " + ", ".join(f"{k} {v:,}" for k, v in cov["universe_rule_vs_dataset_rows"].items()) + ".",
              f"Release sessions: {cov['release_sessions_total']:,}; results observations by rule: "
              + ", ".join(f"{k} {v:,}" for k, v in cov["results_observations_by_rule"].items()) + "; release sessions by the rules observed on them: "
              + ", ".join(f"{k} {v:,}" for k, v in list(cov["release_sessions_by_rules_observed"].items())[:8]) + ".",
              f"Spacing between consecutive releases of a symbol (sessions): median {cov['release_spacing_sessions_histogram']['median']:.0f}; histogram edges "
              f"{cov['release_spacing_sessions_histogram']['edges']} counts {cov['release_spacing_sessions_histogram']['counts']}.", "",
              "| Year | Bundles | Records (all) | Non-NAV | Non-routine | Symbols (non-NAV) | Matched to dataset tickers | Dataset rows | Rows with a release in the past 126 sessions | Of rows with a known value | sess_since_results NaN |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for y, r in sorted(cov["by_year"].items()):
            L.append(f"| {y} | {r['bundles_parsed']} | {r['records_all']:,} | {r['records_non_nav']:,} | {r['records_non_routine']:,} | "
                     f"{r['symbols_non_nav']:,} | {r['symbols_matched_to_dataset_tickers']:,} | {r['dataset_rows']:,} | "
                     f"{pct(r['share_rows_release_in_past_126'])} | {pct(r['share_rows_release_in_past_126_of_known'])} | {pct(r['share_rows_sess_since_results_nan'])} |")
        L += ["", "Quarterly results coverage (D2): share of names with at least one release session in the calendar quarter; "
              "liquid = `cs_rank_turnover` >= 0.67 on some row of the quarter.", "",
              "| Quarter | Liquid names | With a release | From announcement records alone (R1-R3) | All dataset names | With a release | R1-R3 alone |",
              "|---|---:|---:|---:|---:|---:|---:|"]
        allq = cov["results_quarterly_all_dataset_names"]
        for q, r in cov["results_quarterly_liquid"].items():
            a = allq.get(q, {})
            L.append(f"| {q} | {r['names']} | {pct(r['share_with_release'])} | {pct(r['share_with_announcement_record_R1_R3'])} | "
                     f"{a.get('names', '')} | {pct(a.get('share_with_release'))} | {pct(a.get('share_with_announcement_record_R1_R3'))} |")
    # 7.4 features
    L += ["", "### 7.4 The parquet (`features_manifest`)", "",
          f"`ml/data_ext/event_features_10y.parquet`: {man['rows']:,} rows, key {man['key']}, columns {man['columns']}; "
          f"row set: {man['row_set']}; sha256 `{man['sha256'][:16]}...`; {man['release_sessions']:,} release sessions.", "",
          "| Column | NaN share |", "|---|---:|"]
    for c in FEATURES:
        L.append(f"| `{c}` | {pct(man['nan_share'][c])} |")
    # 7.5 checks
    L += ["", "### 7.5 Point-in-time checks (`checks`)", ""]
    if cov:
        rb = cov["rebuild_equals_parquet"]
        L.append(f"- **Rebuild:** a second full build equals the parquet ({rb['rows_compared']:,} rows; unchanged: {rb['unchanged']}).")
    rp = ck.get("reparse")
    if rp:
        L.append(f"- **Re-parse from the raw zips:** {rp['files_reparsed']} files, {rp['records_reparsed']:,} records re-parsed vs "
                 f"{rp['records_stored']:,} stored; files with a digest mismatch: {len(rp['files_with_digest_mismatch'])}; equal: {rp['equal']}.")
    pc = ck.get("pit_cells")
    if pc:
        L.append(f"- **100 random cells recomputed from files dated <= t:** {pc['cells_all_equal']}/{pc['n_cells']} cells equal on all ten columns "
                 f"(mismatches by column: " + ", ".join(f"{k} {v}" for k, v in pc["mismatches_by_column"].items()) + "; non-NaN cells by column: "
                 + ", ".join(f"{k} {v}" for k, v in pc["non_nan_cells_by_column"].items()) + "). " + pc["method"] + ".")
    dfu = ck.get("delete_future")
    if dfu:
        L.append(f"- **Delete-the-future ({dfu['month']}):** files after the month-end and prices after it removed ({dfu['files_kept']} files and "
                 f"{dfu['price_sessions_kept']} price sessions kept); {dfu['rows_compared']:,} rows <= month-end compared, of which {dfu['month_rows']:,} in the month; "
                 f"cells differing: " + ", ".join(f"{k} {v}" for k, v in dfu["cells_differing_by_column"].items()) + f"; unchanged: {dfu['unchanged']}.")
    sh = ck.get("shift")
    if sh:
        L.append(f"- **Shift test (T0 = {sh['T0']}):** build on the {sh['files_up_to_T0']} bundles up to T0, then with every later bundle appended; "
                 f"{sh['rows_compared']:,} rows <= T0 compared; cells differing: " + ", ".join(f"{k} {v}" for k, v in sh["cells_differing_by_column"].items())
                 + f"; unchanged: {sh['unchanged']}.")
    aj = ck.get("ab_join")
    if aj:
        L.append(f"- **A/B join:** {aj['path']}; {aj['rows']:,} rows, all ten columns present: {aj['all_ten_present']}; non-NaN share: "
                 + ", ".join(f"{k} {v:.3f}" for k, v in aj["coverage"].items()) + ".")
    # 7.6 IC
    L += ["", "### 7.6 Descriptive rank IC (last step; `ic`)", ""]
    if ic:
        L += [f"**{ic['label']}.** Target {ic['target']}; {ic['rows']}; per date with >= {ic['min_names_per_date']} names; Newey-West lag {ic['nw_lag']}.", ""]
        e = ic["ear_3d_recent_release"]
        L += [f"`ear_3d` among {e['subset']}: mean rank IC {f(e['mean'], '+.4f')}, NW t {f(e['nw_t'], '.2f')}, {e['dates']} dates, "
              f"{pct(e['share_positive'], 0)} of dates positive.", "",
              "| Year | Mean IC | NW t | Dates | Share positive |", "|---|---:|---:|---:|---:|"]
        for y, r in e["by_year"].items():
            L.append(f"| {y} | {f(r['mean'], '+.4f')} | {f(r['nw_t'], '.2f')} | {r['dates']} | {pct(r['share_positive'], 0)} |")
        years = sorted({y for c in ic["columns_all_rows"].values() for y in c["by_year"]})
        L += ["", "Every family-E column over all rows with a value:", "",
              "| Column | Mean IC | NW t | Dates | " + " | ".join(years) + " |", "|---|---:|---:|---:|" + "---:|" * len(years)]
        for c, r in ic["columns_all_rows"].items():
            L.append(f"| `{c}` | {f(r['mean'], '+.4f')} | {f(r['nw_t'], '.2f')} | {r['dates']} | "
                     + " | ".join(f(r["by_year"].get(y, {}).get("mean"), "+.3f", "") for y in years) + " |")
    else:
        L.append("Pending: `python3 -m ml.events.ic` runs last.")
    # 7.7 rules appendix
    L += ["", "### 7.7 Rule patterns as fixed (`classify.rules`)", "",
          "| Class | Rule | Where | Patterns (case-insensitive regular expressions) |", "|---|---|---|---|"]
    for r in cj["rules"]:
        pats = "; ".join(f"`{p}`" for p in r["patterns"]).replace("|", "\\|")
        L.append(f"| {r['class']} | {r['id']} | {r['where'].replace('|', '/')} | {pats} |")
    L.append("")
    return "\n".join(L)


def run() -> None:
    ev = merge()
    md = MD.read_text()
    head = md.split(MARK)[0]
    MD.write_text(head + MARK + "\n\n" + render(ev))
    print("[events.report] events.json and EVENTS.md written", flush=True)


if __name__ == "__main__":
    run()
