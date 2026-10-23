"""paper.json (every number of the paper book's status page) and PAPER.md, which only quotes paper.json."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ml.paper.common import read_csv_rows, wjson, wtext
from ml.paper.config import (ALL_BOOKS, BOOK_ORDER, EXT_BACKFILL_THROUGH, EXT_BOOK_ORDER, EXT_COUNTERPART, EXT_NAME,
                             EXT_N_TRIALS_DSR, EXT_REGISTERED_UTC, INCEPTION_SIGNAL_DATE, MODELS_META_DIR,
                             N_TRIALS_DSR, RESULTS_DIR, SPEC_EXT_HASH, SPEC_HASH)

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

# Extension 1 (ml/paper/SPEC.md amendment 10)
EXT_MOTIVATION = ("Plan 2 amendment A1 (Q9): the control with an expanding training window passed the primary AUC mark "
                  "(delta CV-mean AUC +0.0079, 95% CI [+0.0047, +0.0113], ml/results/improve2/expanding/EXPANDING.md); "
                  "the plan says a pass is evidence for a forward test, not a promotion, and until this amendment no "
                  "forward book ran it. The hypothesis was formed after the CPCV reading was seen, so this record, not "
                  "the backtest, is the test.")
EXT_DEFINITION = ("challenger_expanding is the primary book in every respect (LightGBM champion configuration, the 52 "
                  "features, per-date vol+size neutralisation on the full universe, full-universe top decile, 20 "
                  "overlapping tranches, entry at the next open, 20-session hold, 20 bps and name-level costs, "
                  "equal-weight universe benchmark) except the monthly model's training window: every labelled clean row "
                  "whose label exit date is before the model date, from the first dataset row (2017-10-03), with no "
                  "504-session cap (ml/improve/ab.py q9_expanding). capacity_expanding is its liquid-tercile version, "
                  "as the capacity book is to the primary (benchmark: the equal-weight liquid tercile).")
EXT_BACKFILL_NOTE = ("The two books were added on 2026-10-23 and backfilled from inception (signal dates 2026-10-19, "
                     "2026-10-21 and 2026-10-22) with the 2026-10 expanding-window model, trained as of 2026-10-01 on the "
                     "data available then: rows dated up to 2026-08-31 (train_end, 22 sessions before the model date) "
                     "whose label exit date is before 2026-10-01 (exit-date purge), exactly as the frozen October model "
                     "was trained but with the expanding window. This is legitimate: the three signal dates are after the "
                     "research data (which end 2026-10-16), the model uses no data dated after its model date, and every "
                     "choice in the books' definition was fixed by amendment A1 before Q9 produced any result (SPEC.md section 6, "
                     "erratum). The frozen books' first "
                     "three signal dates were themselves scored in one catch-up run on 2026-10-23; the extension's were "
                     "scored the same day, after the frozen books' first two marked sessions (2026-10-21, 2026-10-22) "
                     "were in the ledger. No parameter of the extension depends on those marks.")

def _load(name: str) -> dict:
    p = RESULTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else {}


def marks_summary(marks: pd.DataFrame) -> dict:
    out = {}
    for book in BOOK_ORDER + [b for b in EXT_BOOK_ORDER if (marks["book"] == b).any()]:
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
                     "benchmark": ALL_BOOKS[book]["benchmark"]}
    return out


def build(state: dict, marks: pd.DataFrame, inception: dict, latest: dict, dsr: dict, marks_info: dict,
          ext: dict | None = None) -> dict:
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
                                                                  "regenerated_signal_dates",
                                                                  "score_files_identical_expanding",
                                                                  "frozen_only")} if regen else {},
    }
    if ext is not None:
        xm = {}
        for p in sorted((MODELS_META_DIR / EXT_NAME).glob("*.json")):
            m = json.loads(p.read_text())
            xm[m["month"]] = {"role": m["role"], "members": m["members"], "trained_as_of": m["trained_as_of"],
                              "spec": m["spec"], "training_window": m["training_window"],
                              "training_frame_sha256": m["training_frame_sha256"], "files_sha256": m["files_sha256"],
                              "fit_seconds": m["fit_seconds"], "metadata": f"ml/paper/models/{EXT_NAME}/{p.name}"}
        out["extension"] = {"name": EXT_NAME, "spec_hash": SPEC_EXT_HASH, "extends_spec_hash": SPEC_HASH,
                            "registered_utc": EXT_REGISTERED_UTC, "amendment": "ml/paper/SPEC.md section 5 (amendment 10)",
                            "books": EXT_BOOK_ORDER, "counterpart": EXT_COUNTERPART,
                            "backfill_through": EXT_BACKFILL_THROUGH, "motivation": EXT_MOTIVATION,
                            "definition": EXT_DEFINITION, "backfill_note": EXT_BACKFILL_NOTE, "models": xm,
                            "trainer_reproduction": _load("trainer_reproduction_expanding.json"),
                            "backfill_proof": _load("extension_backfill.json"),
                            "lost_state_check": _load("lost_state_check_expanding.json"),
                            "inception_baskets": ext.get("inception"), "basket_overlap": ext.get("overlap"),
                            "score_agreement": ext.get("score_agreement"), "dsr_paper": ext.get("dsr"),
                            "dsr_n_trials": EXT_N_TRIALS_DSR}
    wjson(PAPER_JSON, out)
    wtext(PAPER_MD, markdown(out))
    return out


def _p(x, d=2):
    return "n/a" if x is None else f"{100 * x:+.{d}f}%"


def markdown(j: dict) -> str:
    st = j["state"]
    L = ["# Paper book: forward record", "",
         f"Source of every number: `ml/results/improve2/paper/paper.json` (spec hash `{j['spec_hash'][:16]}`"
         + (f"; extension 1 spec hash `{j['extension']['spec_hash'][:16]}`" if j.get("extension") else "")
         + f", as of session "
         f"{j['as_of_session']}). Specification and definitions: `ml/paper/SPEC.md`; daily procedure: `ml/paper/RUNBOOK.md`. "
         "No capital; the paper book is N = 1 and adds no trial.", "",
         "## Status", "",
         f"- Inception signal date {j['inception_signal_date']}; last store session {st.get('last_store_session')}; "
         f"last signal date {st.get('last_signal_date')}; last marked session {st.get('last_mark_session')}.",
         f"- Ledger rows: signals {st.get('ledger_rows', {}).get('signals')}, marks {st.get('ledger_rows', {}).get('marks')}, "
         f"monitors {st.get('ledger_rows', {}).get('monitors')}"
         + (" (the four frozen books); extension 1: signals {signals}, marks {marks}, monitors {monitors}".format(
             **st["extension"]["ledger_rows"]) if st.get("extension") else "") + ".",
         f"- Models: " + "; ".join(f"{m} ({v['role']}, {', '.join(v['members'])}, trained as of {v['trained_as_of']} on "
                                  f"{v['training_window']['rows']:,} rows {v['training_window']['first_date']}.."
                                  f"{v['training_window']['last_date']})" for m, v in j["models"].items())]
    xj = j.get("extension") or {}
    if xj:
        L += [f"- Extension 1 (SPEC.md amendment 10, registered {xj['registered_utc']}, spec hash "
              f"`{xj['spec_hash'][:16]}`; the frozen books' spec hash `{xj['extends_spec_hash'][:16]}` is unchanged): books "
              + ", ".join(xj["books"]) + "; expanding-window models: "
              + "; ".join(f"{m} ({', '.join(v['members'])}, trained as of {v['trained_as_of']} on "
                          f"{v['training_window']['rows']:,} rows {v['training_window']['first_date']}.."
                          f"{v['training_window']['last_date']})" for m, v in xj["models"].items()) + "."]
    L.append("")
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
        xi = (xj.get("inception_baskets") or {}) if xj else {}
        for b in (EXT_BOOK_ORDER if xi else []):
            x = xi.get(b, {})
            L.append(f"| {b} (model {xi.get('model_month_expanding')} expanding) | {x.get('size')} | "
                     + ", ".join(f"{t['rank']}: {t['ticker']}" for t in x.get("top", [])) + " |")
        L.append("")
    lt = j["latest_baskets"]
    if lt:
        L += [f"Latest signal date {lt.get('signal_date')}: " + ", ".join(f"{b} {lt[b]['size']} names"
                                                                          for b in BOOK_ORDER + EXT_BOOK_ORDER
                                                                          if b in lt) + ".", ""]
    if xj:
        L += _extension_md(xj)
    mk = j["marks"]
    if mk:
        L += ["## Marks (fixed capital: 1/20 per tranche, idle capital at zero)", "",
              "| Book | Sessions | Exposure (last) | Gross | Net 20 bps | Net name-level | Benchmark | Active net 20 bps |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for b in BOOK_ORDER + EXT_BOOK_ORDER:
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
        L += [f"Deflated Sharpe of the daily active net-20 bps series (N = {N_TRIALS_DSR}, V[SR] = 0.00387): "
              + "; ".join(f"{b} {v.get('dsr', float('nan')):.3f} ({v.get('status')})" if "dsr" in v else f"{b} {v.get('status')}"
                          for b, v in ds.items()) + "."]
        dx = (xj.get("dsr_paper") or {}) if xj else {}
        if dx:
            L += [f"Extension books (N = {xj['dsr_n_trials']}, the trial ledger at registration; V[SR] = 0.00387): "
                  + "; ".join(f"{b} {v.get('dsr', float('nan')):.3f} ({v.get('status')})" if "dsr" in v
                              else f"{b} {v.get('status')}" for b, v in dx.items()) + "."]
        L.append("")
    idem = j["idempotency"]
    if idem:
        L += ["## Idempotency proof", "",
              f"A second run on the same data ({idem.get('note')}; scoring frame rebuilt from the store in this run: "
              f"{idem.get('frame_rebuilt_in_this_run')}; ingest decisions {idem.get('ingest_decisions_in_this_run')}): "
              f"ledger SHA-256 before and after identical "
              f"{idem.get('identical')}; rows appended {idem.get('rows_appended')}; recomputed signals of "
              f"{idem.get('recomputed_signal_date')} equal the ledger {idem.get('recomputed_signals_equal_ledger')}; "
              f"recomputed marks equal the ledger {idem.get('recomputed_marks_equal_ledger')}"
              + (f"; recomputed extension signals of {idem.get('recomputed_signal_date_expanding')} equal the ledger "
                 f"{idem.get('recomputed_signals_equal_ledger_expanding')} (expanding scores max |diff| "
                 f"{idem.get('recomputed_scores_max_abs_diff_expanding')})"
                 if idem.get("recomputed_signal_date_expanding") else "") + ".", "",
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
              f"{rg.get('ledger_identical')}; per-date score files identical {rg.get('score_files_identical')}"
              + (f" (extension score files identical {rg.get('score_files_identical_expanding')})"
                 if rg.get("score_files_identical_expanding") is not None else "")
              + f"; committed ledger untouched {rg.get('committed_ledger_untouched')}.", "",
              "| File | Committed SHA-256 | Regenerated SHA-256 |", "|---|---|---|"]
        for k, v in (rg.get("ledger_files") or {}).items():
            L.append(f"| {k} | `{(v.get('committed') or '')[:16]}` | `{(v.get('regenerated') or '')[:16]}` |")
        L.append("")
        fo = rg.get("frozen_only") or {}
        if fo:
            L += [f"Frozen books without the extension: {fo.get('procedure')}. The regenerated files equal the committed "
                  f"ledger's frozen-book rows byte for byte: {fo.get('identical_to_committed_frozen_rows')} ("
                  + ", ".join(f"{k} {v.get('identical')}" for k, v in (fo.get('files') or {}).items())
                  + f"); and equal the ledger as it stood before the amendment: {fo.get('identical_to_pre_amendment_ledger')}. "
                  f"state.json without its `extension` key is the file the job writes with the extension off: "
                  f"{fo.get('state_identical_to_committed_without_extension')} (equal to the pre-amendment state.json: "
                  f"{fo.get('state_equal_to_pre_amendment_state')}).",
                  ""]
    return "\n".join(L) + "\n"


def _extension_md(x: dict) -> list[str]:
    L = ["## Extension 1: expanding-window challenger (SPEC.md amendment 10)", "",
         f"Registered {x['registered_utc']}; extension spec hash `{x['spec_hash'][:16]}`; the frozen books' spec hash "
         f"`{x['extends_spec_hash'][:16]}` and their rows are unchanged byte for byte.", "",
         f"Why: {x['motivation']}", "", f"What: {x['definition']}", "", f"Backfill: {x['backfill_note']}", ""]
    for m, v in (x.get("models") or {}).items():
        tw = v["training_window"]
        L += [f"Model {m} (`{v['metadata']}`): trained as of {v['trained_as_of']} (train_end {v['spec']['train_end']}), "
              f"{tw['rows']:,} rows, {tw['sessions']} sessions {tw['first_date']}..{tw['last_date']}, {tw['tickers']} tickers, "
              f"{tw['rows_purged_exit_ge_test_start']} rows removed by the exit-date purge, label mean {tw['label_mean']:.4f}; "
              f"fit {v['fit_seconds'].get('lgbm')} s with two threads; LightGBM file SHA-256 "
              f"`{v['files_sha256'].get('lgbm', '')[:16]}`.", ""]
    rp = x.get("trainer_reproduction") or {}
    if rp:
        L += [f"Trainer reproduction: the paper's expanding-window trainer on the research holdout fold (train end "
              f"{rp['fold']['train_end']}, {rp['train_rows']:,} training rows {rp['training_window']['first_date']}.."
              f"{rp['training_window']['last_date']}, the same rows as Q9's fold) scores {rp['rows_matched']:,} holdout rows; "
              f"max |score - Q9 score| = {rp['max_abs_score_diff']:.3g}; bit-identical ({rp['identical_rule']}): "
              f"{rp['identical']}."
              + (f" Not compared: {len(rp['test_rows_label_exit_after_research_end'])} test rows whose label exits after "
                 "the research end (" + ", ".join(f"{t['ticker']} {t['date']}" for t in rp["test_rows_label_exit_after_research_end"])
                 + ")." if rp.get("test_rows_label_exit_after_research_end") else ""), ""]
        ex = rp.get("explanation") or {}
        if ex:
            rr, pp = ex.get("on_research_frame") or {}, ex.get("on_paper_frame") or {}
            cc = ex.get("training_cells_paper_vs_research_frame") or {}
            how = "exactly" if rr.get("identical") else "not exactly"
            L += [f"Why not bit-identical: the same trainer on the research frame (`ml/data_10y`, the frame Q9 ran on) "
                  f"reproduces Q9's holdout scores {how} ({rr.get('rows_matched'):,} rows, max |diff| "
                  f"{rr.get('max_abs_score_diff')}), so the trainer is Q9's. The paper frame carries the live "
                  f"corporate-action feed's rescaling (consistency proof above): {cc.get('feature_cells_differing'):,} "
                  f"training cells differ from the research frame (at most {cc.get('max_abs_feature_diff', 0):.2g}, in "
                  f"{cc.get('rows_with_a_differing_cell')} rows of {cc.get('tickers_with_a_differing_cell')} tickers; "
                  f"label cells differing {cc.get('label_cells_differing')}); LightGBM's bin boundaries and split "
                  f"thresholds come from the training values, so the fitted trees differ slightly (the frozen trainer's "
                  f"504-session reproduction happened to come out exact). Effect on the holdout: AUC "
                  f"{pp.get('auc_paper_frame', 0):.5f} on the paper frame vs {pp.get('auc_q9', 0):.5f} for Q9; per-date "
                  f"Spearman correlation with Q9's scores min {pp.get('per_date_spearman_min', 0):.8f}, mean "
                  f"{pp.get('per_date_spearman_mean', 0):.8f}; per-date top-decile overlap min "
                  f"{100 * pp.get('per_date_top_decile_overlap_min', 0):.1f}%, mean "
                  f"{100 * pp.get('per_date_top_decile_overlap_mean', 0):.1f}% ({pp.get('dates')} dates).", ""]
    lc = x.get("lost_state_check") or {}
    if lc:
        L += [f"Lost-state check (`ml/results/improve2/paper/lost_state_check_expanding.json`): {lc.get('test')}: the model "
              f"was retrained in a child process and equals the committed metadata ({lc.get('retrain_equal_to_committed_metadata')}); "
              f"regenerated score files {lc.get('regenerated_score_files_expanding')}; every file byte-identical to before "
              f"{lc.get('all_identical')} ({lc.get('note')}).", ""]
    bp = x.get("backfill_proof") or {}
    if bp:
        er = bp.get("existing_rows") or {}
        L += [f"Backfill proof (`ml/results/improve2/paper/extension_backfill.json`): the run appended "
              f"{bp.get('rows_appended')} rows ({bp.get('appended_rows_by_book')}) for signal dates "
              f"{bp.get('appended_signal_dates')} and marked sessions {bp.get('appended_mark_sessions')}; only extension rows "
              f"appended {bp.get('only_extension_rows_appended')}; the existing rows {bp.get('rows_before')} are unchanged "
              f"byte for byte {bp.get('existing_rows_unchanged')}; ingest run {bp.get('ingest_run')}, frame rebuilt "
              f"{bp.get('frame_rebuilt')}.", "",
              "| File | Bytes before | SHA-256 before | SHA-256 of the same bytes after | Unchanged |", "|---|---:|---|---|---|"]
        for k, v in er.items():
            L.append(f"| {k} | {v.get('bytes_before')} | `{(v.get('sha256_before') or '')[:16]}` | "
                     f"`{(v.get('sha256_of_first_bytes_after') or '')[:16]}` | {v.get('existing_rows_unchanged')} |")
        L.append("")
    ov = x.get("basket_overlap") or []
    if ov:
        L += ["Overlap with the frozen books (names in both baskets on the signal date):", "",
              "| Signal date | Book | Names | Shared with primary | Share | Shared with counterpart | Share |",
              "|---|---|---:|---:|---:|---:|---:|"]
        for r in ov:
            cp = x["counterpart"][r["book"]]
            L.append(f"| {r['signal_date']} | {r['book']} | {r['names']} | {r['shared_with_primary']} of "
                     f"{r['names_of_primary']} | {100 * r['share_of_book_shared_with_primary']:.0f}% | "
                     f"{r[f'shared_with_{cp}']} of {r[f'names_of_{cp}']} ({cp}) | "
                     f"{100 * r[f'share_of_book_shared_with_{cp}']:.0f}% |")
        L.append("")
    sa = x.get("score_agreement") or []
    if sa:
        L += ["Score agreement with the primary model (Spearman over the date's universe): "
              + "; ".join(f"{r['signal_date']} raw {r['spearman_raw']:.3f}, neutralised {r['spearman_neutral']:.3f} "
                          f"({r['universe']} names)" for r in sa) + ".", ""]
    return L
