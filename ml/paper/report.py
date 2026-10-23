"""paper.json (every number of the paper book's status page) and PAPER.md, which only quotes paper.json."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ml.paper.common import read_csv_rows, wjson, wtext
from ml.paper.config import BOOK_ORDER, BOOKS, INCEPTION_SIGNAL_DATE, MODELS_META_DIR, RESULTS_DIR, SPEC_HASH

PAPER_JSON = RESULTS_DIR / "paper.json"
PAPER_MD = RESULTS_DIR / "PAPER.md"

# The stream started on 2026-10-23, so the first three signal dates were scored in one catch-up run.
INCEPTION_NOTE = ("signal dates 2026-10-19, 2026-10-21 and 2026-10-22 were scored on 2026-10-23 (the day this stream "
                  "started) from the store as of 2026-10-22, after the corporate-action repair of that day. Every "
                  "feature looks back only, so a date's frame rows do not depend on later sessions except through a "
                  "corporate action added later, which rescales that ticker's earlier prices (here JSWDULUX, split ex "
                  "2026-10-22): the consistency proof above is exactly that check at 2026-10-16 (a frame built "
                  "through 2026-10-22 against the research frame built through 2026-10-16), and it differs only by "
                  "floating-point rounding in that one ticker. CCAVENUE's consolidation (record date 2026-10-13) was "
                  "announced in the 2026-10-12 bundle, so adjusting it before scoring 2026-10-19 uses no later "
                  "information. From 2026-10-23 on, each session is scored on its own evening.")
SUPERSEDED_DIR = RESULTS_DIR / "superseded_2026-10-23"

def _load(name: str) -> dict:
    p = RESULTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else {}


def marks_summary(marks: pd.DataFrame) -> dict:
    out = {}
    for book in BOOK_ORDER:
        x = marks[marks["book"] == book]
        if x.empty:
            out[book] = {"sessions": 0}
            continue
        e = x["exposure"].to_numpy(float)
        g, n, b, nl = (x[c].to_numpy(float) for c in ("gross_return", "net_return_20bps", "benchmark_return",
                                                      "net_return_name_level"))
        out[book] = {"sessions": int(len(x)), "first_session": x["session"].iloc[0], "last_session": x["session"].iloc[-1],
                     "exposure_last": float(e[-1]),
                     "cum_fixed_capital_gross": float(np.prod(1 + e * g) - 1),
                     "cum_fixed_capital_net_20bps": float(np.prod(1 + e * n) - 1),
                     "cum_fixed_capital_net_name_level": float(np.prod(1 + e * nl) - 1),
                     "cum_fixed_capital_benchmark": float(np.prod(1 + e * b) - 1),
                     "cum_active_net_20bps": float(np.prod(1 + e * n) - np.prod(1 + e * b)),
                     "benchmark": BOOKS[book]["benchmark"]}
    return out


def build(state: dict, marks: pd.DataFrame, inception: dict, latest: dict, dsr: dict, marks_info: dict) -> dict:
    ing = _load("ingest.json")
    cons = _load("consistency.json")
    rep = _load("trainer_reproduction.json")
    idem = _load("idempotency.json")
    lost = _load("lost_state_check.json")
    regen = _load("regeneration.json")
    cal = json.loads((MODELS_META_DIR.parent / "calendar_live.json").read_text()) \
        if (MODELS_META_DIR.parent / "calendar_live.json").exists() else {}
    mon = read_csv_rows(MODELS_META_DIR.parent / "ledger" / "monitors.csv")
    last_s = max((r["session"] for r in mon), default=None)
    models = {}
    for p in sorted(MODELS_META_DIR.glob("*.json")):
        m = json.loads(p.read_text())
        models[m["month"]] = {"role": m["role"], "members": m["members"], "trained_as_of": m["trained_as_of"],
                              "training_window": m["training_window"], "training_frame_sha256": m["training_frame_sha256"],
                              "files_sha256": m["files_sha256"]}
    writes = ing.get("writes", [])
    sessions_ingested = [d for w in writes for d in w.get("accepted", [])]
    sup = _load(SUPERSEDED_DIR.name + "/supersession.json")

    def breaks_of(i: int, w: dict) -> dict | None:
        """Per-name breaks of a write's sessions: its own check, else the first later write that re-checked them."""
        own = (w.get("write") or {}).get("after", {}).get("price_breaks")
        if own is not None:
            return {"by": "this write", **own}
        need = set(w.get("accepted") or [])
        for v in writes[i + 1:]:
            pb = (v.get("write") or {}).get("after", {}).get("price_breaks")
            if pb is not None and need <= set(pb.get("sessions", {})):
                return {"by": f"the later {v.get('kind', 'sessions')} write of {v.get('run_today_ist')}", **pb}
        return None
    out = {
        "spec_hash": SPEC_HASH, "inception_signal_date": INCEPTION_SIGNAL_DATE, "as_of_session": state.get("last_store_session"),
        "state": state,
        "ingest": {"sessions_ingested_by_this_stream": sessions_ingested,
                   "closures_recorded": cal.get("closures", {}),
                   "writes": [{"kind": w.get("kind", "sessions"), "run_today_ist": w.get("run_today_ist"),
                               "reason": w.get("reason"), "checks": w.get("write", {}).get("checks"),
                               "checked_sessions": w.get("write", {}).get("checked_sessions"),
                               "feed_lines_added": w.get("write", {}).get("feed_lines_added"),
                               "price_breaks": breaks_of(i, w),
                               "parser_extension": w.get("corporate_actions", {}).get("parser_extension"),
                               "live_feed": w.get("corporate_actions", {}).get("live_feed"),
                               "sessions": w.get("accepted"), "decisions": [{k: d.get(k) for k in
                                                                            ("date", "weekday", "decision", "date1",
                                                                             "duplicate_day_guard_echo",
                                                                             "byte_identical_to_previous_sec_file",
                                                                             "pr_bundle", "rows_eq_be")}
                                                                           for d in w.get("decisions", [])],
                               "verified": w.get("write", {}).get("verified"),
                               "lock_window_seconds": w.get("write", {}).get("lock", {}).get("window_seconds"),
                               "upsert_rows": w.get("write", {}).get("upsert", {}).get("rows"),
                               "continuity_new_sessions": w.get("write", {}).get("after", {}).get("continuity_new_sessions"),
                               "eq_be_duplicates": w.get("write", {}).get("after", {}).get("eq_be_dup_date_ticker"),
                               "fingerprint_through_research_end": w.get("write", {}).get("after", {}).get(
                                   "fingerprint_through_research_end"),
                               "forward_label_changes_through_research_end": w.get("write", {}).get("after", {}).get(
                                   "forward_label_changes_through_research_end"),
                               "new_corporate_actions": w.get("corporate_actions", {}).get("new_validated_events"),
                               "upcoming_corporate_actions": w.get("corporate_actions", {}).get("upcoming_adjustable_events"),
                               "unvalidated_in_window": w.get("corporate_actions", {}).get(
                                   "unvalidated_adjustable_events_in_window"),
                               "price_breaks_in_window": w.get("corporate_actions", {}).get("price_breaks_in_window"),
                               "rebuilt_ca_feed_vs_10y": w.get("corporate_actions", {}).get(
                                   "rebuilt_vs_10y_through_research_end"),
                               "new_etf_symbols": w.get("etf", {}).get("new_symbols"),
                               "backup_deleted": w.get("write", {}).get("backup", {}).get("deleted_after_verification")}
                              for i, w in enumerate(writes)]},
        "superseded_ledger": sup,
        "consistency_proof": {k: cons.get(k) for k in ("research_end", "rule", "research_end_rows",
                                                      "all_dates_through_research_end",
                                                      "frame_dates_after_research_end",
                                                      "corporate_actions_added_to_ten_year_feed",
                                                      "explained_difference_rule")},
        "inception_point_in_time_note": INCEPTION_NOTE,
        "trainer_reproduction": rep,
        "models": models,
        "inception_baskets": inception,
        "latest_baskets": latest,
        "marks": marks_summary(marks) if len(marks) else {},
        "marks_info": marks_info,
        "monitors_last_session": {"session": last_s, "rows": [r for r in mon if r["session"] == last_s]},
        "dsr_paper": dsr,
        "idempotency": idem,
        "lost_state_check": {k: lost.get(k) for k in ("test", "retrain_equal_to_committed_metadata",
                                                      "regenerated_score_files", "regenerated_scores_file_byte_identical",
                                                      "unchanged", "note_catboost", "live_feed_regeneration")}
        if lost else {},
        "regeneration_from_inception": {k: regen.get(k) for k in ("procedure", "ledger_files", "ledger_identical",
                                                                  "score_files_identical", "committed_ledger_untouched",
                                                                  "regenerated_rows_appended",
                                                                  "regenerated_signal_dates")} if regen else {},
    }
    wjson(PAPER_JSON, out)
    wtext(PAPER_MD, markdown(out))
    return out


def _p(x, d=2):
    return "n/a" if x is None else f"{100 * x:+.{d}f}%"


def markdown(j: dict) -> str:
    st = j["state"]
    L = ["# Paper book: forward record", "",
         f"Source of every number: `ml/results/improve2/paper/paper.json` (spec hash `{j['spec_hash'][:16]}`, as of session "
         f"{j['as_of_session']}). Specification and definitions: `ml/paper/SPEC.md`; daily procedure: `ml/paper/RUNBOOK.md`. "
         "No capital; the paper book is N = 1 and adds no trial.", "",
         "## Status", "",
         f"- Inception signal date {j['inception_signal_date']}; last store session {st.get('last_store_session')}; "
         f"last signal date {st.get('last_signal_date')}; last marked session {st.get('last_mark_session')}.",
         f"- Ledger rows: signals {st.get('ledger_rows', {}).get('signals')}, marks {st.get('ledger_rows', {}).get('marks')}, "
         f"monitors {st.get('ledger_rows', {}).get('monitors')}.",
         f"- Models: " + "; ".join(f"{m} ({v['role']}, {', '.join(v['members'])}, trained as of {v['trained_as_of']} on "
                                  f"{v['training_window']['rows']:,} rows {v['training_window']['first_date']}.."
                                  f"{v['training_window']['last_date']})" for m, v in j["models"].items()), ""]
    ing = j["ingest"]
    L += ["## Sessions ingested after the research data, and store writes", ""]
    for w in ing["writes"]:
        cont = w.get("continuity_new_sessions") or []
        fp = w.get("fingerprint_through_research_end") or {}
        fl = w.get("forward_label_changes_through_research_end") or {}
        pb = w.get("price_breaks") or {}
        brk_txt = ""
        if pb:
            per = pb.get("sessions", {})
            items = "; ".join(f"{b['date']} {b['ticker']} prev_close {b['prev_close']:g} vs stored close "
                              f"{b['stored_previous_close']:g} of {b['stored_previous_date']} (x{b['prev_close_over_stored_close']:.4g}): "
                              f"{b['status'].replace('_', ' ')}" for b in pb.get("breaks", []))
            brk_txt = (f" Per-name prev_close breaks above 22% (checked by {pb.get('by')}): "
                       + ", ".join(f"{d} {v['breaks']} of {v['names_with_prev']}" for d, v in per.items())
                       + (f" ({items})" if items else "") + f"; unexplained {pb.get('n_unexplained')}.")
        common = (f"equity_eod through {j['consistency_proof'].get('research_end')}: identical "
                  f"{(fp.get('equity_eod_through_boundary') or {}).get('identical')}; equity_features non-label columns of "
                  f"{fp.get('tickers_compared')} tickers unchanged except the tickers whose feed lines changed "
                  f"{fp.get('non_forward_unchanged_except_new_ca_tickers')} (changed: "
                  f"{fp.get('tickers_with_changed_non_forward_rows')}); forward label columns (fwd_ret_2d..5d, "
                  f"label_up_2d..5d) changed on {fl.get('rows_changed')} rows dated {fl.get('first_date')}.."
                  f"{fl.get('last_date')}: {fl.get('rows_last5_of_ticker_previously_nan')} were each ticker's last 5 rows "
                  f"(NaN before; build_features shifts by rows, so they now reach the new sessions), "
                  f"{fl.get('rows_of_new_corporate_action_tickers')} belong to the tickers whose feed lines changed, "
                  f"{fl.get('rows_unexplained')} unexplained.")
        if w.get("kind") == "features_rebuild":
            lf = w.get("live_feed") or {}
            px = w.get("parser_extension") or {}
            L += [f"**Repair write ({w.get('run_today_ist')}, no new session): `ml/paper/ingest.py --rebuild-features`.** "
                  f"Reason: {w.get('reason')}. Live feed lines added: {w.get('feed_lines_added')}; the live feed is the "
                  f"ten-year feed's bytes plus {lf.get('lines_appended')} lines ({lf.get('rows')} rows, starts with the "
                  f"ten-year bytes {lf.get('starts_with_ten_year_feed_bytes')}). Parser extension: purposes read "
                  f"{px.get('purposes_read_by_extension')}, ex-dates taken from the record date "
                  f"{[(e['ticker'], e['ex_date']) for e in px.get('ex_date_from_record_date') or []]}. "
                  f"Lock held {w.get('lock_window_seconds')} s, verified {w.get('verified')} ({w.get('checks')}), backup "
                  f"deleted after verification {w.get('backup_deleted')}. Sessions re-checked: {w.get('checked_sessions')}."
                  + brk_txt + " " + common,
                  f"Research-period events the parser extension finds and the ten-year feed lacks (reported, not applied): "
                  f"{[e for e in (w.get('rebuilt_ca_feed_vs_10y') or {}).get('only_in_rebuilt_from_parser_extension', []) if (e[0], e[1]) not in {(x['ticker'], x['ex_date']) for x in (w.get('new_corporate_actions') or [])}]}; "
                  f"rebuilt feed equals the ten-year feed apart from the extension: "
                  f"{(w.get('rebuilt_ca_feed_vs_10y') or {}).get('identical_apart_from_parser_extension')}.", ""]
            continue
        L.append("| Date | Weekday | Decision | DATE1 | Echo of previous | PR bundle | EQ/BE rows |")
        L.append("|---|---|---|---|---|---|---:|")
        for d in w["decisions"]:
            echo = ("" if d.get("duplicate_day_guard_echo") is None else
                    f"{d.get('duplicate_day_guard_echo')} (file bytes identical: {d.get('byte_identical_to_previous_sec_file')})")
            L.append(f"| {d['date']} | {d['weekday']} | {d['decision']} | {', '.join(d.get('date1') or [])} | "
                     f"{echo} | {d.get('pr_bundle') or ''} | {d.get('rows_eq_be') if d.get('rows_eq_be') is not None else ''} |")
        rb = w.get("rebuilt_ca_feed_vs_10y") or {}
        L += ["", f"Write ({w.get('run_today_ist')}): {w.get('upsert_rows')} rows upserted, lock held "
                  f"{w.get('lock_window_seconds')} s, verified {w.get('verified')}, backup deleted after verification "
                  f"{w.get('backup_deleted')}. Continuity scan on the new sessions (share of names whose prev_close differs "
                  "from the stored previous close): " + ", ".join(f"{c['date']} {c['n_mismatch']} of {c['n_with_prev']} "
                                                                 f"({100 * c['share']:.2f}%)" for c in cont)
                  + f"; duplicate EQ/BE pairs {w.get('eq_be_duplicates')}." + brk_txt + " " + common,
              f"New validated corporate actions (cumulative since the research end, as of this write): "
              f"{[(e['ticker'], e['ex_date'], e['ratio']) for e in (w.get('new_corporate_actions') or [])]}. "
              f"Unvalidated split/bonus in the window: {w.get('unvalidated_in_window')}. Price breaks (unadjustable "
              f"actions): {len(w.get('price_breaks_in_window') or [])}. Upcoming split/bonus ex-dates: "
              f"{[(e['ticker'], e['ex_date']) for e in (w.get('upcoming_corporate_actions') or [])]}. Rebuilt feed equals "
              f"the ten-year feed through the research end: {rb.get('identical')}"
              + (f" (apart from the parser extension: {rb.get('identical_apart_from_parser_extension')})"
                 if rb.get("identical_apart_from_parser_extension") is not None else "")
              + f". New ETF symbols: {w.get('new_etf_symbols')}.", ""]
    sp = j.get("superseded_ledger") or {}
    if sp:
        L += ["## Superseded first ledger (regenerated from inception on 2026-10-23)", "",
              f"{sp.get('reason')}", "",
              f"Superseded files: `{sp.get('folder')}` ({sp.get('rows')}). The regenerated ledger uses the same frozen "
              f"construction, the same October models (content hashes {sp.get('models_unchanged')}) and the repaired "
              f"store. CCAVENUE's neutral LightGBM score: "
              + ", ".join(f"{d} {v['old']:.3f} -> {v['new']:.3f}" for d, v in (sp.get("ccavenue_neutral_lgbm") or {}).items())
              + ".", "",
              "| Signal date | Book | Names before | Names after | Left the book | Entered the book |",
              "|---|---|---:|---:|---|---|"]
        for r in sp.get("basket_changes", []):
            L.append(f"| {r['signal_date']} | {r['book']} | {r['n_old']} | {r['n_new']} | {', '.join(r['out']) or '-'} | "
                     f"{', '.join(r['in']) or '-'} |")
        L.append("")
    c = j["consistency_proof"]
    r0, ra = c.get("research_end_rows") or {}, c.get("all_dates_through_research_end") or {}
    L += ["## Consistency proof (scoring frame vs `ml/data_10y`)", "",
          f"Rule: {c.get('rule')}.", "",
          "| Rows compared | Common rows | Only frame | Only 10y | Max abs diff (52 features) | Cells differing | "
          "Unexplained cells | Bit-identical | Equal except the new corporate action's rounding |",
          "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for lab, r in ((c.get("research_end"), r0), (f"every date through {c.get('research_end')}", ra)):
        L.append(f"| {lab} | {r.get('rows_common')} | {r.get('rows_only_frame')} | {r.get('rows_only_10y')} | "
                 f"{r.get('max_abs_diff_all_features', 0):.2g} | {r.get('cells_differing')} | "
                 f"{r.get('cells_differing_unexplained')} | {r.get('identical')} | "
                 f"{r.get('equal_except_new_corporate_action_rounding')} |")
    L.append("")
    ev = c.get("corporate_actions_added_to_ten_year_feed") or []
    if r0.get("cells_differing"):
        evs = ", ".join("{} (price ratio {:g}, ex {})".format(e["ticker"], e["ratio"], e["ex_date"]) for e in ev) \
            or "a corporate action"
        L += [f"Why not bit-identical: the live corporate-action feed adds {evs} to the ten-year feed, "
              f"so build_features rescales those tickers' earlier prices by the ratio; every price ratio is unchanged up to "
              f"floating-point rounding. On {c.get('research_end')} the {r0.get('cells_differing')} differing cells are all "
              f"in {', '.join(r0.get('tickers_with_differences') or [])} ({len(r0.get('per_feature_differing') or {})} "
              f"features, at most {r0.get('max_abs_diff_all_features', 0):.2g}); the other "
              f"{(r0.get('rows_common') or 0) - len(r0.get('tickers_with_differences') or [])} rows of that date are "
              f"bit-identical. Over every date, {ra.get('cells_differing')} cells differ (at most "
              f"{ra.get('max_abs_diff_all_features', 0):.2g}) on {ra.get('n_dates_with_differences')} dates in "
              f"{ra.get('n_tickers_with_differences')} tickers (cells by feature: "
              + ", ".join(f"{k} {v['rows_differing']}" for k, v in (ra.get('per_feature_differing') or {}).items())
              + f"), every one of them a rescaled ticker's own row or a cross-sectional feature (`amihud_20` z-score, "
              f"ranks) on a date where a rescaled ticker is in the universe, which is why so many tickers carry a "
              f"rounding-level `amihud_20` difference; {ra.get('cells_differing_unexplained')} are unexplained. Rule of "
              f"explanation: {c.get('explained_difference_rule')}.", ""]
    if j.get("inception_point_in_time_note"):
        L += [f"Point in time: {j['inception_point_in_time_note']}", ""]
    rp = j["trainer_reproduction"]
    if rp:
        L += [f"Trainer reproduction: the paper trainer on the research holdout fold (train end {rp['fold']['train_end']}, "
              f"{rp['train_rows']:,} training rows) scores {rp['rows_matched']:,} holdout rows; max |score − ten-year control "
              f"score| = {rp['max_abs_score_diff']}; identical {rp['identical']} ({rp.get('identical_rule', 'every row')})."
              + (f" Not compared: {len(rp['test_rows_label_exit_after_research_end'])} test rows whose label exits after "
                 f"the research end, so the research data could not label them ("
                 + ", ".join(f"{x['ticker']} {x['date']} exit {x['exit_date']}"
                             for x in rp["test_rows_label_exit_after_research_end"])
                 + "; a 20-row label window that crosses a trading suspension into the sessions after the research end)."
                 if rp.get("test_rows_label_exit_after_research_end") else ""), ""]
    inc = j["inception_baskets"]
    if inc:
        L += [f"## Inception baskets (signal date {inc['signal_date']}, entry at the next session's open)", "",
              f"Model {inc.get('model_month')}; universe {inc.get('universe')} names, liquid tercile "
              f"{inc.get('liquid_tercile')}. Scores: neutralised percentile for the neutral books, LightGBM probability "
              "for the plain reference.", "",
              "| Book | Names | Top 10 (rank: ticker) |", "|---|---:|---|"]
        for b in BOOK_ORDER:
            x = inc.get(b, {})
            L.append(f"| {b} | {x.get('size')} | " + ", ".join(f"{t['rank']}: {t['ticker']}" for t in x.get("top", [])) + " |")
        L.append("")
    lt = j["latest_baskets"]
    if lt:
        L += [f"Latest signal date {lt.get('signal_date')}: " + ", ".join(f"{b} {lt[b]['size']} names" for b in BOOK_ORDER
                                                                          if b in lt) + ".", ""]
    mk = j["marks"]
    if mk:
        L += ["## Marks (fixed capital: 1/20 per tranche, idle capital at zero)", "",
              "| Book | Sessions | Exposure (last) | Gross | Net 20 bps | Net name-level | Benchmark | Active net 20 bps |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for b in BOOK_ORDER:
            x = mk.get(b, {})
            if not x.get("sessions"):
                continue
            L.append(f"| {b} | {x['sessions']} ({x['first_session']}..{x['last_session']}) | {x['exposure_last']:.2f} | "
                     f"{_p(x['cum_fixed_capital_gross'])} | {_p(x['cum_fixed_capital_net_20bps'])} | "
                     f"{_p(x['cum_fixed_capital_net_name_level'])} | {_p(x['cum_fixed_capital_benchmark'])} "
                     f"({x['benchmark']}) | {_p(x['cum_active_net_20bps'])} |")
        L += ["", "A few sessions of a ramping book say nothing about the strategy; these lines exist so that the record "
                  "starts on the day it should.", ""]
    mo = j["monitors_last_session"]
    if mo.get("rows"):
        L += [f"## Monitors as of {mo['session']}", "", "| Monitor | Scope | Value | Threshold | Status | Detail |",
              "|---|---|---:|---:|---|---|"]
        for r in mo["rows"]:
            L.append(f"| {r['monitor']} | {r['scope']} | {r['value']} | {r['threshold']} | {r['status']} | {r['detail']} |")
        L.append("")
    ds = j["dsr_paper"]
    if ds:
        L += ["Deflated Sharpe of the daily active net-20 bps series (N = 261, V[SR] = 0.00387): "
              + "; ".join(f"{b} {v.get('dsr', float('nan')):.3f} ({v.get('status')})" if "dsr" in v else f"{b} {v.get('status')}"
                          for b, v in ds.items()) + ".", ""]
    idem = j["idempotency"]
    if idem:
        L += ["## Idempotency proof", "",
              f"A second run on the same data ({idem.get('note')}; scoring frame rebuilt from the store in this run: "
              f"{idem.get('frame_rebuilt_in_this_run')}; ingest decisions {idem.get('ingest_decisions_in_this_run')}): "
              f"ledger SHA-256 before and after identical "
              f"{idem.get('identical')}; rows appended {idem.get('rows_appended')}; recomputed signals of "
              f"{idem.get('recomputed_signal_date')} equal the ledger {idem.get('recomputed_signals_equal_ledger')}; "
              f"recomputed marks equal the ledger {idem.get('recomputed_marks_equal_ledger')}.", "",
              "| File | SHA-256 before | SHA-256 after |", "|---|---|---|"]
        for k in idem.get("before", {}):
            L.append(f"| {k} | `{(idem['before'][k] or '')[:16]}` | `{(idem['after'].get(k) or '')[:16]}` |")
        L.append("")
    ls = j.get("lost_state_check") or {}
    if ls:
        L += ["## Lost-state check", "",
              f"{ls.get('test')}: the October models were retrained and equal the committed metadata "
              f"({ls.get('retrain_equal_to_committed_metadata')}); regenerated score files {ls.get('regenerated_score_files')} "
              f"byte-identical {ls.get('regenerated_scores_file_byte_identical')}; ledger and model metadata unchanged "
              f"{ls.get('unchanged')}. {ls.get('note_catboost')}.", ""]
        lf = ls.get("live_feed_regeneration") or {}
        if lf:
            L += [f"Live corporate-action feed: {lf.get('test')}; byte-identical to the original {lf.get('byte_identical')}, "
                  f"equal to the hash in state.json {lf.get('equals_state_json')} ({lf.get('rows')} rows).", ""]
    rg = j.get("regeneration_from_inception") or {}
    if rg:
        L += ["## Determinism proof (ledger regenerated from inception)", "",
              f"{rg.get('procedure')}. Rows regenerated: {rg.get('regenerated_rows_appended')} for signal dates "
              f"{rg.get('regenerated_signal_dates')}; ledger byte-identical to the committed files "
              f"{rg.get('ledger_identical')}; per-date score files identical {rg.get('score_files_identical')}; committed "
              f"ledger untouched {rg.get('committed_ledger_untouched')}.", "",
              "| File | Committed SHA-256 | Regenerated SHA-256 |", "|---|---|---|"]
        for k, v in (rg.get("ledger_files") or {}).items():
            L.append(f"| {k} | `{(v.get('committed') or '')[:16]}` | `{(v.get('regenerated') or '')[:16]}` |")
        L.append("")
    return "\n".join(L) + "\n"
